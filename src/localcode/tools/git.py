"""A bounded Git diff reader with external helpers disabled."""

from __future__ import annotations

import os
from pathlib import Path
import selectors
import subprocess
import time

from .base import RepositoryPolicy, ToolError, ToolResult


MAX_DIFF_BYTES = 65_536
MAX_NAME_BYTES = 262_144
GIT_TIMEOUT_SECONDS = 10


def _git_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment["GIT_CONFIG_NOSYSTEM"] = "1"
    environment["GIT_PAGER"] = "cat"
    environment["PAGER"] = "cat"
    environment.pop("GIT_EXTERNAL_DIFF", None)
    return environment


def _run_git(root: Path, arguments: list[str], output_limit: int) -> tuple[bytes, bool]:
    command = [
        "git",
        "-C",
        str(root),
        "-c",
        "core.pager=cat",
        *arguments,
    ]
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=_git_environment(),
        )
    except FileNotFoundError as exc:
        raise ToolError("git_unavailable", "git executable was not found") from exc

    if process.stdout is None or process.stderr is None:
        process.kill()
        raise ToolError("git_error", "could not capture Git output")

    stdout = bytearray()
    stderr = bytearray()
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ, "stdout")
    selector.register(process.stderr, selectors.EVENT_READ, "stderr")
    deadline = time.monotonic() + GIT_TIMEOUT_SECONDS

    try:
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                process.kill()
                process.wait()
                raise ToolError("git_timeout", f"git exceeded {GIT_TIMEOUT_SECONDS} seconds")

            for key, _ in selector.select(remaining):
                chunk = os.read(key.fileobj.fileno(), 8_192)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                if key.data == "stderr":
                    room = max(0, 4_096 - len(stderr))
                    stderr.extend(chunk[:room])
                    continue

                room = max(0, output_limit + 1 - len(stdout))
                stdout.extend(chunk[:room])
                if len(stdout) > output_limit or len(chunk) > room:
                    process.kill()
                    process.wait()
                    return bytes(stdout[:output_limit]), True
    finally:
        selector.close()
        process.stdout.close()
        process.stderr.close()

    return_code = process.wait()
    if return_code != 0:
        message = bytes(stderr).decode("utf-8", errors="replace").strip()
        raise ToolError("git_error", message or f"git exited with code {return_code}")
    return bytes(stdout), False


def git_diff(
    root: str | Path,
    path: str = ".",
    *,
    staged: bool = False,
    max_bytes: int = MAX_DIFF_BYTES,
) -> ToolResult:
    """Return an allowed, bounded working-tree or staged Git diff."""

    if not isinstance(staged, bool):
        raise ToolError("invalid_argument", "staged must be a boolean")
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or not 1 <= max_bytes <= MAX_DIFF_BYTES:
        raise ToolError("invalid_argument", f"max_bytes must be between 1 and {MAX_DIFF_BYTES}")

    policy = RepositoryPolicy.from_root(root)
    top_level_bytes, top_level_truncated = _run_git(
        policy.root,
        ["rev-parse", "--show-toplevel"],
        4_096,
    )
    if top_level_truncated:
        raise ToolError("git_root_mismatch", "Git top-level path exceeded its safety limit")
    try:
        git_top_level = Path(top_level_bytes.decode("utf-8").strip()).resolve(strict=True)
    except (OSError, UnicodeDecodeError) as exc:
        raise ToolError("git_root_mismatch", "Git returned an invalid top-level path") from exc
    if git_top_level != policy.root:
        raise ToolError(
            "git_root_mismatch",
            "repository root must be Git's top-level working tree directory",
        )

    requested_relative, _ = policy.resolve(path, require_exists=False)
    diff_mode = ["--cached"] if staged else []
    safe_diff_options = ["--no-ext-diff", "--no-textconv", "--no-color"]

    names_bytes, names_truncated = _run_git(
        policy.root,
        ["diff", *diff_mode, *safe_diff_options, "--name-only", "-z", "--", requested_relative.as_posix()],
        MAX_NAME_BYTES,
    )
    if names_truncated:
        raise ToolError("too_many_changes", "changed-file discovery exceeded its safety limit")
    try:
        changed_names = [name.decode("utf-8") for name in names_bytes.split(b"\x00") if name]
    except UnicodeDecodeError as exc:
        raise ToolError("unsupported_path", "Git reported a non-UTF-8 path") from exc

    allowed_names: list[str] = []
    excluded_count = 0
    for name in changed_names:
        relative = policy.relative_path(name)
        if policy.exclusion_reason(relative) is not None:
            excluded_count += 1
            continue
        policy.resolve(name, require_exists=False)
        allowed_names.append(relative.as_posix())

    if not allowed_names:
        return ToolResult(
            content="",
            metadata=(("file_count", 0), ("excluded_file_count", excluded_count), ("staged", staged)),
        )

    diff_bytes, truncated = _run_git(
        policy.root,
        ["diff", *diff_mode, *safe_diff_options, "--", *allowed_names],
        max_bytes,
    )
    content = diff_bytes.decode("utf-8", errors="replace")
    return ToolResult(
        content=content,
        truncated=truncated,
        metadata=(
            ("file_count", len(allowed_names)),
            ("excluded_file_count", excluded_count),
            ("staged", staged),
        ),
    )
