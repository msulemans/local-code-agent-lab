"""Strict, versioned action parsing for untrusted model output."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from .compatibility import arguments_match_schema, schema_map


MAX_ACTION_PAYLOAD_CHARS = 16_384


class ActionValidationError(ValueError):
    """A safe explanation of why a model action cannot be executed."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class ValidatedAction:
    """An immutable action that passed the protocol and tool schema gates."""

    protocol_version: str
    thought_summary: str
    tool: str
    arguments: tuple[tuple[str, Any], ...]

    def arguments_dict(self) -> dict[str, Any]:
        return dict(self.arguments)


class ActionValidator:
    """Validate exactly one JSON action envelope without semantic repair."""

    def __init__(self, tools_by_name: Mapping[str, dict[str, Any]]) -> None:
        if not tools_by_name:
            raise ValueError("at least one tool schema is required")
        self._tools = dict(tools_by_name)

    @classmethod
    def from_tool_document(cls, document: dict[str, Any]) -> "ActionValidator":
        return cls(schema_map(document))

    @classmethod
    def from_path(cls, path: str | Path) -> "ActionValidator":
        try:
            document = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"cannot load tool schemas: {path}") from exc
        if not isinstance(document, dict):
            raise ValueError("tool schema document must be a JSON object")
        return cls.from_tool_document(document)

    @property
    def tool_names(self) -> tuple[str, ...]:
        return tuple(sorted(self._tools))

    def validate(self, payload: str) -> ValidatedAction:
        if not isinstance(payload, str):
            raise ActionValidationError("invalid_json", "model response must be JSON text")
        if len(payload) > MAX_ACTION_PAYLOAD_CHARS:
            raise ActionValidationError(
                "payload_too_large",
                f"model response exceeds {MAX_ACTION_PAYLOAD_CHARS} characters",
            )
        try:
            envelope = json.loads(payload, object_pairs_hook=_unique_object)
        except json.JSONDecodeError as exc:
            raise ActionValidationError("invalid_json", "model response is not valid JSON") from exc
        if not isinstance(envelope, dict):
            raise ActionValidationError("invalid_envelope", "action envelope must be a JSON object")

        expected_envelope = {"protocol_version", "thought_summary", "action"}
        if set(envelope) != expected_envelope:
            raise ActionValidationError(
                "invalid_envelope",
                _field_mismatch("action envelope", set(envelope), expected_envelope),
            )
        if envelope["protocol_version"] != "1":
            raise ActionValidationError("unsupported_version", "protocol_version must be '1'")

        summary = envelope["thought_summary"]
        if not isinstance(summary, str) or not summary.strip() or len(summary) > 500:
            raise ActionValidationError(
                "invalid_summary",
                "thought_summary must contain 1-500 characters",
            )

        action = envelope["action"]
        if not isinstance(action, dict):
            raise ActionValidationError("invalid_action", "action must be a JSON object")
        expected_action = {"tool", "arguments"}
        if set(action) != expected_action:
            raise ActionValidationError(
                "invalid_action",
                _field_mismatch("action", set(action), expected_action),
            )

        tool = action["tool"]
        if not isinstance(tool, str) or tool not in self._tools:
            raise ActionValidationError("unknown_tool", f"unknown tool: {tool!r}")
        arguments = action["arguments"]
        function_schema = self._tools[tool]
        if not arguments_match_schema(arguments, function_schema) or not _arguments_match_enums(
            arguments,
            function_schema,
        ):
            raise ActionValidationError(
                "invalid_arguments",
                f"arguments do not match the {tool} schema",
            )

        normalized = _apply_declared_defaults(arguments, function_schema)
        if "path" in normalized:
            normalized["path"] = _canonical_path(normalized["path"])
        return ValidatedAction(
            protocol_version="1",
            thought_summary=summary.strip(),
            tool=tool,
            arguments=tuple(sorted(normalized.items())),
        )


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name, value in pairs:
        if name in result:
            raise ActionValidationError("duplicate_field", f"duplicate JSON field: {name!r}")
        result[name] = value
    return result


def _field_mismatch(label: str, actual: set[str], expected: set[str]) -> str:
    missing = sorted(expected - actual)
    unknown = sorted(actual - expected)
    parts = []
    if missing:
        parts.append(f"missing fields: {missing}")
    if unknown:
        parts.append(f"unknown fields: {unknown}")
    return f"{label} has " + "; ".join(parts)


def _apply_declared_defaults(
    arguments: dict[str, Any],
    function_schema: dict[str, Any],
) -> dict[str, Any]:
    result = dict(arguments)
    properties = function_schema.get("parameters", {}).get("properties", {})
    for name, rule in properties.items():
        if name not in result and isinstance(rule, dict) and "default" in rule:
            result[name] = rule["default"]
    return result


def _arguments_match_enums(
    arguments: Any,
    function_schema: dict[str, Any],
) -> bool:
    """Enforce action-only enum constraints without changing the frozen model scorer."""

    if not isinstance(arguments, dict):
        return False
    properties = function_schema.get("parameters", {}).get("properties", {})
    for name, value in arguments.items():
        rule = properties.get(name)
        if not isinstance(rule, dict) or "enum" not in rule:
            continue
        choices = rule["enum"]
        if not isinstance(choices, list) or value not in choices:
            return False
    return True


def _canonical_path(value: Any) -> Any:
    if not isinstance(value, str) or not value or "\x00" in value:
        return value
    return PurePosixPath(value).as_posix()
