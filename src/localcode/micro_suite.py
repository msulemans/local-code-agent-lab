"""Registered deterministic micro-repository suite for the guarded agent loop."""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import tempfile
import time
from typing import Any, Callable

from .controller import ModelBackendError
from .context import RetrievalContextCompiler, SimpleContextCompiler, compile_single_shot_context
from .decisions import DecisionValidator, FinalDecision
from .engineering_registry import EngineeringToolRegistry
from .loop import AgentLoop, CompletionRequirements, LoopBudgets, LoopRequest, TerminationReason
from .patches import apply_patch
from .review import DeterministicReviewer, ReviewBackend, ReviewDisposition, ReviewRequest
from .test_runner import TestRunner
from .tools import ToolError, git_diff
from .tools.base import RepositoryPolicy
from .workspace import create_workspace


_SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9-]{2,79}$")
_DIFF_PATH = re.compile(r"^diff --git a/(.+) b/(.+)$", re.MULTILINE)
_CONTEXT_MODES = frozenset({"simple", "retrieval", "single_shot"})
_REVIEWED_CONTEXT_MODE = "reviewed"


class MicroSuiteError(ValueError):
    """A deterministic manifest or suite-registration error."""


@dataclass(frozen=True, slots=True)
class MicroCase:
    case_id: str
    category: str
    fixture: Path
    issue_file: str
    expected_changed_paths: tuple[str, ...]
    responses: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MicroSuite:
    suite_id: str
    minimum_cases: int
    maximum_cases: int
    minimum_solved: int
    cases: tuple[MicroCase, ...]


@dataclass(frozen=True, slots=True)
class MicroCaseRun:
    case_id: str
    category: str
    context_mode: str
    success: bool
    termination_reason: TerminationReason
    final_answer: str | None
    changed_paths: tuple[str, ...]
    test_exit_codes: tuple[int, ...]
    observation_error_codes: tuple[str, ...]
    source_unchanged: bool
    first_context_chars: int
    first_selected_paths: tuple[str, ...]
    diff: str
    review_disposition: str | None = None
    review_findings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MicroSuiteRun:
    suite_id: str
    context_mode: str
    cases: tuple[MicroCaseRun, ...]
    minimum_cases: int
    maximum_cases: int
    minimum_solved: int

    @property
    def registered(self) -> int:
        return len(self.cases)

    @property
    def solved(self) -> int:
        return sum(case.success for case in self.cases)

    @property
    def milestone_ready(self) -> bool:
        return (
            self.minimum_cases <= self.registered <= self.maximum_cases
            and self.solved >= self.minimum_solved
        )


class ScriptedMicroBackend:
    """Supply a frozen sequence of model-shaped decisions for runtime testing."""

    def __init__(self, responses: tuple[str, ...]) -> None:
        self._responses = iter(responses)
        self.requests: list[LoopRequest] = []

    def complete(self, request: LoopRequest) -> str:
        self.requests.append(request)
        try:
            return next(self._responses)
        except StopIteration as exc:
            raise ModelBackendError("scripted micro-case plan was exhausted") from exc


MicroCaseRunner = Callable[..., MicroCaseRun]


