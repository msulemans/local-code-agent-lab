"""Versioned immutable event values for LocalCode traces."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import json
from typing import Any, Mapping


class EventError(ValueError):
    """Raised when event data violates the event schema."""


class EventType(str, Enum):
    RUN_CREATED = "run_created"
    NOTE = "note"
    ACTION_ACCEPTED = "action_accepted"
    ACTION_REJECTED = "action_rejected"
    TOOL_RESULT = "tool_result"
    TOOL_ERROR = "tool_error"
    FINAL_ANSWER = "final_answer"
    REPEATED_ACTION = "repeated_action"
    BACKEND_ERROR = "backend_error"
    RUN_TERMINATED = "run_terminated"


_EVENT_KEYS = frozenset(
    {
        "schema_version",
        "run_id",
        "sequence",
        "timestamp",
        "event_type",
        "state",
        "summary",
        "artifact_refs",
        "budgets_remaining",
    }
)


def _required_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EventError(f"{field} must be a non-empty string")
    return value


@dataclass(frozen=True, slots=True)
class Event:
    """One immutable fact in a LocalCode run trace."""

    schema_version: int
    run_id: str
    sequence: int
    timestamp: str
    event_type: EventType
    state: str
    summary: str
    artifact_refs: tuple[str, ...] = ()
    budgets_remaining: tuple[tuple[str, int], ...] = ()

    def __post_init__(self) -> None:
        if isinstance(self.schema_version, bool) or self.schema_version != 1:
            raise EventError("schema_version must be 1")
        _required_string(self.run_id, "run_id")
        if isinstance(self.sequence, bool) or not isinstance(self.sequence, int):
            raise EventError("sequence must be a non-negative integer")
        if self.sequence < 0:
            raise EventError("sequence must be a non-negative integer")
        timestamp = _required_string(self.timestamp, "timestamp")
        try:
            parsed_timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError as exc:
            raise EventError("timestamp must be ISO 8601") from exc
        if parsed_timestamp.tzinfo is None:
            raise EventError("timestamp must include a timezone")
        if not isinstance(self.event_type, EventType):
            raise EventError("event_type must be an EventType")
        _required_string(self.state, "state")
        _required_string(self.summary, "summary")
        if not isinstance(self.artifact_refs, tuple):
            raise EventError("artifact_refs must be an immutable tuple")
        if any(not isinstance(ref, str) or not ref for ref in self.artifact_refs):
            raise EventError("artifact_refs must contain non-empty strings")

        if not isinstance(self.budgets_remaining, tuple):
            raise EventError("budgets_remaining must be an immutable tuple")
        budget_names: set[str] = set()
        ordered_budget_names: list[str] = []
        for item in self.budgets_remaining:
            if not isinstance(item, tuple) or len(item) != 2:
                raise EventError("each budget must be an immutable name/value pair")
            name, remaining = item
            if not isinstance(name, str) or not name:
                raise EventError("budget names must be non-empty strings")
            if name in budget_names:
                raise EventError(f"duplicate budget name: {name}")
            if isinstance(remaining, bool) or not isinstance(remaining, int) or remaining < 0:
                raise EventError(f"budget {name} must be a non-negative integer")
            budget_names.add(name)
            ordered_budget_names.append(name)
        if ordered_budget_names != sorted(ordered_budget_names):
            raise EventError("budgets_remaining must be sorted by budget name")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "sequence": self.sequence,
            "timestamp": self.timestamp,
            "event_type": self.event_type.value,
            "state": self.state,
            "summary": self.summary,
            "artifact_refs": list(self.artifact_refs),
            "budgets_remaining": dict(self.budgets_remaining),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))

    @classmethod
    def from_dict(cls, values: Mapping[str, Any]) -> "Event":
        keys = set(values)
        missing = _EVENT_KEYS - keys
        unknown = keys - _EVENT_KEYS
        if missing:
            raise EventError(f"missing event fields: {sorted(missing)}")
        if unknown:
            raise EventError(f"unknown event fields: {sorted(unknown)}")

        raw_artifacts = values["artifact_refs"]
        raw_budgets = values["budgets_remaining"]
        if not isinstance(raw_artifacts, list):
            raise EventError("artifact_refs must be a JSON array")
        if not isinstance(raw_budgets, dict):
            raise EventError("budgets_remaining must be a JSON object")

        try:
            event_type = EventType(values["event_type"])
        except (TypeError, ValueError) as exc:
            raise EventError(f"unknown event_type: {values['event_type']!r}") from exc

        return cls(
            schema_version=values["schema_version"],
            run_id=values["run_id"],
            sequence=values["sequence"],
            timestamp=values["timestamp"],
            event_type=event_type,
            state=values["state"],
            summary=values["summary"],
            artifact_refs=tuple(raw_artifacts),
            budgets_remaining=tuple(sorted(raw_budgets.items())),
        )

    @classmethod
    def from_json(cls, payload: str) -> "Event":
        try:
            raw = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise EventError("event payload is not valid JSON") from exc
        if not isinstance(raw, dict):
            raise EventError("event root must be a JSON object")
        return cls.from_dict(raw)
