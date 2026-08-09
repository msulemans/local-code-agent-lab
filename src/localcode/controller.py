"""A deterministic controller for exactly one model action and one tool call."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

from .actions import ActionValidationError, ActionValidator, ValidatedAction
from .events import Event, EventType
from .registry import ToolRegistry
from .tools import ToolError, ToolResult


@dataclass(frozen=True, slots=True)
class OneTurnRequest:
    issue: str
    allowed_tools: tuple[str, ...]
    protocol_version: str = "1"


class ModelBackend(Protocol):
    def complete(self, request: OneTurnRequest) -> str:
        """Return one untrusted action envelope as JSON text."""


@dataclass(frozen=True, slots=True)
class OneTurnResult:
    events: tuple[Event, ...]
    action: ValidatedAction | None
    observation: ToolResult


class OneTurnController:
    """Call a backend once, then execute at most one read-only tool."""

    def __init__(
        self,
        backend: ModelBackend,
        validator: ActionValidator,
        registry: ToolRegistry,
        *,
        clock: Callable[[], str],
    ) -> None:
        if validator.tool_names != registry.tool_names:
            raise ValueError("validator schemas and registry tools must match exactly")
        self._backend = backend
        self._validator = validator
        self._registry = registry
        self._clock = clock

    def run(self, *, run_id: str, issue: str) -> OneTurnResult:
        events = [self._event(run_id, 0, EventType.RUN_CREATED, "created", "One-turn run created.")]
        request = OneTurnRequest(issue=issue, allowed_tools=self._validator.tool_names)
        raw_response = self._backend.complete(request)

        try:
            action = self._validator.validate(raw_response)
        except ActionValidationError as exc:
            observation = _error_observation("action_rejected", exc.code, str(exc))
            events.append(
                self._event(run_id, 1, EventType.ACTION_REJECTED, "observed", observation.content)
            )
            return OneTurnResult(tuple(events), None, observation)

        events.append(
            self._event(
                run_id,
                1,
                EventType.ACTION_ACCEPTED,
                "acting",
                f"Accepted read-only tool: {action.tool}.",
            )
        )
        try:
            observation = self._registry.execute(action)
        except ToolError as exc:
            observation = _error_observation("tool_error", exc.code, str(exc))
            events.append(self._event(run_id, 2, EventType.TOOL_ERROR, "observed", observation.content))
        else:
            events.append(
                self._event(
                    run_id,
                    2,
                    EventType.TOOL_RESULT,
                    "observed",
                    f"Tool {action.tool} completed.",
                )
            )
        return OneTurnResult(tuple(events), action, observation)

    def _event(
        self,
        run_id: str,
        sequence: int,
        event_type: EventType,
        state: str,
        summary: str,
    ) -> Event:
        return Event(
            schema_version=1,
            run_id=run_id,
            sequence=sequence,
            timestamp=self._clock(),
            event_type=event_type,
            state=state,
            summary=summary,
        )


def _error_observation(kind: str, code: str, message: str) -> ToolResult:
    return ToolResult(
        content=f"{kind}: {message}",
        metadata=(("code", code), ("observation_type", kind)),
    )
