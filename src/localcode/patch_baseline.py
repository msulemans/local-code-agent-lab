"""Executable issue-to-diff development gate for M016b."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
import tempfile
from pathlib import Path
from typing import Any

from .patches import apply_patch
from .test_runner import TestRunner
from .tools import ToolError, ToolResult, git_diff
from .training_baseline import ExecutableBaselineError, ExecutableCase
from .workspace import create_workspace


SYSTEM_PROMPT = (
    "You repair Python repositories. Return only one valid unified diff that "
    "fixes the issue, without Markdown fences or explanation."
)


@dataclass(frozen=True, slots=True)
class PatchCaseResult:
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


def observe_failing_tests(case: ExecutableCase, *, test_runner: TestRunner | None = None) -> ToolResult:
    """Run the registered test on an unchanged disposable fixture."""

    runner = TestRunner() if test_runner is None else test_runner
    with tempfile.TemporaryDirectory(prefix=f"localcode-m016b-observe-{case.case_id}-") as temporary:
        workspace = create_workspace(case.fixture, Path(temporary) / "workspace")
        result = runner.run(workspace, case.test_command)
    if int(result.metadata_dict()["exit_code"]) == 0:
        raise ExecutableBaselineError("fixture_not_broken", f"{case.case_id} tests unexpectedly pass")
    return result


def build_patch_messages(case: ExecutableCase, failure: ToolResult) -> tuple[dict[str, str], ...]:
    exit_code = int(failure.metadata_dict()["exit_code"])
    if exit_code == 0:
        raise ExecutableBaselineError("failure_evidence", "patch prompt requires a failing test")
    return (
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Issue:\n{case.issue.rstrip()}\n\n"
                f"Failing test output (exit {exit_code}):\n{failure.content.rstrip()}\n\n"
                f"Broken repository file:\nFile: {case.source_path}\n{case.broken_source}"
            ),
        },
    )


def extract_unified_diff(response: str, *, max_bytes: int) -> str:
    if not isinstance(response, str) or "\x00" in response:
        raise ExecutableBaselineError("invalid_prediction", "prediction must be NUL-free text")
    patch = response.strip()
    if not patch.startswith("diff --git ") or "```" in patch:
        raise ExecutableBaselineError("invalid_format", "prediction must contain only one unified diff")
    if len(re.findall(r"^diff --git ", patch, re.MULTILINE)) != 1:
        raise ExecutableBaselineError("invalid_format", "prediction must contain exactly one file diff")
    if len(patch.encode("utf-8")) > max_bytes:
        raise ExecutableBaselineError("prediction_too_large", "prediction exceeds the byte limit")
    return patch + "\n"


def evaluate_patch_prediction(
    case: ExecutableCase,
    response: str,
    *,
    max_prediction_bytes: int,
    test_runner: TestRunner | None = None,
) -> PatchCaseResult:
    """Apply one strict model diff, run tests, and leave the source fixture unchanged."""

    source_before = _sha(case.fixture / case.source_path)
    try:
        patch = extract_unified_diff(response, max_bytes=max_prediction_bytes)
    except ExecutableBaselineError as exc:
        return _result(case, source_before, status="invalid_prediction", error_code=exc.code)
    prediction_sha = hashlib.sha256(patch.encode("utf-8")).hexdigest()
    runner = TestRunner() if test_runner is None else test_runner
    try:
        with tempfile.TemporaryDirectory(prefix=f"localcode-m016b-{case.case_id}-") as temporary:
            workspace = create_workspace(case.fixture, Path(temporary) / "workspace")
            apply_patch(workspace.root, patch)
            diff = git_diff(workspace.root).content
            test = runner.run(workspace, case.test_command)
            exit_code = int(test.metadata_dict()["exit_code"])
            solved = exit_code == 0 and bool(diff.strip())
            return PatchCaseResult(
                case_id=case.case_id,
                status="solved" if solved else "tests_failed",
                solved=solved,
                output_format_valid=True,
                test_exit_code=exit_code,
                test_output=test.content,
                prediction_sha256=prediction_sha,
                changed=bool(diff.strip()),
                diff=diff,
                source_unchanged=source_before == _sha(case.fixture / case.source_path),
            )
    except ToolError as exc:
        return PatchCaseResult(
            case_id=case.case_id,
            status="patch_rejected" if exc.code != "test_failed" else "evaluation_error",
            solved=False,
            output_format_valid=True,
            test_exit_code=None,
            test_output=str(exc),
            prediction_sha256=prediction_sha,
            changed=False,
            diff="",
            source_unchanged=source_before == _sha(case.fixture / case.source_path),
            error_code=exc.code,
        )


def _result(
    case: ExecutableCase,
    source_before: str,
    *,
    status: str,
    error_code: str,
) -> PatchCaseResult:
    return PatchCaseResult(
        case_id=case.case_id,
        status=status,
        solved=False,
        output_format_valid=False,
        test_exit_code=None,
        test_output="",
        prediction_sha256=None,
        changed=False,
        diff="",
        source_unchanged=source_before == _sha(case.fixture / case.source_path),
        error_code=error_code,
    )


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
