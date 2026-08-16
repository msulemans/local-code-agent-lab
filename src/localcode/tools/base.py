"""Shared policy and result types for read-only repository tools."""

from __future__ import annotations

from dataclasses import dataclass
import fnmatch
import os
from pathlib import Path, PurePosixPath
from typing import Iterator, TypeAlias


MetadataValue: TypeAlias = str | int | bool


class ToolError(ValueError):
    """A safe, expected tool failure suitable for returning to an agent."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class ToolResult:
    """A bounded immutable observation returned by a repository tool."""

    content: str
    truncated: bool = False
    metadata: tuple[tuple[str, MetadataValue], ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.content, str):
            raise TypeError("content must be a string")
        if not isinstance(self.truncated, bool):
            raise TypeError("truncated must be a boolean")
        if not isinstance(self.metadata, tuple):
            raise TypeError("metadata must be an immutable tuple")

        names: set[str] = set()
        for item in self.metadata:
            if not isinstance(item, tuple) or len(item) != 2:
                raise TypeError("metadata entries must be immutable name/value pairs")
            name, value = item
            if not isinstance(name, str) or not name or name in names:
                raise TypeError("metadata names must be unique non-empty strings")
            if not isinstance(value, (str, int, bool)):
                raise TypeError("metadata values must be strings, integers, or booleans")
            names.add(name)

    def metadata_dict(self) -> dict[str, MetadataValue]:
        return dict(self.metadata)


EXCLUDED_DIRECTORY_NAMES = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".venv",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "node_modules",
        "runs",
        "models",
        "checkpoints",
        "adapters",
    }
)

EXCLUDED_RELATIVE_PREFIXES = (
    PurePosixPath("data/raw"),
    PurePosixPath("data/processed"),
    PurePosixPath("evaluation_results"),
    PurePosixPath("logs"),
)

SECRET_EXACT_NAMES = frozenset(
    {
        ".env",
        ".npmrc",
        ".pypirc",
        "credentials",
        "credentials.json",
        "id_dsa",
        "id_ed25519",
        "id_rsa",
        "known_hosts",
    }
)

SECRET_GLOBS = (".env.*", "*.key", "*.p12", "*.pem", "*.pfx")


# Third-party code vendored into a repository tree (e.g. requests/packages)
# is never the fix site for a first-party issue and must not be surfaced as
# evidence or search matches that could misdirect the agent.
VENDORED_DIRECTORY_NAMES = frozenset(
    {"vendor", "vendored", "third_party", "_vendor", "site-packages", "packages"}
)


def is_vendored_path(relative: PurePosixPath) -> bool:
    """Return whether a repository-relative path sits under vendored code."""
    return any(part in VENDORED_DIRECTORY_NAMES for part in relative.parts)


@dataclass(frozen=True, slots=True)
class RepositoryPolicy:
    """Canonical path and exclusion policy anchored to one repository root."""

    root: Path

    @classmethod
    def from_root(cls, root: str | Path) -> "RepositoryPolicy":
        root_path = Path(root)
        try:
            resolved = root_path.resolve(strict=True)
        except OSError as exc:
            raise ToolError("invalid_root", f"repository root does not exist: {root_path}") from exc
        if not resolved.is_dir():
            raise ToolError("invalid_root", f"repository root is not a directory: {root_path}")
        return cls(resolved)

    def relative_path(self, raw_path: str) -> PurePosixPath:
        if not isinstance(raw_path, str) or not raw_path or "\x00" in raw_path:
            raise ToolError("invalid_path", "path must be a non-empty string without NUL bytes")
        relative = PurePosixPath(raw_path)
        if relative.is_absolute() or ".." in relative.parts:
            raise ToolError("path_escape", "path must stay within the repository")
        return relative

    def exclusion_reason(self, relative: PurePosixPath) -> str | None:
        parts = relative.parts
        if any(part in EXCLUDED_DIRECTORY_NAMES for part in parts):
            return "excluded directory"
        if any(part in {".ssh", ".aws", ".gnupg"} for part in parts):
            return "credential directory"
        if any(relative == prefix or prefix in relative.parents for prefix in EXCLUDED_RELATIVE_PREFIXES):
            return "generated or local artifact directory"

        name = relative.name
        if name == ".env.example":
            return None
        if name in SECRET_EXACT_NAMES or any(fnmatch.fnmatchcase(name, pattern) for pattern in SECRET_GLOBS):
            return "secret-like filename"
        return None

    def require_allowed(self, relative: PurePosixPath) -> None:
        reason = self.exclusion_reason(relative)
        if reason is not None:
            raise ToolError("excluded_path", f"path is excluded by policy ({reason}): {relative}")

    def resolve(
        self,
        raw_path: str,
        *,
        require_exists: bool = True,
        kind: str | None = None,
    ) -> tuple[PurePosixPath, Path]:
        relative = self.relative_path(raw_path)
        self.require_allowed(relative)

        current = self.root
        for part in relative.parts:
            if part == ".":
                continue
            current = current / part
            if current.is_symlink():
                raise ToolError("symlink_rejected", f"symlink paths are not readable: {relative}")

        try:
            resolved = current.resolve(strict=require_exists)
            resolved.relative_to(self.root)
        except (OSError, ValueError) as exc:
            if require_exists and not current.exists():
                raise ToolError("not_found", f"path does not exist: {relative}") from exc
            raise ToolError("path_escape", f"path resolves outside the repository: {relative}") from exc

        if require_exists:
            if kind == "file" and not resolved.is_file():
                raise ToolError("not_file", f"path is not a regular file: {relative}")
            if kind == "directory" and not resolved.is_dir():
                raise ToolError("not_directory", f"path is not a directory: {relative}")
        return relative, resolved

    def iter_files(
        self,
        start: Path,
        *,
        max_depth: int | None = None,
    ) -> Iterator[tuple[PurePosixPath, Path]]:
        """Yield allowed non-symlink files deterministically without following links."""

        for current_raw, directory_names, file_names in os.walk(start, followlinks=False):
            current = Path(current_raw)
            current_depth = len(current.relative_to(start).parts)
            allowed_directories: list[str] = []
            if max_depth is None or current_depth < max_depth:
                for name in sorted(directory_names):
                    child = current / name
                    relative = PurePosixPath(child.relative_to(self.root).as_posix())
                    if child.is_symlink() or self.exclusion_reason(relative) is not None:
                        continue
                    allowed_directories.append(name)
            directory_names[:] = allowed_directories

            for name in sorted(file_names):
                child = current / name
                relative = PurePosixPath(child.relative_to(self.root).as_posix())
                if child.is_symlink() or self.exclusion_reason(relative) is not None:
                    continue
                if child.is_file():
                    yield relative, child
