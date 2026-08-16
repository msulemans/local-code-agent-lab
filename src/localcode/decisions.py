"""Strict protocol parsing for one multi-turn agent decision."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from .actions import ActionValidationError, ActionValidator, ValidatedAction


MAX_DECISION_PAYLOAD_CHARS = 16_384


@dataclass(frozen=True, slots=True)
class FinalDecision:
    protocol_version: str
    thought_summary: str
    answer: str


LoopDecision = ValidatedAction | FinalDecision


class DecisionValidator:
    """Validate a tool proposal or final answer without repairing either."""

    def __init__(self, action_validator: ActionValidator) -> None:
        self._actions = action_validator

    @classmethod
    def from_path(cls, path: str | Path) -> "DecisionValidator":
        return cls(ActionValidator.from_path(path))

    @classmethod
    def from_tool_document(cls, document: dict[str, Any]) -> "DecisionValidator":
        return cls(ActionValidator.from_tool_document(document))

    @property
    def tool_names(self) -> tuple[str, ...]:
        return self._actions.tool_names

    def validate(self, payload: str) -> LoopDecision:
        if not isinstance(payload, str):
            raise ActionValidationError("invalid_json", "model response must be JSON text")
        if len(payload) > MAX_DECISION_PAYLOAD_CHARS:
            raise ActionValidationError(
                "payload_too_large",
                f"model response exceeds {MAX_DECISION_PAYLOAD_CHARS} characters",
            )
        try:
            envelope = json.loads(payload, object_pairs_hook=_unique_object)
        except json.JSONDecodeError as exc:
            raise ActionValidationError("invalid_json", "model response is not valid JSON") from exc
        if not isinstance(envelope, dict):
            raise ActionValidationError("invalid_envelope", "decision envelope must be an object")
        expected = {"protocol_version", "thought_summary", "decision"}
        if set(envelope) != expected:
            raise ActionValidationError("invalid_envelope", "decision envelope fields do not match")
        if envelope["protocol_version"] != "1":
            raise ActionValidationError("unsupported_version", "protocol_version must be '1'")

        summary = envelope["thought_summary"]
        if not isinstance(summary, str) or not summary.strip() or len(summary) > 500:
            raise ActionValidationError(
                "invalid_summary",
                "thought_summary must contain 1-500 characters",
            )
        decision = envelope["decision"]
        if not isinstance(decision, dict):
            raise ActionValidationError("invalid_decision", "decision must be an object")

        kind = decision.get("kind")
        if kind == "tool":
            if set(decision) != {"kind", "tool", "arguments"}:
                raise ActionValidationError("invalid_decision", "tool decision fields do not match")
            action_payload = json.dumps(
                {
                    "protocol_version": "1",
                    "thought_summary": summary,
                    "action": {
                        "tool": decision["tool"],
                        "arguments": decision["arguments"],
                    },
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            return self._actions.validate(action_payload)

        if kind == "final":
            if set(decision) != {"kind", "answer"}:
                raise ActionValidationError("invalid_decision", "final decision fields do not match")
            answer = decision["answer"]
            if not isinstance(answer, str) or not answer.strip() or len(answer) > 4_000:
                raise ActionValidationError(
                    "invalid_final_answer",
                    "final answer must contain 1-4000 characters",
                )
            return FinalDecision("1", summary.strip(), answer.strip())

        raise ActionValidationError("invalid_decision", f"unknown decision kind: {kind!r}")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name, value in pairs:
        if name in result:
            raise ActionValidationError("duplicate_field", f"duplicate JSON field: {name!r}")
        result[name] = value
    return result
