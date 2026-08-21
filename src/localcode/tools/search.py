"""Bounded deterministic repository text search."""

from __future__ import annotations

import fnmatch
from pathlib import Path, PurePosixPath
import re

from .base import RepositoryPolicy, ToolError, ToolResult, is_vendored_path
from .files import MAX_FILE_BYTES


MAX_QUERY_CHARS = 1_000
MAX_SEARCH_RESULTS = 200
MAX_SEARCH_FILES = 5_000
MAX_SEARCH_BYTES = 16_777_216
MAX_MATCH_CHARS = 300


def search_code(
    root: str | Path,
    query: str,
    path: str = ".",
    *,
    glob: str | None = None,
    max_results: int = 40,
    regex: bool = False,
    case_sensitive: bool = True,
    file_paths: list[str] | None = None,
) -> ToolResult:
    """Search allowed UTF-8 files without exposing excluded repository content.

    When ``file_paths`` is provided, search exactly those files instead of
    walking ``path``; each entry is resolved through the repository policy so
    excluded and escaping paths stay unreachable.
    """

    if not isinstance(query, str) or not query or len(query) > MAX_QUERY_CHARS:
        raise ToolError("invalid_argument", f"query must contain 1-{MAX_QUERY_CHARS} characters")
    if isinstance(max_results, bool) or not isinstance(max_results, int):
        raise ToolError("invalid_argument", "max_results must be an integer")
    if not 1 <= max_results <= MAX_SEARCH_RESULTS:
        raise ToolError("invalid_argument", f"max_results must be between 1 and {MAX_SEARCH_RESULTS}")
    if glob is not None and (not isinstance(glob, str) or not glob):
        raise ToolError("invalid_argument", "glob must be a non-empty string")
    if not isinstance(regex, bool) or not isinstance(case_sensitive, bool):
        raise ToolError("invalid_argument", "regex and case_sensitive must be booleans")
    if file_paths is not None and (
        not isinstance(file_paths, list)
        or not file_paths
        or any(not isinstance(item, str) or not item for item in file_paths)
    ):
        raise ToolError("invalid_argument", "file_paths must be a non-empty list of non-empty strings")

    flags = 0 if case_sensitive else re.IGNORECASE
    pattern_text = query if regex else re.escape(query)
    try:
        pattern = re.compile(pattern_text, flags)
    except re.error as exc:
        raise ToolError("invalid_regex", f"query is not a valid regular expression: {exc}") from exc

    policy = RepositoryPolicy.from_root(root)
    if file_paths is not None:
        resolved_paths: list[tuple[PurePosixPath, Path]] = []
        for raw_path in file_paths:
            relative, candidate = policy.resolve(raw_path)
            if not candidate.is_file():
                raise ToolError(
                    "invalid_path",
                    f"file_paths entry is not a file: {relative.as_posix()}",
                )
            resolved_paths.append((relative, candidate))
        candidates = iter(resolved_paths)
    else:
        start_relative, start = policy.resolve(path)
        if start.is_file():
            candidates = iter(((start_relative, start),))
        elif start.is_dir():
            candidates = policy.iter_files(start)
        else:
            raise ToolError("invalid_path", f"search path is not a file or directory: {start_relative}")

    matches: list[str] = []
    considered_files = 0
    scanned_files = 0
    scanned_bytes = 0
    truncated = False

    for relative, candidate in candidates:
        considered_files += 1
        if considered_files > MAX_SEARCH_FILES:
            truncated = True
            break
        if is_vendored_path(relative):
            continue
        relative_text = relative.as_posix()
        if glob is not None and not (
            fnmatch.fnmatchcase(relative_text, glob)
            or fnmatch.fnmatchcase(PurePosixPath(relative).name, glob)
        ):
            continue
        if scanned_bytes >= MAX_SEARCH_BYTES:
            truncated = True
            break

        size = candidate.stat().st_size
        if size > MAX_FILE_BYTES or scanned_bytes + size > MAX_SEARCH_BYTES:
            truncated = True
            continue
        raw = candidate.read_bytes()
        scanned_files += 1
        scanned_bytes += len(raw)
        if b"\x00" in raw[:8_192]:
            continue
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue

        for line_number, line in enumerate(text.splitlines(), start=1):
            if pattern.search(line) is None:
                continue
            if len(matches) == max_results:
                truncated = True
                break
            preview = line.expandtabs(4)
            if len(preview) > MAX_MATCH_CHARS:
                preview = preview[:MAX_MATCH_CHARS] + "…"
                truncated = True
            matches.append(f"{relative_text}:{line_number}: {preview}")
        if len(matches) == max_results:
            truncated = True
            break

    return ToolResult(
        content="\n".join(matches),
        truncated=truncated,
        metadata=(
            ("match_count", len(matches)),
            ("considered_files", considered_files),
            ("scanned_files", scanned_files),
            ("scanned_bytes", scanned_bytes),
        ),
    )