def load_micro_suite(
    manifest_path: str | Path,
    tool_schemas_path: str | Path,
    repository_root: str | Path,
) -> MicroSuite:
    """Load and validate the complete registered suite before any case executes."""

    manifest_file = Path(manifest_path)
    try:
        document = json.loads(manifest_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MicroSuiteError(f"cannot load micro-suite manifest: {manifest_file}") from exc
    if not isinstance(document, dict) or set(document) != {
        "schema_version",
        "suite_id",
        "milestone_gate",
        "cases",
    }:
        raise MicroSuiteError("micro-suite manifest has unexpected top-level fields")
    if document["schema_version"] != 1:
        raise MicroSuiteError("micro-suite schema_version must equal 1")
    suite_id = document["suite_id"]
    if not isinstance(suite_id, str) or _SAFE_ID.fullmatch(suite_id) is None:
        raise MicroSuiteError("micro-suite ID is invalid")

    gate = document["milestone_gate"]
    if not isinstance(gate, dict) or set(gate) != {
        "minimum_cases",
        "maximum_cases",
        "minimum_solved",
    }:
        raise MicroSuiteError("milestone_gate fields are invalid")
    minimum_cases = _positive_integer(gate["minimum_cases"], "minimum_cases")
    maximum_cases = _positive_integer(gate["maximum_cases"], "maximum_cases")
    minimum_solved = _positive_integer(gate["minimum_solved"], "minimum_solved")
    if not minimum_cases <= maximum_cases or minimum_solved > maximum_cases:
        raise MicroSuiteError("milestone gate bounds are inconsistent")

    raw_cases = document["cases"]
    if not isinstance(raw_cases, list) or not raw_cases or len(raw_cases) > maximum_cases:
        raise MicroSuiteError("micro-suite cases must be a non-empty bounded list")
    validator = DecisionValidator.from_path(tool_schemas_path)
    root = Path(repository_root).resolve(strict=True)
    cases: list[MicroCase] = []
    seen_ids: set[str] = set()
    for raw_case in raw_cases:
        case = _load_case(raw_case, root, validator)
        if case.case_id in seen_ids:
            raise MicroSuiteError(f"duplicate micro-case ID: {case.case_id}")
        seen_ids.add(case.case_id)
        cases.append(case)
    return MicroSuite(
        suite_id=suite_id,
        minimum_cases=minimum_cases,
        maximum_cases=maximum_cases,
        minimum_solved=minimum_solved,
        cases=tuple(cases),
    )


def run_micro_case(
    case: MicroCase,
    test_runner: TestRunner | None = None,
    *,
    context_mode: str = "simple",
) -> MicroCaseRun:
    """Run one scripted plan through the real guarded engineering runtime."""

    context_mode = _validate_context_mode(context_mode)
    if context_mode == "single_shot":
        return _run_single_shot_case(case, test_runner)
    source_before = _fixture_fingerprint(case.fixture)
    tool_count = sum(
        json.loads(response)["decision"]["kind"] == "tool"
        for response in case.responses
    )
    with tempfile.TemporaryDirectory(prefix=f"localcode-{case.case_id}-") as temporary:
        workspace = create_workspace(case.fixture, Path(temporary) / "workspace")
        backend = ScriptedMicroBackend(case.responses)
        result = AgentLoop(
            backend,
            DecisionValidator.from_path(
                Path(__file__).resolve().parents[2] / "benchmarks/micro_agent/tool_schemas.json"
            ),
            EngineeringToolRegistry(workspace, test_runner),
            LoopBudgets(
                max_turns=len(case.responses),
                max_tool_calls=tool_count,
                max_invalid_actions=2,
                max_wall_seconds=120,
            ),
            clock=lambda: "2026-08-12T12:00:00+10:00",
            monotonic=time.monotonic,
            completion_requirements=CompletionRequirements(
                require_patch=True,
                require_passing_tests=True,
            ),
            context_compiler=_context_compiler_for_mode(context_mode, workspace),
        ).run(
            run_id=f"micro-{case.case_id}",
            issue=(case.fixture / case.issue_file).read_text(encoding="utf-8"),
        )
        first_context_chars, first_selected_paths = _first_context_evidence(backend.requests)

        test_exit_codes = tuple(
            metadata["exit_code"]
            for observation in result.observations
            if "exit_code" in (metadata := observation.metadata_dict())
        )
        error_codes = tuple(
            str(metadata["code"])
            for observation in result.observations
            if "code" in (metadata := observation.metadata_dict())
        )
        diff = ""
        for observation in result.observations:
            if observation.content.startswith("diff --git "):
                diff = observation.content
        changed_paths = _changed_paths(diff)

    source_unchanged = source_before == _fixture_fingerprint(case.fixture)
    success = (
        result.termination_reason is TerminationReason.FINAL_ANSWER
        and result.final_answer is not None
        and bool(test_exit_codes)
        and test_exit_codes[-1] == 0
        and changed_paths == case.expected_changed_paths
        and source_unchanged
    )
    return MicroCaseRun(
        case_id=case.case_id,
        category=case.category,
        context_mode=context_mode,
        success=success,
        termination_reason=result.termination_reason,
        final_answer=result.final_answer,
        changed_paths=changed_paths,
        test_exit_codes=test_exit_codes,
        observation_error_codes=error_codes,
        source_unchanged=source_unchanged,
        first_context_chars=first_context_chars,
        first_selected_paths=first_selected_paths,
        diff=diff,
    )


def run_micro_suite(suite: MicroSuite, *, context_mode: str = "simple") -> MicroSuiteRun:
    context_mode = _validate_context_mode(context_mode)
    return MicroSuiteRun(
        suite_id=suite.suite_id,
        context_mode=context_mode,
        cases=tuple(run_micro_case(case, context_mode=context_mode) for case in suite.cases),
        minimum_cases=suite.minimum_cases,
        maximum_cases=suite.maximum_cases,
        minimum_solved=suite.minimum_solved,
    )


def run_reviewed_micro_case(
    case: MicroCase,
    *,
    reviewer: ReviewBackend | None = None,
    test_runner: TestRunner | None = None,
    case_runner: MicroCaseRunner | None = None,
) -> MicroCaseRun:
    runner = run_micro_case if case_runner is None else case_runner
    base = runner(case, test_runner=test_runner, context_mode="retrieval")
    decision = (DeterministicReviewer() if reviewer is None else reviewer).review(
        ReviewRequest(
            issue=(case.fixture / case.issue_file).read_text(encoding="utf-8"),
            category=case.category,
            diff=base.diff,
            final_answer=base.final_answer,
            test_exit_codes=base.test_exit_codes,
            observation_error_codes=base.observation_error_codes,
            changed_paths=base.changed_paths,
            selected_paths=base.first_selected_paths,
        )
    )
    if decision.disposition is ReviewDisposition.ACCEPT:
        return replace(
            base,
            context_mode=_REVIEWED_CONTEXT_MODE,
            review_disposition=decision.disposition.value,
            review_findings=decision.findings,
        )
    return replace(
        base,
        context_mode=_REVIEWED_CONTEXT_MODE,
        success=False,
        final_answer=None,
        observation_error_codes=base.observation_error_codes + (f"review_{decision.disposition.value}",),
        review_disposition=decision.disposition.value,
        review_findings=decision.findings,
    )


def run_reviewed_micro_suite(
    suite: MicroSuite,
    *,
    reviewer: ReviewBackend | None = None,
    test_runner: TestRunner | None = None,
    case_runner: MicroCaseRunner | None = None,
) -> MicroSuiteRun:
    return MicroSuiteRun(
        suite_id=suite.suite_id,
        context_mode=_REVIEWED_CONTEXT_MODE,
        cases=tuple(
            run_reviewed_micro_case(
                case,
                reviewer=reviewer,
                test_runner=test_runner,
                case_runner=case_runner,
            )
            for case in suite.cases
        ),
        minimum_cases=suite.minimum_cases,
        maximum_cases=suite.maximum_cases,
        minimum_solved=suite.minimum_solved,
    )


def _load_case(raw_case: Any, root: Path, validator: DecisionValidator) -> MicroCase:
    expected_fields = {
        "id",
        "category",
        "fixture",
        "issue_file",
        "expected_changed_paths",
        "plan",
    }
    if not isinstance(raw_case, dict) or set(raw_case) != expected_fields:
        raise MicroSuiteError("micro-case fields are invalid")
    case_id = raw_case["id"]
    if not isinstance(case_id, str) or _SAFE_ID.fullmatch(case_id) is None:
        raise MicroSuiteError("micro-case ID is invalid")
    category = raw_case["category"]
    if not isinstance(category, str) or not category or len(category) > 80:
        raise MicroSuiteError(f"micro-case category is invalid: {case_id}")

    fixture_relative = _safe_relative(raw_case["fixture"], "fixture")
    fixture = (root / Path(fixture_relative.as_posix())).resolve(strict=True)
    try:
        fixture.relative_to(root)
    except ValueError as exc:
        raise MicroSuiteError(f"fixture escapes repository root: {case_id}") from exc
    if not fixture.is_dir():
        raise MicroSuiteError(f"fixture is not a directory: {case_id}")
    issue_relative = _safe_relative(raw_case["issue_file"], "issue_file")
    issue_path = fixture / Path(issue_relative.as_posix())
    if not issue_path.is_file():
        raise MicroSuiteError(f"issue file is missing: {case_id}")

    raw_paths = raw_case["expected_changed_paths"]
    if not isinstance(raw_paths, list) or not raw_paths:
        raise MicroSuiteError(f"expected_changed_paths is invalid: {case_id}")
    expected_paths = tuple(sorted(_safe_relative(value, "changed path").as_posix() for value in raw_paths))
    if len(set(expected_paths)) != len(expected_paths):
        raise MicroSuiteError(f"expected changed paths contain duplicates: {case_id}")

    raw_plan = raw_case["plan"]
    if not isinstance(raw_plan, list) or not 2 <= len(raw_plan) <= 20:
        raise MicroSuiteError(f"micro-case plan is invalid: {case_id}")
    responses: list[str] = []
    decisions = []
    for step in raw_plan:
        if not isinstance(step, dict) or set(step) != {"thought_summary", "decision"}:
            raise MicroSuiteError(f"micro-case plan step is invalid: {case_id}")
        response = json.dumps(
            {
                "protocol_version": "1",
                "thought_summary": step["thought_summary"],
                "decision": step["decision"],
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        try:
            decisions.append(validator.validate(response))
        except Exception as exc:
            raise MicroSuiteError(f"micro-case decision is invalid: {case_id}") from exc
        responses.append(response)
    if not isinstance(decisions[-1], FinalDecision) or any(
        isinstance(decision, FinalDecision) for decision in decisions[:-1]
    ):
        raise MicroSuiteError(f"micro-case must end with exactly one final decision: {case_id}")
    tools = tuple(decision.tool for decision in decisions if not isinstance(decision, FinalDecision))
    for required in ("apply_patch", "run_tests", "git_diff"):
        if required not in tools:
            raise MicroSuiteError(f"micro-case lacks required tool {required}: {case_id}")
    if not any(tool in tools for tool in ("list_files", "search_code", "read_file")):
        raise MicroSuiteError(f"micro-case lacks repository inspection: {case_id}")
    return MicroCase(
        case_id=case_id,
        category=category,
        fixture=fixture,
        issue_file=issue_relative.as_posix(),
        expected_changed_paths=expected_paths,
        responses=tuple(responses),
    )


def _validate_context_mode(context_mode: str) -> str:
    if not isinstance(context_mode, str) or context_mode not in _CONTEXT_MODES:
        raise ValueError("context_mode must be 'simple', 'retrieval', or 'single_shot'")
    return context_mode


def _context_compiler_for_mode(context_mode: str, workspace: Any) -> SimpleContextCompiler | RetrievalContextCompiler:
    if context_mode == "simple":
        return SimpleContextCompiler()
    return RetrievalContextCompiler(workspace.root, max_files=3)


def _run_single_shot_case(
    case: MicroCase,
    test_runner: TestRunner | None,
) -> MicroCaseRun:
    source_before = _fixture_fingerprint(case.fixture)
    patch, answer = _single_shot_patch_and_answer(case)
    runner = TestRunner() if test_runner is None else test_runner
    with tempfile.TemporaryDirectory(prefix=f"localcode-{case.case_id}-single-shot-") as temporary:
        workspace = create_workspace(case.fixture, Path(temporary) / "workspace")
        issue = (case.fixture / case.issue_file).read_text(encoding="utf-8")
        context = compile_single_shot_context(issue, workspace.root, 12_000)
        first_context_chars = len(context)
        test_exit_codes: tuple[int, ...] = ()
        error_codes: tuple[str, ...] = ()
        final_answer = answer
        diff = ""
        changed_paths: tuple[str, ...] = ()
        termination_reason = TerminationReason.TURN_EXHAUSTION
        try:
            apply_patch(workspace.root, patch)
            diff = git_diff(workspace.root).content
            changed_paths = _changed_paths(diff)
            test_result = runner.run(workspace, "python-unittest")
            metadata = test_result.metadata_dict()
            test_exit_codes = (int(metadata["exit_code"]),)
            if test_exit_codes[-1] == 0:
                termination_reason = TerminationReason.FINAL_ANSWER
        except ToolError as exc:
            error_codes = (exc.code,)
            diff = git_diff(workspace.root).content
            changed_paths = _changed_paths(diff)

    source_unchanged = source_before == _fixture_fingerprint(case.fixture)
    success = (
        termination_reason is TerminationReason.FINAL_ANSWER
        and bool(test_exit_codes)
        and test_exit_codes[-1] == 0
        and changed_paths == case.expected_changed_paths
        and source_unchanged
    )
    return MicroCaseRun(
        case_id=case.case_id,
        category=case.category,
        context_mode="single_shot",
        success=success,
        termination_reason=termination_reason,
        final_answer=final_answer,
        changed_paths=changed_paths,
        test_exit_codes=test_exit_codes,
        observation_error_codes=error_codes,
        source_unchanged=source_unchanged,
        first_context_chars=first_context_chars,
        first_selected_paths=(),
        diff=diff,
    )


def _single_shot_patch_and_answer(case: MicroCase) -> tuple[str, str]:
    patch: str | None = None
    answer: str | None = None
    for response in case.responses:
        decision = json.loads(response)["decision"]
        if patch is None and decision.get("kind") == "tool" and decision.get("tool") == "apply_patch":
            arguments = decision.get("arguments", {})
            if isinstance(arguments, dict) and isinstance(arguments.get("patch"), str):
                patch = arguments["patch"]
        if decision.get("kind") == "final" and isinstance(decision.get("answer"), str):
            answer = decision["answer"]
    if patch is None or answer is None:
        raise MicroSuiteError(f"single-shot baseline could not be derived: {case.case_id}")
    return patch, answer


def _first_context_evidence(requests: list[LoopRequest]) -> tuple[int, tuple[str, ...]]:
    if not requests:
        return 0, ()
    context = requests[0].context
    try:
        payload = json.loads(context)
    except json.JSONDecodeError:
        return len(context), ()
    selected_paths = payload.get("retrieved_evidence", {}).get("selected_paths", ())
    if not isinstance(selected_paths, list) or not all(isinstance(path, str) for path in selected_paths):
        return len(context), ()
    return len(context), tuple(selected_paths)


def _safe_relative(value: Any, label: str) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise MicroSuiteError(f"{label} must be non-empty text")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or path.as_posix() in {".", ""}:
        raise MicroSuiteError(f"{label} must stay relative")
    return path


def _positive_integer(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise MicroSuiteError(f"{label} must be a positive integer")
    return value


def _fixture_fingerprint(root: Path) -> str:
    policy = RepositoryPolicy.from_root(root)
    digest = hashlib.sha256()
    for path in sorted(policy.root.rglob("*")):
        if path.is_symlink():
            raise MicroSuiteError(f"fixture fingerprint rejects symlink: {path}")
        if not path.is_file():
            continue
        relative = PurePosixPath(path.relative_to(policy.root).as_posix())
        if policy.exclusion_reason(relative) is not None:
            continue
        digest.update(relative.as_posix().encode("utf-8"))
        digest.update(b"\x00")
        digest.update(path.read_bytes())
        digest.update(b"\x00")
    return digest.hexdigest()


def _changed_paths(diff: str) -> tuple[str, ...]:
    paths = []
    for old, new in _DIFF_PATH.findall(diff):
        if old != new:
            return ()
        paths.append(old)
    return tuple(sorted(paths))
