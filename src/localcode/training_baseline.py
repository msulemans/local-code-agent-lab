"""Pinned executable development baseline for the Phase 4 repair model."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import tempfile
from typing import Any

from .test_runner import TestRunner
from .tools import ToolError, git_diff
from .workspace import create_workspace, write_file


_SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9-]{2,79}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CASE_FIELDS = {
    "case_id",
    "fixture",
    "issue_path",
    "issue_sha256",
    "source_path",
    "source_sha256",
    "test_path",
    "test_sha256",
    "test_command",
}

SYSTEM_PROMPT = """You repair one Python file from a behavior report.
Return exactly one complete corrected file between the literal tags
<corrected_file> and </corrected_file>. Do not return Markdown, explanations,
tests, patches, or any text outside those tags. Preserve behavior not mentioned
by the report."""


class ExecutableBaselineError(ValueError):
    """A frozen-suite, prediction, or evaluation contract error."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class ExecutableCase:
    case_id: str
    fixture: Path
    issue_path: str
    source_path: str
    test_path: str
    test_command: str
    issue_sha256: str
    source_sha256: str
    test_sha256: str

    @property
    def issue(self) -> str:
        return (self.fixture / self.issue_path).read_text(encoding="utf-8")

    @property
    def broken_source(self) -> str:
        return (self.fixture / self.source_path).read_text(encoding="utf-8")


@dataclass(frozen=True, slots=True)
class ExecutableSuite:
    suite_id: str
    purpose: str
    model_config: str
    temperature: int
    max_output_tokens: int
    max_prediction_bytes: int
    cases: tuple[ExecutableCase, ...]
    sealed_split_policy: str


@dataclass(frozen=True, slots=True)
class ExecutableCaseResult:
    case_id: str
    status: str
    solved: bool
    output_format_valid: bool
    test_exit_code: int | None
    test_output: str
    prediction_sha256: str | None
    changed: bool
    diff: str
    source_unchanged: bool
    error_code: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "status": self.status,
            "solved": self.solved,
            "output_format_valid": self.output_format_valid,
            "test_exit_code": self.test_exit_code,
            "test_output": self.test_output,
            "prediction_sha256": self.prediction_sha256,
            "changed": self.changed,
            "diff": self.diff,
            "source_unchanged": self.source_unchanged,
            "error_code": self.error_code,
        }


def load_executable_suite(path: str | Path, project_root: str | Path) -> ExecutableSuite:
    manifest = Path(path)
    root = Path(project_root).resolve(strict=True)
    try:
        document = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ExecutableBaselineError("manifest_read", f"cannot load executable suite: {manifest}") from exc
    expected = {
        "schema_version",
        "suite_id",
        "purpose",
        "model_config",
        "generation",
        "cases",
        "sealed_split_policy",
    }
    if not isinstance(document, dict) or set(document) != expected or document["schema_version"] != 1:
        raise ExecutableBaselineError("manifest_shape", "executable suite must match schema v1")
    suite_id = document["suite_id"]
    if not isinstance(suite_id, str) or _SAFE_ID.fullmatch(suite_id) is None:
        raise ExecutableBaselineError("suite_id", "suite ID must be lowercase safe text")
    if document["purpose"] != "development_only_untouched_base_baseline":
        raise ExecutableBaselineError("purpose", "suite is not registered for the untouched development baseline")
    model_config = _safe_relative(document["model_config"], "model_config")
    if not (root / model_config).is_file():
        raise ExecutableBaselineError("model_config", "registered model config does not exist")
    generation = document["generation"]
    if not isinstance(generation, dict) or set(generation) != {
        "temperature", "max_output_tokens", "max_prediction_bytes"
    }:
        raise ExecutableBaselineError("generation", "generation fields are invalid")
    if generation["temperature"] != 0:
        raise ExecutableBaselineError("generation", "baseline temperature must be zero")
    max_tokens = _bounded_int(generation["max_output_tokens"], 1, 2048, "max_output_tokens")
    max_bytes = _bounded_int(generation["max_prediction_bytes"], 1, 1_048_576, "max_prediction_bytes")
    raw_cases = document["cases"]
    if not isinstance(raw_cases, list) or not 4 <= len(raw_cases) <= 12:
        raise ExecutableBaselineError("cases", "development suite must contain 4-12 cases")
    cases = tuple(_load_case(raw, root) for raw in raw_cases)
    if len({case.case_id for case in cases}) != len(cases):
        raise ExecutableBaselineError("cases", "case IDs must be unique")
    sealed_policy = document["sealed_split_policy"]
    if not isinstance(sealed_policy, str) or "must not load" not in sealed_policy:
        raise ExecutableBaselineError("sealed_policy", "sealed split prohibition must be explicit")
    return ExecutableSuite(
        suite_id=suite_id,
        purpose=document["purpose"],
        model_config=model_config,
        temperature=0,
        max_output_tokens=max_tokens,
        max_prediction_bytes=max_bytes,
        cases=cases,
        sealed_split_policy=sealed_policy,
    )


def build_case_messages(case: ExecutableCase) -> tuple[dict[str, str], ...]:
    """Build model messages without reading tests or expected corrected code."""
    return (
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Behavior report:\n{case.issue.rstrip()}\n\n"
                f"File path: {case.source_path}\n"
                f"Broken file:\n{case.broken_source}"
            ),
        },
    )


