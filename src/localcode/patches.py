"""Strict one-shot unified-diff application inside a disposable workspace."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from .tools import ToolError, ToolResult
from .tools.base import RepositoryPolicy
from .workspace import _run_git


MAX_PATCH_BYTES = 65_536
MAX_PATCH_FILES = 8
MAX_CHANGED_LINES = 400
MAX_EDITABLE_FILE_BYTES = 1_048_576

_DIFF_HEADER = re.compile(r"^diff --git a/([^\s]+) b/([^\s]+)$")
_HUNK_HEADER = re.compile(r"^@@ -[0-9]+(?:,[0-9]+)? \+[0-9]+(?:,[0-9]+)? @@(?: .*)?$")
_FORBIDDEN_MARKERS = (
    "new file mode ",
    "deleted file mode ",
    "old mode ",
    "new mode ",
    "rename from ",
    "rename to ",
    "copy from ",
    "copy to ",
    "GIT binary patch",
    "Binary files ",
)


@dataclass(frozen=True, slots=True)
class PatchSummary:
    paths: tuple[str, ...]
    added_lines: int
    removed_lines: int


def apply_patch(
    root: str | Path,
    patch: str,
    *,
    max_bytes: int = MAX_PATCH_BYTES,
    max_files: int = MAX_PATCH_FILES,
    max_changed_lines: int = MAX_CHANGED_LINES,
) -> ToolResult:
    """Validate and atomically apply one bounded patch to clean tracked files."""

    _validate_positive_limit(max_bytes, "max_bytes", MAX_PATCH_BYTES)
    _validate_positive_limit(max_files, "max_files", MAX_PATCH_FILES)
    _validate_positive_limit(max_changed_lines, "max_changed_lines", MAX_CHANGED_LINES)
    if not isinstance(patch, str) or not patch or "\x00" in patch:
        raise ToolError("invalid_patch", "patch must be non-empty text without NUL bytes")
    if len(patch.encode("utf-8")) > max_bytes:
        raise ToolError("patch_too_large", f"patch exceeds {max_bytes} bytes")

    policy = RepositoryPolicy.from_root(root)
    git_root = Path(_run_git(policy.root, ["rev-parse", "--show-toplevel"]).strip()).resolve()
    if git_root != policy.root:
        raise ToolError("git_root_mismatch", "workspace root must equal Git's top-level directory")
    staged = _run_git(policy.root, ["diff", "--cached", "--name-only", "-z"])
    if staged:
        raise ToolError("staged_changes", "apply_patch refuses a workspace with staged changes")
    untracked = _run_git(policy.root, ["ls-files", "--others", "--exclude-standard", "-z"])
    if untracked:
        raise ToolError("untracked_files", "apply_patch refuses a workspace with untracked files")
    changed_before = _changed_paths(policy.root)

    summary = _parse_patch(policy, patch)
    if len(summary.paths) > max_files:
        raise ToolError("patch_file_limit", f"patch exceeds {max_files} files")
    if summary.added_lines + summary.removed_lines > max_changed_lines:
        raise ToolError("patch_line_limit", f"patch exceeds {max_changed_lines} changed lines")

    _run_git(policy.root, ["apply", "--check", "--whitespace=error-all", "-"], input_text=patch)
    _run_git(policy.root, ["apply", "--whitespace=error-all", "-"], input_text=patch)
    changed = _changed_paths(policy.root)
    allowed_changed_paths = set(changed_before) | set(summary.paths)
    if not set(changed).issubset(allowed_changed_paths):
        raise ToolError("patch_postcondition", "patch changed a path outside the validated set")

    return ToolResult(
        content="Applied patch to " + ", ".join(summary.paths),
        metadata=(
            ("file_count", len(summary.paths)),
            ("added_lines", summary.added_lines),
            ("removed_lines", summary.removed_lines),
        ),
    )


def _parse_patch(policy: RepositoryPolicy, patch: str) -> PatchSummary:
    lines = patch.splitlines()
    if any(line.startswith(_FORBIDDEN_MARKERS) for line in lines):
        raise ToolError("unsupported_patch", "file creation, deletion, rename, mode, and binary patches are forbidden")

    paths: list[str] = []
    added_lines = 0
    removed_lines = 0
    index = 0
    while index < len(lines):
        header = _DIFF_HEADER.fullmatch(lines[index])
        if header is None:
            raise ToolError("invalid_patch", f"expected diff header at line {index + 1}")
        old_name, new_name = header.groups()
        if old_name != new_name:
            raise ToolError("unsupported_patch", "renaming files is forbidden")
        relative, resolved = policy.resolve(old_name, kind="file")
        path = relative.as_posix()
        if path in paths:
            raise ToolError("duplicate_patch_path", f"patch contains duplicate file section: {path}")
        try:
            if resolved.stat().st_size > MAX_EDITABLE_FILE_BYTES:
                raise ToolError("file_too_large", f"editable file exceeds one MiB: {path}")
            resolved.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise ToolError("binary_file", f"editable file is not UTF-8 text: {path}") from exc
        except OSError as exc:
            raise ToolError("read_error", f"could not inspect editable file: {path}") from exc

        index += 1
        if index >= len(lines) or lines[index] != f"--- a/{path}":
            raise ToolError("invalid_patch", f"missing old-file header for {path}")
        index += 1
        if index >= len(lines) or lines[index] != f"+++ b/{path}":
            raise ToolError("invalid_patch", f"missing new-file header for {path}")
        index += 1

        hunk_count = 0
        while index < len(lines) and not lines[index].startswith("diff --git "):
            if not _HUNK_HEADER.fullmatch(lines[index]):
                raise ToolError("invalid_patch", f"invalid hunk header at line {index + 1}")
            hunk_count += 1
            index += 1
            hunk_line_count = 0
            while index < len(lines) and not lines[index].startswith(("@@ ", "diff --git ")):
                line = lines[index]
                if not line or line[0] not in {" ", "+", "-", "\\"}:
                    raise ToolError("invalid_patch", f"invalid hunk line at line {index + 1}")
                if line.startswith("+"):
                    added_lines += 1
                elif line.startswith("-"):
                    removed_lines += 1
                hunk_line_count += 1
                index += 1
            if hunk_line_count == 0:
                raise ToolError("invalid_patch", f"empty hunk for {path}")
        if hunk_count == 0:
            raise ToolError("invalid_patch", f"patch has no hunks for {path}")
        paths.append(path)

    if not paths:
        raise ToolError("invalid_patch", "patch contains no file sections")
    return PatchSummary(tuple(sorted(paths)), added_lines, removed_lines)


def _changed_paths(root: Path) -> tuple[str, ...]:
    output = _run_git(root, ["diff", "--name-only", "-z", "--no-ext-diff", "--no-textconv"])
    return tuple(sorted(name for name in output.split("\x00") if name))


def _validate_positive_limit(value: int, name: str, maximum: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
        raise ToolError("invalid_argument", f"{name} must be between 1 and {maximum}")
