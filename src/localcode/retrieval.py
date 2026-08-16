"""Deterministic repository map and evidence ranking for LocalCode retrieval."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import re

from .tools.base import RepositoryPolicy


MAX_RETRIEVAL_FILES = 1_000
MAX_RETRIEVAL_FILE_BYTES = 1_048_576
MAX_RETRIEVAL_TOTAL_CHARS = 24_000
MAX_EXCERPT_LINES = 80
MAX_LINE_CHARS = 240

_TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|[0-9]+")
_PY_SYMBOL = re.compile(r"^\s*(?:async\s+def|def|class)\s+([A-Za-z_][A-Za-z0-9_]*)\b")
_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "any",
        "are",
        "as",
        "at",
        "be",
        "but",
        "by",
        "for",
        "from",
        "in",
        "is",
        "it",
        "no",
        "not",
        "of",
        "on",
        "or",
        "preserve",
        "return",
        "should",
        "the",
        "to",
        "value",
        "when",
        "while",
        "with",
    }
)


class RetrievalError(ValueError):
    """Raised when retrieval inputs or bounds are invalid."""


@dataclass(frozen=True, slots=True)
class RepositoryFile:
    path: str
    kind: str
    language: str
    size_bytes: int
    line_count: int
    symbols: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RepositoryMap:
    files: tuple[RepositoryFile, ...]
    truncated: bool = False

    def by_path(self) -> dict[str, RepositoryFile]:
        return {file.path: file for file in self.files}


@dataclass(frozen=True, slots=True)
class EvidenceExcerpt:
    path: str
    kind: str
    score: int
    reason: str
    start_line: int
    end_line: int
    content: str


@dataclass(frozen=True, slots=True)
class RetrievalPack:
    repository_map: RepositoryMap
    issue_terms: tuple[str, ...]
    excerpts: tuple[EvidenceExcerpt, ...]
    truncated: bool = False

    @property
    def selected_paths(self) -> tuple[str, ...]:
        return tuple(excerpt.path for excerpt in self.excerpts)

    def to_context(self) -> str:
        parts = ["REPOSITORY MAP"]
        for file in self.repository_map.files:
            symbol_text = ", ".join(file.symbols[:8]) if file.symbols else "-"
            parts.append(
                f"- {file.path} [{file.kind}; {file.language}; {file.line_count} lines; symbols: {symbol_text}]"
            )
        parts.append("RETRIEVED EVIDENCE")
        for excerpt in self.excerpts:
            parts.append(
                f"--- {excerpt.path}:{excerpt.start_line}-{excerpt.end_line} "
                f"score={excerpt.score} reason={excerpt.reason}\n{excerpt.content}"
            )
        if self.truncated or self.repository_map.truncated:
            parts.append("TRUNCATED: true")
        return "\n".join(parts)


@dataclass(frozen=True, slots=True)
class RetrievalRecall:
    expected_paths: tuple[str, ...]
    selected_paths: tuple[str, ...]
    recalled_paths: tuple[str, ...]

    @property
    def numerator(self) -> int:
        return len(self.recalled_paths)

    @property
    def denominator(self) -> int:
        return len(self.expected_paths)

    @property
    def recall(self) -> float:
        if not self.expected_paths:
            return 1.0
        return len(self.recalled_paths) / len(self.expected_paths)


def build_repository_map(
    root: str | Path,
    *,
    max_files: int = MAX_RETRIEVAL_FILES,
    max_file_bytes: int = MAX_RETRIEVAL_FILE_BYTES,
) -> RepositoryMap:
    """Return a deterministic map of allowed UTF-8 repository files."""

    _bounded_integer(max_files, "max_files", 1, MAX_RETRIEVAL_FILES)
    _bounded_integer(max_file_bytes, "max_file_bytes", 1, MAX_RETRIEVAL_FILE_BYTES)
    policy = RepositoryPolicy.from_root(root)
    files: list[RepositoryFile] = []
    truncated = False
    for relative, path in policy.iter_files(policy.root):
        if len(files) == max_files:
            truncated = True
            break
        size = path.stat().st_size
        if size > max_file_bytes:
            truncated = True
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        files.append(
            RepositoryFile(
                path=relative.as_posix(),
                kind=_file_kind(relative),
                language=_language(relative),
                size_bytes=size,
                line_count=len(text.splitlines()),
                symbols=_symbols(text),
            )
        )
    return RepositoryMap(tuple(files), truncated)


def select_retrieval_evidence(
    root: str | Path,
    issue: str,
    *,
    max_files: int = 6,
    max_excerpt_lines: int = 40,
    max_total_chars: int = 8_000,
) -> RetrievalPack:
    """Rank bounded source/test excerpts for one issue without editing anything."""

    if not isinstance(issue, str) or not issue.strip():
        raise RetrievalError("issue must be non-empty text")
    max_files = _bounded_integer(max_files, "max_files", 1, 50)
    max_excerpt_lines = _bounded_integer(max_excerpt_lines, "max_excerpt_lines", 1, MAX_EXCERPT_LINES)
    max_total_chars = _bounded_integer(max_total_chars, "max_total_chars", 512, MAX_RETRIEVAL_TOTAL_CHARS)
    repo_map = build_repository_map(root)
    policy = RepositoryPolicy.from_root(root)
    issue_terms = _tokens(issue)
    candidates: list[tuple[int, str, str, str, tuple[int, ...], str]] = []

    for file in repo_map.files:
        if file.kind == "issue":
            continue
        relative, path = policy.resolve(file.path, kind="file")
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        score, reason, matching_lines = _rank_file(file, text, issue_terms)
        if score <= 0:
            score, reason, matching_lines = _fallback_rank(file, text)
        candidates.append((score, file.path, reason, text, matching_lines, file.kind))

    candidates.sort(key=lambda item: (-item[0], _kind_order(item[5]), item[1]))
    excerpts: list[EvidenceExcerpt] = []
    used_chars = 0
    truncated = False
    for score, path, reason, text, matching_lines, kind in candidates[:max_files]:
        excerpt = _excerpt(path, kind, score, reason, text, matching_lines, max_excerpt_lines)
        cost = len(excerpt.content) + 120
        if used_chars + cost > max_total_chars:
            truncated = True
            break
        excerpts.append(excerpt)
        used_chars += cost
    return RetrievalPack(
        repository_map=repo_map,
        issue_terms=issue_terms,
        excerpts=tuple(excerpts),
        truncated=truncated,
    )


def evaluate_relevant_file_recall(
    pack: RetrievalPack,
    expected_paths: tuple[str, ...] | list[str],
) -> RetrievalRecall:
    expected = tuple(sorted(_safe_relative(path).as_posix() for path in expected_paths))
    selected = tuple(sorted(set(pack.selected_paths)))
    recalled = tuple(path for path in expected if path in selected)
    return RetrievalRecall(expected, selected, recalled)


def _rank_file(
    file: RepositoryFile,
    text: str,
    issue_terms: tuple[str, ...],
) -> tuple[int, str, tuple[int, ...]]:
    path_terms = set(_tokens(file.path))
    symbol_terms = set(_tokens(" ".join(file.symbols)))
    matching_lines: list[int] = []
    content_score = 0
    lowered_terms = set(issue_terms)
    for line_number, line in enumerate(text.splitlines(), start=1):
        line_terms = set(_tokens(line))
        overlap = lowered_terms & line_terms
        if not overlap:
            continue
        matching_lines.append(line_number)
        content_score += min(6, len(overlap) * 2)

    path_hits = len(lowered_terms & path_terms)
    symbol_hits = len(lowered_terms & symbol_terms)
    score = content_score + path_hits * 5 + symbol_hits * 8
    if file.kind == "source":
        score += 6
    elif file.kind == "test":
        score += 4
    reasons = []
    if path_hits:
        reasons.append("path")
    if symbol_hits:
        reasons.append("symbol")
    if matching_lines:
        reasons.append("content")
    if file.kind in {"source", "test"}:
        reasons.append(file.kind)
    return score, "+".join(reasons) if reasons else "fallback", tuple(matching_lines)


def _fallback_rank(file: RepositoryFile, text: str) -> tuple[int, str, tuple[int, ...]]:
    if file.kind == "source":
        lines = _symbol_lines(text)
        return 6, "source-fallback", lines or (1,)
    if file.kind == "test":
        lines = _symbol_lines(text)
        return 4, "test-fallback", lines or (1,)
    return 1, "map-fallback", (1,)


def _excerpt(
    path: str,
    kind: str,
    score: int,
    reason: str,
    text: str,
    matching_lines: tuple[int, ...],
    max_excerpt_lines: int,
) -> EvidenceExcerpt:
    lines = text.splitlines()
    if not lines:
        return EvidenceExcerpt(path, kind, score, reason, 1, 1, "")
    anchors = matching_lines or (1,)
    selected: set[int] = set()
    for anchor in anchors[:6]:
        start = max(1, anchor - 2)
        end = min(len(lines), anchor + 2)
        selected.update(range(start, end + 1))
        if len(selected) >= max_excerpt_lines:
            break
    ordered = tuple(sorted(selected)[:max_excerpt_lines])
    rendered = []
    for line_number in ordered:
        line = lines[line_number - 1].expandtabs(4)
        if len(line) > MAX_LINE_CHARS:
            line = line[:MAX_LINE_CHARS] + "..."
        rendered.append(f"{line_number:>6} | {line}")
    return EvidenceExcerpt(
        path=path,
        kind=kind,
        score=score,
        reason=reason,
        start_line=ordered[0],
        end_line=ordered[-1],
        content="\n".join(rendered),
    )


def _tokens(value: str) -> tuple[str, ...]:
    found = []
    for raw in _TOKEN.findall(value.replace("-", "_")):
        token = raw.lower()
        parts = [part for part in token.split("_") if part]
        for part in parts or [token]:
            if len(part) >= 2 and part not in _STOPWORDS:
                found.append(part)
    return tuple(sorted(set(found)))


def _symbols(text: str) -> tuple[str, ...]:
    symbols = []
    for line in text.splitlines():
        match = _PY_SYMBOL.match(line)
        if match is not None:
            symbols.append(match.group(1))
    return tuple(sorted(set(symbols)))


def _symbol_lines(text: str) -> tuple[int, ...]:
    lines = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if _PY_SYMBOL.match(line) is not None:
            lines.append(line_number)
    return tuple(lines)


def _file_kind(path: PurePosixPath) -> str:
    parts = path.parts
    name = path.name.lower()
    if name == "issue.md":
        return "issue"
    if "tests" in parts or name.startswith("test_") or name.endswith("_test.py"):
        return "test"
    if parts and parts[0] == "src":
        return "source"
    return "other"


def _language(path: PurePosixPath) -> str:
    suffix = path.suffix.lower()
    if suffix == ".py":
        return "python"
    if suffix in {".md", ".markdown"}:
        return "markdown"
    if suffix in {".js", ".mjs", ".cjs"}:
        return "javascript"
    if suffix in {".ts", ".tsx"}:
        return "typescript"
    if suffix == ".json":
        return "json"
    return suffix.removeprefix(".") or "text"


def _kind_order(kind: str) -> int:
    return {"source": 0, "test": 1, "other": 2, "issue": 3}.get(kind, 4)


def _safe_relative(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or not path.as_posix():
        raise RetrievalError("expected paths must be repository-relative")
    return path


def _bounded_integer(value: object, field: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise RetrievalError(f"{field} must be between {minimum} and {maximum}")
    return value
