"""Bounded file listing and reading tools."""

from __future__ import annotations

from pathlib import Path, PurePosixPath

from .base import RepositoryPolicy, ToolError, ToolResult


MAX_LIST_RESULTS = 1_000
MAX_LIST_DEPTH = 20
MAX_FILE_BYTES = 1_048_576
MAX_READ_LINES = 1_000
MAX_OUTPUT_CHARS = 65_536
MAX_LINE_CHARS = 2_000


def _bounded_integer(value: object, field: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ToolError("invalid_argument", f"{field} must be between {minimum} and {maximum}")
    return value


def list_files(
    root: str | Path,
    path: str = ".",
    *,
    max_depth: int = 4,
    max_results: int = 200,
) -> ToolResult:
    """List allowed repository files in stable lexical order."""

    max_depth = _bounded_integer(max_depth, "max_depth", 0, MAX_LIST_DEPTH)
    max_results = _bounded_integer(max_results, "max_results", 1, MAX_LIST_RESULTS)
    policy = RepositoryPolicy.from_root(root)
    start_relative, start = policy.resolve(path, kind="directory")

    results: list[str] = []
    truncated = False
    for relative, _ in policy.iter_files(start, max_depth=max_depth):
        within_start = PurePosixPath(relative).relative_to(start_relative)
        file_depth = max(0, len(within_start.parts) - 1)
        if file_depth > max_depth:
            continue
        if len(results) == max_results:
            truncated = True
            break
        results.append(relative.as_posix())

    return ToolResult(
        content="\n".join(results),
        truncated=truncated,
        metadata=(("file_count", len(results)), ("max_depth", max_depth)),
    )


def read_file(
    root: str | Path,
    path: str,
    *,
    start_line: int = 1,
    end_line: int | None = None,
    max_lines: int = 400,
) -> ToolResult:
    """Read a bounded UTF-8, line-numbered excerpt from one allowed file."""

    start_line = _bounded_integer(start_line, "start_line", 1, 10_000_000)
    max_lines = _bounded_integer(max_lines, "max_lines", 1, MAX_READ_LINES)
    if end_line is not None:
        end_line = _bounded_integer(end_line, "end_line", start_line, 10_000_000)

    policy = RepositoryPolicy.from_root(root)
    relative, resolved = policy.resolve(path, kind="file")
    size = resolved.stat().st_size
    if size > MAX_FILE_BYTES:
        raise ToolError(
            "file_too_large",
            f"file exceeds the {MAX_FILE_BYTES}-byte read limit: {relative}",
        )

    raw = resolved.read_bytes()
    if b"\x00" in raw[:8_192]:
        raise ToolError("binary_file", f"binary files are not readable: {relative}")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ToolError("binary_file", f"file is not valid UTF-8: {relative}") from exc

    lines = text.splitlines()
    requested_end = end_line if end_line is not None else start_line + max_lines - 1
    effective_end = min(requested_end, start_line + max_lines - 1, len(lines))
    truncated = effective_end < len(lines)

    rendered: list[str] = []
    characters = 0
    for line_number in range(start_line, effective_end + 1):
        line = lines[line_number - 1]
        if len(line) > MAX_LINE_CHARS:
            line = line[:MAX_LINE_CHARS] + "…"
            truncated = True
        rendered_line = f"{line_number:>6} | {line}"
        separator_cost = 1 if rendered else 0
        if characters + separator_cost + len(rendered_line) > MAX_OUTPUT_CHARS:
            truncated = True
            break
        rendered.append(rendered_line)
        characters += separator_cost + len(rendered_line)

    return ToolResult(
        content="\n".join(rendered),
        truncated=truncated,
        metadata=(
            ("file", relative.as_posix()),
            ("file_bytes", size),
            ("start_line", start_line),
            ("lines_returned", len(rendered)),
        ),
    )
