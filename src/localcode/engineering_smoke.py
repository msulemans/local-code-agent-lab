"""Resource-gated real-model smoke for one bounded repository repair."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import tempfile
import time
from typing import Callable

from .backends.ollama_loop import OllamaLoopBackend
from .compatibility import OllamaClient
from .context import RetrievalContextCompiler, SimpleContextCompiler
from .controller import ModelBackendError
from .decisions import DecisionValidator
from .engineering_registry import EngineeringToolRegistry
from .loop import (
    AgentLoop,
    CompletionRequirements,
    LoopBackend,
    LoopBudgets,
    LoopRequest,
    LoopResult,
    TerminationReason,
)
from .preflight import (
    SmokeBaseline,
    SmokePreflightError,
    parse_host_resource_snapshot,
    validate_smoke_baseline,
)
from .smoke import CommandRunner, _run_host_command
from .tools import git_diff
from .tools.base import RepositoryPolicy
from .workspace import Workspace, create_workspace


MAX_SWAP_GROWTH_BYTES = 2 * 1_024 * 1_024 * 1_024
MINIMUM_MEMORY_FREE_PERCENT = 5
_DIFF_PATH = re.compile(r"^diff --git a/(.+) b/(.+)$", re.MULTILINE)
_CONTEXT_MODES = frozenset({"simple", "retrieval"})

BaselineObserver = Callable[[SmokeBaseline], None]
ResourceObserver = Callable[["ResourceSnapshot"], None]
RegistryFactory = Callable[[Workspace], EngineeringToolRegistry]


@dataclass(frozen=True, slots=True)
class ResourceSnapshot:
    """Resource evidence captured immediately before or after one model turn."""

    turn_index: int
    phase: str
    swap_used_bytes: int
    memory_free_percent: int

    def __post_init__(self) -> None:
        if self.phase not in {"before_inference", "after_inference"}:
            raise ValueError("resource phase must be before_inference or after_inference")


@dataclass(frozen=True, slots=True)
class EngineeringSmokeRun:
    """Portable evidence from a disposable one-issue repair attempt."""

    context_mode: str
    baseline: SmokeBaseline
    result: LoopResult
    resource_snapshots: tuple[ResourceSnapshot, ...]
    first_context_chars: int
    first_selected_paths: tuple[str, ...]
    diff: str
    diff_truncated: bool
    changed_paths: tuple[str, ...]
    expected_changed_paths: tuple[str, ...]
    test_exit_codes: tuple[int, ...]
    source_unchanged: bool
    solved: bool


class ResourceGuardedLoopBackend:
    """Refuse inference or tool execution once frozen host limits are crossed."""

    def __init__(
        self,
        backend: LoopBackend,
        *,
        baseline: SmokeBaseline,
        command_runner: CommandRunner,
        observer: ResourceObserver,
        max_swap_growth_bytes: int = MAX_SWAP_GROWTH_BYTES,
        minimum_memory_free_percent: int = MINIMUM_MEMORY_FREE_PERCENT,
    ) -> None:
        if (
            isinstance(max_swap_growth_bytes, bool)
            or not isinstance(max_swap_growth_bytes, int)
            or max_swap_growth_bytes < 0
        ):
            raise ValueError("max_swap_growth_bytes must be a non-negative integer")
        if (
            isinstance(minimum_memory_free_percent, bool)
            or not isinstance(minimum_memory_free_percent, int)
            or not 0 <= minimum_memory_free_percent <= 100
        ):
            raise ValueError("minimum_memory_free_percent must be between 0 and 100")
        self._backend = backend
        self._baseline = baseline
        self._command_runner = command_runner
        self._observer = observer
        self._max_swap_growth_bytes = max_swap_growth_bytes
        self._minimum_memory_free_percent = minimum_memory_free_percent

    def complete(self, request: LoopRequest) -> str:
        before = self._capture(request.turn_index, "before_inference")
        self._enforce(before)
        try:
            response = self._backend.complete(request)
        except ModelBackendError:
            after = self._capture(request.turn_index, "after_inference")
            self._enforce(after)
            raise
        after = self._capture(request.turn_index, "after_inference")
        self._enforce(after)
        return response

    def _capture(self, turn_index: int, phase: str) -> ResourceSnapshot:
        try:
            parsed = parse_host_resource_snapshot(
                swapusage_output=self._command_runner(("sysctl", "vm.swapusage")),
                memory_pressure_output=self._command_runner(("memory_pressure", "-Q")),
            )
        except SmokePreflightError as exc:
            raise ModelBackendError(f"resource monitor failed: {exc}") from exc
        snapshot = ResourceSnapshot(
            turn_index=turn_index,
            phase=phase,
            swap_used_bytes=parsed.swap_used_bytes,
            memory_free_percent=parsed.memory_free_percent,
        )
        self._observer(snapshot)
        return snapshot

    def _enforce(self, snapshot: ResourceSnapshot) -> None:
        growth = snapshot.swap_used_bytes - self._baseline.swap_used_bytes
        if growth > self._max_swap_growth_bytes:
            raise ModelBackendError(
                "resource gate stopped the run: swap growth "
                f"{growth} bytes exceeds {self._max_swap_growth_bytes}"
            )
        if snapshot.memory_free_percent < self._minimum_memory_free_percent:
            raise ModelBackendError(
                "resource gate stopped the run: memory free "
                f"{snapshot.memory_free_percent}% is below "
                f"{self._minimum_memory_free_percent}%"
            )


class RequestRecordingLoopBackend:
    """Capture the exact loop requests handed to the real-model backend."""

    def __init__(self, backend: LoopBackend) -> None:
        self._backend = backend
        self.requests: list[LoopRequest] = []

    def complete(self, request: LoopRequest) -> str:
        self.requests.append(request)
        return self._backend.complete(request)


def run_engineering_smoke(
    *,
    run_id: str,
    issue: str,
    model: str,
    fixture_root: str | Path,
    expected_changed_paths: tuple[str, ...],
    tool_document: dict[str, object],
    clock: Callable[[], str],
    monotonic: Callable[[], float] = time.monotonic,
    client: OllamaClient | None = None,
    command_runner: CommandRunner | None = None,
    baseline_observer: BaselineObserver | None = None,
    registry_factory: RegistryFactory | None = None,
    budgets: LoopBudgets | None = None,
    context_mode: str = "simple",
    allow_retained_swap: bool = False,
) -> EngineeringSmokeRun:
    """Run Qwen against one copied fixture only after the clean-host gate."""

    context_mode = _validate_context_mode(context_mode)
    ollama = OllamaClient() if client is None else client
    run_command = _run_host_command if command_runner is None else command_runner
    baseline = validate_smoke_baseline(
        swapusage_output=run_command(("sysctl", "vm.swapusage")),
        memory_pressure_output=run_command(("memory_pressure", "-Q")),
        running_models=ollama.running_models(),
        allow_retained_swap=allow_retained_swap,
    )
    if baseline.memory_free_percent < MINIMUM_MEMORY_FREE_PERCENT:
        raise SmokePreflightError(
            "low_memory",
            "real-model smoke requires at least "
            f"{MINIMUM_MEMORY_FREE_PERCENT}% free memory; observed "
            f"{baseline.memory_free_percent}%",
        )
    if baseline_observer is not None:
        baseline_observer(baseline)

    fixture = Path(fixture_root).resolve(strict=True)
    source_before = _repository_fingerprint(fixture)
    resources: list[ResourceSnapshot] = []
    validator = DecisionValidator.from_tool_document(tool_document)

    with tempfile.TemporaryDirectory(prefix="localcode-engineering-smoke-") as temporary:
        workspace = create_workspace(fixture, Path(temporary) / "repository")
        registry = (
            EngineeringToolRegistry(workspace)
            if registry_factory is None
            else registry_factory(workspace)
        )
        backend = ResourceGuardedLoopBackend(
            OllamaLoopBackend(model=model, tool_document=tool_document, client=ollama),
            baseline=baseline,
            command_runner=run_command,
            observer=resources.append,
        )
        recording_backend = RequestRecordingLoopBackend(backend)
        result = AgentLoop(
            recording_backend,
            validator,
            registry,
            LoopBudgets(
                max_turns=10,
                max_tool_calls=8,
                max_invalid_actions=2,
                max_identical_actions=1,
                max_wall_seconds=600,
                max_context_chars=12_000,
            )
            if budgets is None
            else budgets,
            clock=clock,
            monotonic=monotonic,
            completion_requirements=CompletionRequirements(
                require_patch=True,
                require_passing_tests=True,
            ),
            context_compiler=_context_compiler_for_mode(context_mode, workspace),
        ).run(run_id=run_id, issue=issue)
        final_diff = git_diff(workspace.root)
        first_context_chars, first_selected_paths = _first_context_evidence(recording_backend.requests)

    source_unchanged = source_before == _repository_fingerprint(fixture)
    test_exit_codes = tuple(
        int(metadata["exit_code"])
        for observation in result.observations
        if "exit_code" in (metadata := observation.metadata_dict())
    )
    changed_paths = _changed_paths(final_diff.content)
    normalized_expected = tuple(sorted(expected_changed_paths))
    solved = (
        result.termination_reason is TerminationReason.FINAL_ANSWER
        and result.final_answer is not None
        and bool(test_exit_codes)
        and test_exit_codes[-1] == 0
        and bool(final_diff.content)
        and not final_diff.truncated
        and changed_paths == normalized_expected
        and source_unchanged
    )
    return EngineeringSmokeRun(
        context_mode=context_mode,
        baseline=baseline,
        result=result,
        resource_snapshots=tuple(resources),
        first_context_chars=first_context_chars,
        first_selected_paths=first_selected_paths,
        diff=final_diff.content,
        diff_truncated=final_diff.truncated,
        changed_paths=changed_paths,
        expected_changed_paths=normalized_expected,
        test_exit_codes=test_exit_codes,
        source_unchanged=source_unchanged,
        solved=solved,
    )


def _repository_fingerprint(root: Path) -> str:
    policy = RepositoryPolicy.from_root(root)
    digest = hashlib.sha256()
    for path in sorted(policy.root.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"repository fingerprint rejects symlink: {path}")
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
    paths: list[str] = []
    for old, new in _DIFF_PATH.findall(diff):
        if old != new:
            return ()
        paths.append(old)
    return tuple(sorted(paths))


def _validate_context_mode(context_mode: str) -> str:
    if not isinstance(context_mode, str) or context_mode not in _CONTEXT_MODES:
        raise ValueError("context_mode must be 'simple' or 'retrieval'")
    return context_mode


def _context_compiler_for_mode(context_mode: str, workspace: Workspace) -> SimpleContextCompiler | RetrievalContextCompiler:
    if context_mode == "simple":
        return SimpleContextCompiler()
    return RetrievalContextCompiler(workspace.root, max_files=3)


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
