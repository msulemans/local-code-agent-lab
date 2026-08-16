"""Disposable micro-repository workspaces with an isolated Git baseline."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess

from .tools import ToolError
from .tools.base import RepositoryPolicy


MAX_WORKSPACE_FILES = 2_000
MAX_WORKSPACE_BYTES = 64 * 1_024 * 1_024


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
