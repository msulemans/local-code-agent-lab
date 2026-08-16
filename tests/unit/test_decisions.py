from __future__ import annotations

import json
from pathlib import Path
import unittest

from localcode.actions import ActionValidationError, ValidatedAction
from localcode.decisions import DecisionValidator, FinalDecision


SCHEMAS = Path("benchmarks/model_compatibility/tool_schemas.json")


def payload(decision: dict[str, object]) -> str:
    return json.dumps(
        {
            "protocol_version": "1",
            "thought_summary": "Use repository evidence.",
            "decision": decision,
        }
    )


class DecisionValidatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.validator = DecisionValidator.from_path(SCHEMAS)

    def test_tool_decision_reuses_the_strict_action_contract(self) -> None:
        decision = self.validator.validate(
            payload({"kind": "tool", "tool": "search_code", "arguments": {"query": "parse"}})
        )

        self.assertIsInstance(decision, ValidatedAction)
        self.assertEqual(decision.tool, "search_code")
        self.assertEqual(decision.arguments_dict()["max_results"], 40)

    def test_final_decision_is_bounded_and_immutable(self) -> None:
        decision = self.validator.validate(
            payload({"kind": "final", "answer": "The parser definition is in src/parser.py."})
        )

        self.assertEqual(
            decision,
            FinalDecision(
                protocol_version="1",
                thought_summary="Use repository evidence.",
                answer="The parser definition is in src/parser.py.",
            ),
        )

    def test_unknown_kinds_fields_and_duplicate_keys_are_rejected(self) -> None:
        cases = (
            payload({"kind": "wait"}),
            payload({"kind": "final", "answer": "done", "extra": True}),
            '{"protocol_version":"1","thought_summary":"x","decision":{"kind":"final","answer":"a","answer":"b"}}',
        )
        for value in cases:
            with self.subTest(value=value):
                with self.assertRaises(ActionValidationError):
                    self.validator.validate(value)

    def test_invalid_tool_arguments_and_empty_final_answer_are_rejected(self) -> None:
        cases = (
            payload({"kind": "tool", "tool": "search_code", "arguments": {"query": 7}}),
            payload({"kind": "final", "answer": "  "}),
        )
        for value in cases:
            with self.subTest(value=value):
                with self.assertRaises(ActionValidationError):
                    self.validator.validate(value)


if __name__ == "__main__":
    unittest.main()