def extract_corrected_file(response: str, *, max_bytes: int) -> str:
    if not isinstance(response, str) or "\x00" in response:
        raise ExecutableBaselineError("invalid_prediction", "prediction must be NUL-free text")
    match = re.fullmatch(r"\s*<corrected_file>\n?(.*?)</corrected_file>\s*", response, re.DOTALL)
    if match is None:
        raise ExecutableBaselineError("invalid_format", "prediction must contain exactly one corrected_file envelope")
    content = match.group(1)
    if not content:
        raise ExecutableBaselineError("empty_prediction", "corrected file must not be empty")
    if len(content.encode("utf-8")) > max_bytes:
        raise ExecutableBaselineError("prediction_too_large", "corrected file exceeds the configured byte limit")
    return content if content.endswith("\n") else content + "\n"


def evaluate_prediction(
    case: ExecutableCase,
    response: str,
    *,
    max_prediction_bytes: int,
    test_runner: TestRunner | None = None,
) -> ExecutableCaseResult:
    """Apply one untrusted prediction in a disposable workspace and test it."""
    source_before = _sha256_path(case.fixture / case.source_path)
    try:
        corrected = extract_corrected_file(response, max_bytes=max_prediction_bytes)
    except ExecutableBaselineError as exc:
        return ExecutableCaseResult(
            case_id=case.case_id,
            status="invalid_prediction",
            solved=False,
            output_format_valid=False,
            test_exit_code=None,
            test_output="",
            prediction_sha256=None,
            changed=False,
            diff="",
            source_unchanged=source_before == _sha256_path(case.fixture / case.source_path),
            error_code=exc.code,
        )
    prediction_sha = hashlib.sha256(corrected.encode("utf-8")).hexdigest()
    runner = TestRunner() if test_runner is None else test_runner
    try:
        with tempfile.TemporaryDirectory(prefix=f"localcode-m015-{case.case_id}-") as temporary:
            workspace = create_workspace(case.fixture, Path(temporary) / "workspace")
            write_file(workspace.root, case.source_path, corrected, max_bytes=max_prediction_bytes)
            diff_result = git_diff(workspace.root)
            test_result = runner.run(workspace, case.test_command)
            metadata = test_result.metadata_dict()
            test_exit_code = int(metadata["exit_code"])
            changed = bool(diff_result.content.strip())
            solved = test_exit_code == 0 and changed
            return ExecutableCaseResult(
                case_id=case.case_id,
                status="solved" if solved else "tests_failed",
                solved=solved,
                output_format_valid=True,
                test_exit_code=test_exit_code,
                test_output=test_result.content,
                prediction_sha256=prediction_sha,
                changed=changed,
                diff=diff_result.content,
                source_unchanged=source_before == _sha256_path(case.fixture / case.source_path),
            )
    except ToolError as exc:
        return ExecutableCaseResult(
            case_id=case.case_id,
            status="evaluation_error",
            solved=False,
            output_format_valid=True,
            test_exit_code=None,
            test_output=str(exc),
            prediction_sha256=prediction_sha,
            changed=False,
            diff="",
            source_unchanged=source_before == _sha256_path(case.fixture / case.source_path),
            error_code=exc.code,
        )


def _load_case(raw: object, root: Path) -> ExecutableCase:
    if not isinstance(raw, dict) or set(raw) != _CASE_FIELDS:
        raise ExecutableBaselineError("case_shape", "case fields do not match schema v1")
    case_id = raw["case_id"]
    if not isinstance(case_id, str) or _SAFE_ID.fullmatch(case_id) is None:
        raise ExecutableBaselineError("case_id", "case ID must be lowercase safe text")
    fixture_relative = _safe_relative(raw["fixture"], "fixture")
    fixture = (root / fixture_relative).resolve(strict=True)
    try:
        fixture.relative_to(root)
    except ValueError as exc:
        raise ExecutableBaselineError("fixture", "fixture must stay inside the project") from exc
    values: dict[str, str] = {}
    for kind in ("issue", "source", "test"):
        relative = _safe_relative(raw[f"{kind}_path"], f"{kind}_path")
        digest = raw[f"{kind}_sha256"]
        if not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
            raise ExecutableBaselineError("case_hash", f"{kind} SHA-256 is invalid")
        candidate = fixture / relative
        if not candidate.is_file() or _sha256_path(candidate) != digest:
            raise ExecutableBaselineError("case_hash", f"{case_id} {kind} file does not match its pin")
        values[f"{kind}_path"] = relative
        values[f"{kind}_sha256"] = digest
    if raw["test_command"] != "python-unittest":
        raise ExecutableBaselineError("test_command", "only the registered python-unittest command is allowed")
    return ExecutableCase(case_id=case_id, fixture=fixture, test_command=raw["test_command"], **values)


def _safe_relative(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ExecutableBaselineError(field, f"{field} must be a repository-relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ExecutableBaselineError(field, f"{field} must stay relative without dot segments")
    return path.as_posix()


def _bounded_int(value: object, minimum: int, maximum: int, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ExecutableBaselineError(field, f"{field} must be an integer in {minimum}..{maximum}")
    return value


def _sha256_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
