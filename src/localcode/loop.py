"""Deterministic bounded agent loop for repository inspection and repair."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import json
from typing import Callable, Protocol

from .actions import ActionValidationError, ValidatedAction
from .context import ContextCompiler, ContextRequest, SimpleContextCompiler, compile_simple_context
from .controller import ActionRegistry, ModelBackendError
from .decisions import DecisionValidator, FinalDecision
from .events import Event, EventType
from .tools import ToolError, ToolResult


@dataclass(frozen=True, slots=True)
class LoopBudgets:
    max_turns: int = 8
    max_invalid_actions: int = 3
    max_tool_calls: int = 6
    max_identical_actions: int = 1
    max_wall_seconds: float = 120.0
    max_context_chars: int = 12_000
    recover_repeated_actions: bool = False
    phase_tool_policy: bool = False
    auto_test_after_edit: bool = False

    def __post_init__(self) -> None:
        integer_fields = (
            ("max_turns", self.max_turns),
            ("max_invalid_actions", self.max_invalid_actions),
            ("max_tool_calls", self.max_tool_calls),
            ("max_identical_actions", self.max_identical_actions),
            ("max_context_chars", self.max_context_chars),
        )
        for name, value in integer_fields:
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        if self.max_context_chars < 512:
            raise ValueError("max_context_chars must be at least 512")
        if not isinstance(self.recover_repeated_actions, bool):
            raise ValueError("recover_repeated_actions must be a boolean")
        if not isinstance(self.phase_tool_policy, bool):
            raise ValueError("phase_tool_policy must be a boolean")
        if not isinstance(self.auto_test_after_edit, bool):
            raise ValueError("auto_test_after_edit must be a boolean")
        if (
            isinstance(self.max_wall_seconds, bool)
            or not isinstance(self.max_wall_seconds, (int, float))
            or self.max_wall_seconds <= 0
        ):
            raise ValueError("max_wall_seconds must be positive")


@dataclass(frozen=True, slots=True)
class CompletionRequirements:
    require_patch: bool = False
    require_passing_tests: bool = False
    require_test_execution: bool = False

    def __post_init__(self) -> None:
        if not all(
            isinstance(value, bool)
            for value in (
                self.require_patch,
                self.require_passing_tests,
                self.require_test_execution,
            )
        ):
            raise ValueError("completion requirements must be booleans")


@dataclass(frozen=True, slots=True)
class LoopRequest:
    issue: str
    context: str
    allowed_tools: tuple[str, ...]
    turn_index: int
    budgets_remaining: tuple[tuple[str, int], ...]
    protocol_version: str = "1"


class LoopBackend(Protocol):
    def complete(self, request: LoopRequest) -> str:
        """Return one untrusted loop-decision envelope."""


class LoopObserver(Protocol):
    """Presentation-only callbacks for immutable loop facts."""

    def on_event(self, event: Event) -> None:
        """Observe one event after it has been appended to the trace."""

    def on_observation(self, observation: ToolResult) -> None:
        """Observe one tool/backend/action observation after it has been recorded."""


class TerminationReason(str, Enum):
    FINAL_ANSWER = "final_answer"
    INVALID_ACTION_EXHAUSTION = "invalid_action_exhaustion"
    TOOL_EXHAUSTION = "tool_exhaustion"
    REPEATED_ACTION = "repeated_action"
    BACKEND_ERROR = "backend_error"
    WALL_CLOCK_TIMEOUT = "wall_clock_timeout"
    TURN_EXHAUSTION = "turn_exhaustion"


@dataclass(frozen=True, slots=True)
class LoopResult:
    events: tuple[Event, ...]
    observations: tuple[ToolResult, ...]
    termination_reason: TerminationReason
    final_answer: str | None
    turns_used: int
    tool_calls_used: int
    invalid_actions_used: int

    @property
    def tests_executed(self) -> int:
        """Count completed test observations, excluding rejected/tool-error calls."""

        return sum("exit_code" in observation.metadata_dict() for observation in self.observations)


class ReadOnlyAgentLoop:
    """Execute bounded validated decisions through a supplied capability registry."""

    def __init__(
        self,
        backend: LoopBackend,
        validator: DecisionValidator,
        registry: ActionRegistry,
        budgets: LoopBudgets,
        *,
        clock: Callable[[], str],
        monotonic: Callable[[], float],
        completion_requirements: CompletionRequirements | None = None,
        observer: LoopObserver | None = None,
        context_compiler: ContextCompiler | None = None,
    ) -> None:
        if validator.tool_names != registry.tool_names:
            raise ValueError("validator schemas and registry tools must match exactly")
        self._backend = backend
        self._validator = validator
        self._registry = registry
        self._budgets = budgets
        self._clock = clock
        self._monotonic = monotonic
        self._completion = (
            CompletionRequirements()
            if completion_requirements is None
            else completion_requirements
        )
        self._observer = observer
        self._context_compiler = SimpleContextCompiler() if context_compiler is None else context_compiler

    def run(self, *, run_id: str, issue: str) -> LoopResult:
        events: list[Event] = []
        observations: list[ToolResult] = []
        history: list[str] = []
        tool_history: list[str] = []
        action_counts: dict[str, int] = {}
        turns_used = 0
        tool_calls_used = 0
        invalid_actions_used = 0
        patch_applied = False
        tests_passed = False
        tests_executed = 0
        started = self._monotonic()

        self._append_event(
            events,
            run_id,
            EventType.RUN_CREATED,
            "created",
            "Bounded agent run created.",
            turns_used,
            tool_calls_used,
            invalid_actions_used,
        )

        for turn_index in range(self._budgets.max_turns):
            if self._expired(started):
                return self._terminate(
                    events,
                    observations,
                    run_id,
                    TerminationReason.WALL_CLOCK_TIMEOUT,
                    turns_used,
                    tool_calls_used,
                    invalid_actions_used,
                )

            remaining = self._remaining(turns_used, tool_calls_used, invalid_actions_used)
            request = LoopRequest(
                issue=issue,
                context=self._context_compiler.compile(
                    ContextRequest(
                        issue=issue,
                        history=tuple(history),
                        budgets_remaining=remaining,
                        max_chars=self._budgets.max_context_chars,
                    )
                ),
                allowed_tools=_phase_tools(self._validator.tool_names, tool_history)
                if self._budgets.phase_tool_policy
                else self._validator.tool_names,
                turn_index=turn_index,
                budgets_remaining=remaining,
            )
            turns_used += 1
            try:
                raw_response = self._backend.complete(request)
            except ModelBackendError as exc:
                observation = _error_observation("backend_error", "backend_error", str(exc))
                self._append_observation(observations, observation)
                self._append_event(
                    events,
                    run_id,
                    EventType.BACKEND_ERROR,
                    "failed",
                    observation.content,
                    turns_used,
                    tool_calls_used,
                    invalid_actions_used,
                )
                return self._terminate(
                    events,
                    observations,
                    run_id,
                    TerminationReason.BACKEND_ERROR,
                    turns_used,
                    tool_calls_used,
                    invalid_actions_used,
                )

            if self._expired(started):
                return self._terminate(
                    events,
                    observations,
                    run_id,
                    TerminationReason.WALL_CLOCK_TIMEOUT,
                    turns_used,
                    tool_calls_used,
                    invalid_actions_used,
                )

            try:
                decision = self._validator.validate(raw_response)
            except ActionValidationError as exc:
                invalid_actions_used += 1
                observation = _error_observation("action_rejected", exc.code, str(exc))
                self._append_observation(observations, observation)
                history.append(observation.content)
                self._append_event(
                    events,
                    run_id,
                    EventType.ACTION_REJECTED,
                    "inspecting",
                    observation.content,
                    turns_used,
                    tool_calls_used,
                    invalid_actions_used,
                )
                if invalid_actions_used >= self._budgets.max_invalid_actions:
                    return self._terminate(
                        events,
                        observations,
                        run_id,
                        TerminationReason.INVALID_ACTION_EXHAUSTION,
                        turns_used,
                        tool_calls_used,
                        invalid_actions_used,
                    )
                continue

            if isinstance(decision, FinalDecision):
                missing = []
                if self._completion.require_patch and not patch_applied:
                    missing.append("applied patch")
                if self._completion.require_passing_tests and not tests_passed:
                    missing.append("passing test command")
                elif self._completion.require_test_execution and tests_executed == 0:
                    missing.append("executed test command")
                if missing:
                    invalid_actions_used += 1
                    message = "final answer rejected; missing " + " and ".join(missing)
                    observation = _error_observation(
                        "action_rejected",
                        "incomplete_work",
                        message,
                    )
                    self._append_observation(observations, observation)
                    history.append(observation.content)
                    self._append_event(
                        events,
                        run_id,
                        EventType.ACTION_REJECTED,
                        "verifying",
                        observation.content,
                        turns_used,
                        tool_calls_used,
                        invalid_actions_used,
                    )
                    if invalid_actions_used >= self._budgets.max_invalid_actions:
                        return self._terminate(
                            events,
                            observations,
                            run_id,
                            TerminationReason.INVALID_ACTION_EXHAUSTION,
                            turns_used,
                            tool_calls_used,
                            invalid_actions_used,
                        )
                    continue
                self._append_event(
                    events,
                    run_id,
                    EventType.FINAL_ANSWER,
                    "completed",
                    "Model returned a final answer.",
                    turns_used,
                    tool_calls_used,
                    invalid_actions_used,
                )
                return LoopResult(
                    tuple(events),
                    tuple(observations),
                    TerminationReason.FINAL_ANSWER,
                    decision.answer,
                    turns_used,
                    tool_calls_used,
                    invalid_actions_used,
                )

            signature = _action_signature(decision)
            prior_count = action_counts.get(signature, 0)
            if prior_count >= self._budgets.max_identical_actions:
                if self._budgets.recover_repeated_actions:
                    invalid_actions_used += 1
                    observation = _error_observation(
                        "action_rejected",
                        "repeated_action",
                        f"do not repeat {decision.tool} with identical arguments; choose a different next action",
                    )
                    self._append_observation(observations, observation)
                    history.append(observation.content)
                    self._append_event(
                        events,
                        run_id,
                        EventType.ACTION_REJECTED,
                        "inspecting",
                        observation.content,
                        turns_used,
                        tool_calls_used,
                        invalid_actions_used,
                    )
                    if invalid_actions_used >= self._budgets.max_invalid_actions:
                        return self._terminate(
                            events,
                            observations,
                            run_id,
                            TerminationReason.INVALID_ACTION_EXHAUSTION,
                            turns_used,
                            tool_calls_used,
                            invalid_actions_used,
                        )
                    continue
                self._append_event(
                    events,
                    run_id,
                    EventType.REPEATED_ACTION,
                    "failed",
                    f"Repeated action blocked: {decision.tool}.",
                    turns_used,
                    tool_calls_used,
                    invalid_actions_used,
                )
                return self._terminate(
                    events,
                    observations,
                    run_id,
                    TerminationReason.REPEATED_ACTION,
                    turns_used,
                    tool_calls_used,
                    invalid_actions_used,
                )
            if tool_calls_used >= self._budgets.max_tool_calls:
                return self._terminate(
                    events,
                    observations,
                    run_id,
                    TerminationReason.TOOL_EXHAUSTION,
                    turns_used,
                    tool_calls_used,
                    invalid_actions_used,
                )

            action_counts[signature] = prior_count + 1
            action_state = _state_for_tool(decision.tool)
            self._append_event(
                events,
                run_id,
                EventType.ACTION_ACCEPTED,
                action_state,
                f"Accepted tool: {decision.tool}.",
                turns_used,
                tool_calls_used,
                invalid_actions_used,
            )
            tool_calls_used += 1
            try:
                observation = self._registry.execute(decision)
            except ToolError as exc:
                observation = _error_observation("tool_error", exc.code, str(exc))
                event_type = EventType.TOOL_ERROR
                summary = observation.content
            else:
                event_type = EventType.TOOL_RESULT
                summary = f"Tool {decision.tool} completed."
                if decision.tool in {"apply_patch", "edit_file", "write_file"}:
                    patch_applied = True
                    tests_passed = False
                    action_counts.clear()
                elif decision.tool == "run_tests":
                    tests_executed += 1
                    tests_passed = observation.metadata_dict().get("exit_code") == 0
            self._append_observation(observations, observation)
            tool_history.append(decision.tool)
            history.append(
                json.dumps(
                    {
                        "tool": decision.tool,
                        "arguments": decision.arguments_dict(),
                        "observation": observation.content,
                        "metadata": observation.metadata_dict(),
                        "controller_guidance": _controller_guidance(
                            decision.tool,
                            patch_applied=patch_applied,
                            tests_passed=tests_passed,
                        ),
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                )
            )
            self._append_event(
                events,
                run_id,
                event_type,
                action_state,
                summary,
                turns_used,
                tool_calls_used,
                invalid_actions_used,
            )

            if (
                self._budgets.auto_test_after_edit
                and decision.tool in ("apply_patch", "edit_file", "write_file")
                and event_type == EventType.TOOL_RESULT
                and "run_tests" in self._validator.tool_names
            ):
                # Deterministic verification: after every successful edit the
                # controller runs the registered tests itself, so a model that
                # churns on read/edit re-checks cannot exhaust the budget
                # without ever seeing test output (m050-m055).
                auto_action = ValidatedAction(
                    protocol_version="1",
                    thought_summary="automatic verification after edit",
                    tool="run_tests",
                    arguments=(("command_name", "python-unittest"),),
                )
                try:
                    auto_observation = self._registry.execute(auto_action)
                except ToolError as exc:
                    auto_observation = _error_observation("tool_error", exc.code, str(exc))
                    auto_event_type = EventType.TOOL_ERROR
                    auto_summary = auto_observation.content
                else:
                    tests_executed += 1
                    tests_passed = auto_observation.metadata_dict().get("exit_code") == 0
                    auto_event_type = EventType.TOOL_RESULT
                    auto_summary = "Automatic verification after edit completed."
                tool_calls_used += 1
                self._append_observation(observations, auto_observation)
                tool_history.append("run_tests")
                history.append(
                    json.dumps(
                        {
                            "tool": "run_tests",
                            "arguments": {"command_name": "python-unittest"},
                            "observation": auto_observation.content,
                            "metadata": auto_observation.metadata_dict(),
                            "controller_guidance": "Automatic test run after edit; revise with edit_file or apply_patch if failing, otherwise review with git_diff and finish.",
                        },
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                )
                self._append_event(
                    events,
                    run_id,
                    auto_event_type,
                    "verifying",
                    auto_summary,
                    turns_used,
                    tool_calls_used,
                    invalid_actions_used,
                )
                if tool_calls_used >= self._budgets.max_tool_calls:
                    return self._terminate(
                        events,
                        observations,
                        run_id,
                        TerminationReason.TOOL_EXHAUSTION,
                        turns_used,
                        tool_calls_used,
                        invalid_actions_used,
                    )
                if self._expired(started):
                    return self._terminate(
                        events,
                        observations,
                        run_id,
                        TerminationReason.WALL_CLOCK_TIMEOUT,
                        turns_used,
                        tool_calls_used,
                        invalid_actions_used,
                    )

        return self._terminate(
            events,
            observations,
            run_id,
            TerminationReason.TURN_EXHAUSTION,
            turns_used,
            tool_calls_used,
            invalid_actions_used,
        )

    def _expired(self, started: float) -> bool:
        return self._monotonic() - started >= self._budgets.max_wall_seconds

    def _remaining(
        self,
        turns_used: int,
        tool_calls_used: int,
        invalid_actions_used: int,
    ) -> tuple[tuple[str, int], ...]:
        return (
            ("invalid_actions", self._budgets.max_invalid_actions - invalid_actions_used),
            ("tool_calls", self._budgets.max_tool_calls - tool_calls_used),
            ("turns", self._budgets.max_turns - turns_used),
        )

    def _append_event(
        self,
        events: list[Event],
        run_id: str,
        event_type: EventType,
        state: str,
        summary: str,
        turns_used: int,
        tool_calls_used: int,
        invalid_actions_used: int,
    ) -> None:
        event = Event(
            schema_version=1,
            run_id=run_id,
            sequence=len(events),
            timestamp=self._clock(),
            event_type=event_type,
            state=state,
            summary=summary,
            budgets_remaining=self._remaining(
                turns_used,
                tool_calls_used,
                invalid_actions_used,
            ),
        )
        events.append(event)
        self._notify_event(event)

    def _append_observation(
        self,
        observations: list[ToolResult],
        observation: ToolResult,
    ) -> None:
        observations.append(observation)
        self._notify_observation(observation)

    def _notify_event(self, event: Event) -> None:
        if self._observer is None:
            return
        try:
            self._observer.on_event(event)
        except Exception:
            # Observers are presentation only; rendering must not change agent semantics.
            return

    def _notify_observation(self, observation: ToolResult) -> None:
        if self._observer is None:
            return
        try:
            self._observer.on_observation(observation)
        except Exception:
            # Observers are presentation only; rendering must not change agent semantics.
            return

    def _terminate(
        self,
        events: list[Event],
        observations: list[ToolResult],
        run_id: str,
        reason: TerminationReason,
        turns_used: int,
        tool_calls_used: int,
        invalid_actions_used: int,
    ) -> LoopResult:
        self._append_event(
            events,
            run_id,
            EventType.RUN_TERMINATED,
            "budget_exhausted" if "exhaustion" in reason.value else "failed",
            f"Run terminated: {reason.value}.",
            turns_used,
            tool_calls_used,
            invalid_actions_used,
        )
        return LoopResult(
            tuple(events),
            tuple(observations),
            reason,
            None,
            turns_used,
            tool_calls_used,
            invalid_actions_used,
        )


def _compile_context(
    issue: str,
    history: tuple[str, ...],
    budgets_remaining: tuple[tuple[str, int], ...],
    max_chars: int,
) -> str:
    return compile_simple_context(issue, history, budgets_remaining, max_chars)


def _action_signature(action: ValidatedAction) -> str:
    arguments = action.arguments_dict()
    # Optional presentation/bound fields must not let a model evade repeated
    # discovery detection by changing only defaults.
    if action.tool == "search_code":
        arguments = {
            key: arguments[key]
            for key in ("query", "path", "glob", "regex", "case_sensitive")
            if key in arguments
        }
        arguments.pop("path", None)
        arguments.pop("glob", None)
        arguments.pop("regex", None)
        arguments.pop("case_sensitive", None)
    return json.dumps(
        {"tool": action.tool, "arguments": arguments},
        sort_keys=True,
        separators=(",", ":"),
    )


def _error_observation(kind: str, code: str, message: str) -> ToolResult:
    return ToolResult(
        content=f"{kind}: {message}",
        metadata=(("code", code), ("observation_type", kind)),
    )


def _state_for_tool(tool: str) -> str:
    if tool in {"apply_patch", "edit_file", "write_file"}:
        return "editing"
    if tool == "run_tests":
        return "verifying"
    if tool == "git_diff":
        return "reviewing"
    return "inspecting"


def _controller_guidance(tool: str, *, patch_applied: bool, tests_passed: bool) -> str:
    """Make the bounded repair phases explicit in the next model context."""
    if tool == "search_code":
        return "Search completed; inspect the most relevant file with read_file, then edit. Do not repeat this search."
    if tool == "read_file":
        return "Evidence is available; use edit_file with an exact old_string/new_string snippet (or apply_patch) next unless another concrete file is required."
    if tool in ("apply_patch", "edit_file", "write_file"):
        return "Change written; run the registered tests next."
    if tool == "run_tests":
        return "Tests observed; revise with edit_file or apply_patch if failing, otherwise review with git_diff."
    if tool == "git_diff":
        return "Review complete; provide a final answer only when the required patch is present."
    return "Continue to the next bounded repair phase."


def _phase_tools(all_tools: tuple[str, ...], history: list[str]) -> tuple[str, ...]:
    """Narrow native tools to the next repair phase for real-agent runs."""
    if not history:
        return all_tools
    last = history[-1]
    if last in {"list_files", "search_code"}:
        return ("read_file",)
    if last == "read_file":
        return ("apply_patch", "edit_file", "read_file", "write_file")
    if last in {"apply_patch", "edit_file", "write_file"}:
        return ("run_tests",)
    if last == "run_tests":
        return (
            "apply_patch",
            "edit_file",
            "git_diff",
            "read_file",
            "search_code",
            "write_file",
        )
    if last == "git_diff":
        return ()
    return all_tools


AgentLoop = ReadOnlyAgentLoop
