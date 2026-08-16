"""Disposable micro-repository workspaces with an isolated Git baseline."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess

from .tools import ToolError, ToolResult
from .tools.base import RepositoryPolicy


MAX_WORKSPACE_FILES = 2_000
MAX_WORKSPACE_BYTES = 64 * 1_024 * 1_024
MAX_WRITE_BYTES = 1_048_576


@dataclass(frozen=True, slots=True)
class Workspace:
    source_root: Path
    root: Path
    baseline_commit: str
    copied_files: int
    copied_bytes: int


def create_workspace(
    source_root: str | Path,
    destination: str | Path,
    *,
    max_files: int = MAX_WORKSPACE_FILES,
    max_bytes: int = MAX_WORKSPACE_BYTES,
    skip_symlinks: bool = False,
) -> Workspace:
    """Copy allowed regular files once and create a clean private Git baseline.

    Symlinks are rejected by default. Real upstream repositories frequently
    contain documentation or fixture symlinks, so callers that do not need
    those entries may opt to skip them; targets are never followed or copied.
    """

    if isinstance(max_files, bool) or not isinstance(max_files, int) or max_files < 1:
        raise ToolError("invalid_argument", "max_files must be a positive integer")
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes < 1:
        raise ToolError("invalid_argument", "max_bytes must be a positive integer")

    policy = RepositoryPolicy.from_root(source_root)
    target = Path(destination)
    if target.exists() or target.is_symlink():
        raise ToolError("workspace_exists", f"workspace destination already exists: {target}")
    try:
        target_parent = target.parent.resolve(strict=True)
    except OSError as exc:
        raise ToolError("invalid_workspace_parent", f"workspace parent does not exist: {target.parent}") from exc
    target_absolute = target_parent / target.name
    if target_absolute == policy.root or target_absolute in policy.root.parents or policy.root in target_absolute.parents:
        raise ToolError("workspace_overlap", "workspace and source repository must not overlap")

    target.mkdir()
    copied_files = 0
    copied_bytes = 0
    for current_raw, directory_names, file_names in os.walk(policy.root, followlinks=False):
        current = Path(current_raw)
        allowed_directories: list[str] = []
        for name in sorted(directory_names):
            child = current / name
            relative = PurePosixPath(child.relative_to(policy.root).as_posix())
            if child.is_symlink():
                if skip_symlinks:
                    continue
                raise ToolError("symlink_rejected", f"workspace source contains a symlink: {relative}")
            if policy.exclusion_reason(relative) is None:
                allowed_directories.append(name)
        directory_names[:] = allowed_directories

        for name in sorted(file_names):
            source = current / name
            relative = PurePosixPath(source.relative_to(policy.root).as_posix())
            if source.is_symlink():
                if skip_symlinks:
                    continue
                raise ToolError("symlink_rejected", f"workspace source contains a symlink: {relative}")
            if policy.exclusion_reason(relative) is not None:
                continue
            if not source.is_file():
                raise ToolError("unsupported_file", f"workspace source is not a regular file: {relative}")
            try:
                size = source.stat().st_size
            except OSError as exc:
                raise ToolError("workspace_read_error", f"could not inspect source file: {relative}") from exc
            copied_files += 1
            copied_bytes += size
            if copied_files > max_files:
                raise ToolError("workspace_file_limit", f"workspace exceeds {max_files} files")
            if copied_bytes > max_bytes:
                raise ToolError("workspace_byte_limit", f"workspace exceeds {max_bytes} bytes")

            destination_file = target / Path(relative.as_posix())
            destination_file.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copy2(source, destination_file, follow_symlinks=False)
            except OSError as exc:
                raise ToolError("workspace_copy_error", f"could not copy source file: {relative}") from exc

    _run_git(target, ["-c", "init.templateDir=", "init", "--quiet"])
    _run_git(target, ["add", "--all"])
    _run_git(
        target,
        [
            "-c",
            "user.name=LocalCode",
            "-c",
            "user.email=localcode@invalid",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "--quiet",
            "--no-gpg-sign",
            "-m",
            "LocalCode disposable baseline",
        ],
    )
    baseline_commit = _run_git(target, ["rev-parse", "HEAD"]).strip()
    if _run_git(target, ["status", "--porcelain", "--untracked-files=all"]):
        raise ToolError("workspace_not_clean", "new workspace is not clean after baseline commit")
    return Workspace(
        source_root=policy.root,
        root=target.resolve(strict=True),
        baseline_commit=baseline_commit,
        copied_files=copied_files,
        copied_bytes=copied_bytes,
    )


def write_file(
    root: str | Path,
    path: str,
    content: str,
    *,
    max_bytes: int = MAX_WRITE_BYTES,
) -> ToolResult:
    """Atomically replace one existing tracked workspace file with new content.

    Mirrors apply_patch's safety scope so small models that cannot construct a
    line-accurate unified diff can still edit a file: only an existing,
    tracked, UTF-8 file may be replaced; no file creation, deletion, rename, or
    path escape is possible.  The write is atomic (temp file + rename), so a
    failure never leaves a partial file, and the change appears in git_diff.
    """

    if not isinstance(path, str) or not path or "\x00" in path:
        raise ToolError("invalid_path", "path must be non-empty text without NUL bytes")
    if not isinstance(content, str):
        raise ToolError("invalid_content", "content must be text")
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes < 1 or max_bytes > MAX_WRITE_BYTES:
        raise ToolError("invalid_argument", f"max_bytes must be an integer in 1..{MAX_WRITE_BYTES}")
    encoded = content.encode("utf-8")
    if len(encoded) > max_bytes:
        raise ToolError("content_too_large", f"content exceeds {max_bytes} bytes")

    policy = RepositoryPolicy.from_root(root)
    relative, resolved = policy.resolve(path, kind="file")
    if not resolved.is_file():
        raise ToolError("path_does_not_exist", f"file does not exist: {relative.as_posix()}")
    if resolved.stat().st_size > MAX_WRITE_BYTES:
        raise ToolError("file_too_large", f"existing file exceeds one MiB: {relative.as_posix()}")
    tracked = _run_git(policy.root, ["ls-files", "--", relative.as_posix()]).strip()
    if not tracked:
        raise ToolError("untracked_target", f"write_file refuses a file Git does not track: {relative.as_posix()}")

    temporary = resolved.with_name(resolved.name + ".localcode-tmp")
    try:
        temporary.write_text(content, encoding="utf-8", newline="")
        os.replace(temporary, resolved)
    except OSError as exc:
        raise ToolError("write_error", f"could not replace file: {relative.as_posix()}") from exc
    finally:
        if temporary.exists():
            temporary.unlink()

    return ToolResult(
        content=f"Replaced file {relative.as_posix()} ({len(encoded)} bytes)",
        metadata=(
            ("path", relative.as_posix()),
            ("bytes", len(encoded)),
        ),
    )


def edit_file(
    root: str | Path,
    path: str,
    old_string: str,
    new_string: str,
    *,
    max_bytes: int = MAX_WRITE_BYTES,
) -> ToolResult:
    """Replace one exact, unique snippet inside an existing tracked file.

    This is the search-and-replace edit format that small models can use
    reliably on large files: the model copies an exact snippet it read (no
    line numbers, no unified-diff construction) and supplies its replacement.
    The old snippet must occur exactly once; the write is atomic and the file
    remains bounded.
    """

    if not isinstance(path, str) or not path or "\x00" in path:
        raise ToolError("invalid_path", "path must be non-empty text without NUL bytes")
    if not isinstance(old_string, str) or not old_string:
        raise ToolError("invalid_old_string", "old_string must be non-empty text")
    if not isinstance(new_string, str):
        raise ToolError("invalid_new_string", "new_string must be text")
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes < 1 or max_bytes > MAX_WRITE_BYTES:
        raise ToolError("invalid_argument", f"max_bytes must be an integer in 1..{MAX_WRITE_BYTES}")

    policy = RepositoryPolicy.from_root(root)
    relative, resolved = policy.resolve(path, kind="file")
    if not resolved.is_file():
        raise ToolError("path_does_not_exist", f"file does not exist: {relative.as_posix()}")
    tracked = _run_git(policy.root, ["ls-files", "--", relative.as_posix()]).strip()
    if not tracked:
        raise ToolError("untracked_target", f"edit_file refuses a file Git does not track: {relative.as_posix()}")

    try:
        current = resolved.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ToolError("binary_file", f"editable file is not UTF-8 text: {relative.as_posix()}") from exc
    if len(current.encode("utf-8")) > max_bytes:
        raise ToolError("file_too_large", f"file exceeds {max_bytes} bytes: {relative.as_posix()}")
    occurrences = current.count(old_string)
    if occurrences != 1:
        raise ToolError(
            "edit_not_unique",
            f"old_string must match exactly once; found {occurrences}",
        )
    updated = current.replace(old_string, new_string)
    if len(updated.encode("utf-8")) > max_bytes:
        raise ToolError("file_too_large", f"edited file exceeds {max_bytes} bytes: {relative.as_posix()}")

    temporary = resolved.with_name(resolved.name + ".localcode-tmp")
    try:
        temporary.write_text(updated, encoding="utf-8", newline="")
        os.replace(temporary, resolved)
    except OSError as exc:
        raise ToolError("write_error", f"could not edit file: {relative.as_posix()}") from exc
    finally:
        if temporary.exists():
            temporary.unlink()

    return ToolResult(
        content=f"Edited file {relative.as_posix()}",
        metadata=(
            ("path", relative.as_posix()),
            ("old_length", len(old_string)),
            ("new_length", len(new_string)),
        ),
    )


def _run_git(root: Path, arguments: list[str], *, input_text: str | None = None) -> str:
    environment = os.environ.copy()
    environment["GIT_CONFIG_NOSYSTEM"] = "1"
    environment["GIT_CONFIG_GLOBAL"] = os.devnull
    environment["GIT_TERMINAL_PROMPT"] = "0"
    environment["GIT_PAGER"] = "cat"
    environment.pop("GIT_EXTERNAL_DIFF", None)
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), *arguments],
            input=input_text,
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
            env=environment,
        )
    except FileNotFoundError as exc:
        raise ToolError("git_unavailable", "git executable was not found") from exc
    except subprocess.TimeoutExpired as exc:
        raise ToolError("git_timeout", "git exceeded 10 seconds") from exc
    except subprocess.CalledProcessError as exc:
        message = exc.stderr.strip()[:4_096]
        raise ToolError("git_error", message or f"git exited with code {exc.returncode}") from exc
    return completed.stdout
