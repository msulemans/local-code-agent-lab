from __future__ import annotations

from dataclasses import FrozenInstanceError
import json
import unittest

from localcode.actions import MAX_ACTION_PAYLOAD_CHARS, ActionValidationError, ActionValidator


SCHEMAS = "benchmarks/model_compatibility/tool_schemas.json"


def payload(tool: str = "search_code", arguments: object | None = None, **extra: object) -> str:
    envelope = {
        "protocol_version": "1",
        "thought_summary": "Find parser references before reading a file.",
        "action": {
            "tool": tool,
            "arguments": {"query": "parse("} if arguments is None else arguments,
        },
        **extra,
    }
    return json.dumps(envelope)


class ActionValidatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.validator = ActionValidator.from_path(SCHEMAS)

    def test_valid_action_is_immutable_and_receives_declared_defaults(self) -> None:
        action = self.validator.validate(payload())

        self.assertEqual(action.tool, "search_code")
        self.assertEqual(action.arguments_dict()["path"], ".")
        self.assertEqual(action.arguments_dict()["max_results"], 40)
        with self.assertRaises(FrozenInstanceError):
            action.tool = "read_file"  # type: ignore[misc]

    def test_empty_string_optional_path_uses_declared_default(self) -> None:
        action = self.validator.validate(payload(arguments={"query": "parse(", "path": ""}))

        # gpt-oss sends an empty string for optional fields; that is
        # semantically identical to omitting the field (smoke-gptoss20b-v1).
        self.assertEqual(action.arguments_dict()["path"], ".")

    def test_harmless_relative_path_syntax_is_canonicalized(self) -> None:
        action = self.validator.validate(payload(arguments={"query": "parse(", "path": "./src/"}))

        self.assertEqual(action.arguments_dict()["path"], "src")

    def test_invalid_json_and_unknown_tool_are_typed(self) -> None:
        with self.assertRaises(ActionValidationError) as invalid:
            self.validator.validate("not json")
        with self.assertRaises(ActionValidationError) as unknown:
            self.validator.validate(payload(tool="terminal", arguments={"command": "pwd"}))

        self.assertEqual(invalid.exception.code, "invalid_json")
        self.assertEqual(unknown.exception.code, "unknown_tool")

    def test_unknown_envelope_fields_are_rejected(self) -> None:
        with self.assertRaises(ActionValidationError) as raised:
            self.validator.validate(payload(debug=True))

        self.assertEqual(raised.exception.code, "invalid_envelope")

    def test_arguments_are_not_semantically_repaired(self) -> None:
        with self.assertRaises(ActionValidationError) as raised:
            self.validator.validate(payload(arguments={"query": "parse(", "max_results": 0}))

        self.assertEqual(raised.exception.code, "invalid_arguments")

    def test_oversized_payload_is_rejected_before_parsing(self) -> None:
        with self.assertRaises(ActionValidationError) as raised:
            self.validator.validate("x" * (MAX_ACTION_PAYLOAD_CHARS + 1))

        self.assertEqual(raised.exception.code, "payload_too_large")

    def test_duplicate_json_fields_are_rejected_at_any_depth(self) -> None:
        duplicate = (
            '{"protocol_version":"1","thought_summary":"Inspect safely",'
            '"action":{"tool":"search_code","tool":"read_file",'
            '"arguments":{"query":"parse"}}}'
        )

        with self.assertRaises(ActionValidationError) as raised:
            self.validator.validate(duplicate)

        self.assertEqual(raised.exception.code, "duplicate_field")


if __name__ == "__main__":
    unittest.main()
