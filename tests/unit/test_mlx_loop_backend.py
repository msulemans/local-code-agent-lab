from __future__ import annotations

import json
from pathlib import Path
import unittest

from localcode.backends.mlx_loop import MlxLoopBackend
from localcode.decisions import DecisionValidator, FinalDecision
from localcode.loop import LoopRequest


SCHEMAS = Path("benchmarks/micro_agent/tool_schemas.json")


class FakeTokenizer:
    def apply_chat_template(self, messages, *, add_generation_prompt, tokenize):
        self.messages = messages
        return messages[-1]["content"] + "\n<assistant>"

    def encode(self, text):
        return text.split()


def request() -> LoopRequest:
    return LoopRequest(
        issue="Fix parser",
        context='{"issue":"Fix parser","history":[]}',
        allowed_tools=("apply_patch", "edit_file", "git_diff", "list_files", "read_file", "run_tests", "search_code", "write_file"),
        turn_index=0,
        budgets_remaining=(("turns", 4),),
    )


class MlxLoopBackendTests(unittest.TestCase):
    def backend(self, response: str) -> MlxLoopBackend:
        tokenizer = FakeTokenizer()

        def generate(model, tokenizer, **kwargs):
            self.assertEqual(kwargs["verbose"], False)
            self.assertEqual(kwargs["max_tokens"], 64)
            return response

        return MlxLoopBackend(
            model_path=Path("/tmp/fake-qwen"),
            tool_document=json.loads(SCHEMAS.read_text(encoding="utf-8")),
            max_output_tokens=64,
            model=object(),
            tokenizer=tokenizer,
            generate=generate,
        )

    def test_protocol_decision_is_canonicalized(self) -> None:
        response = json.dumps(
            {
                "protocol_version": "1",
                "thought_summary": "inspect",
                "decision": {"kind": "tool", "tool": "search_code", "arguments": {"query": "parse"}},
            }
        ) + "<|im_end|>"
        decision = DecisionValidator.from_path(SCHEMAS).validate(self.backend(response).complete(request()))
        self.assertEqual(decision.tool, "search_code")

    def test_qwen_content_tool_call_is_wrapped_without_argument_repair(self) -> None:
        response = '<tool_call>{"name":"read_file","arguments":{"path":"src/tiny_parser.py"}}</tool_call>'
        decision = DecisionValidator.from_path(SCHEMAS).validate(self.backend(response).complete(request()))
        self.assertEqual(decision.tool, "read_file")
        self.assertEqual(decision.arguments_dict()["path"], "src/tiny_parser.py")

    def test_qwen_direct_tool_kind_is_normalized_to_typed_decision(self) -> None:
        response = json.dumps(
            {
                "protocol_version": "1",
                "thought_summary": "edit",
                "decision": {
                    "kind": "edit_file",
                    "arguments": {
                        "path": "src/tiny_parser.py",
                        "old_string": "return text.strip()",
                        "new_string": "return (text or '').strip()",
                    },
                },
            }
        )
        decision = DecisionValidator.from_path(SCHEMAS).validate(self.backend(response).complete(request()))
        self.assertEqual(decision.tool, "edit_file")
        self.assertEqual(decision.arguments_dict()["old_string"], "return text.strip()")

    def test_qwen_flattened_tool_arguments_are_nested_without_rewriting_values(self) -> None:
        response = json.dumps(
            {
                "protocol_version": "1",
                "thought_summary": "edit",
                "decision": {
                    "kind": "edit_file",
                    "path": "src/tiny_parser.py",
                    "old_string": "return text.strip()",
                    "new_string": "return (text or '').strip()",
                },
            }
        )
        decision = DecisionValidator.from_path(SCHEMAS).validate(self.backend(response).complete(request()))
        self.assertEqual(decision.tool, "edit_file")
        self.assertEqual(decision.arguments_dict()["path"], "src/tiny_parser.py")

    def test_final_protocol_is_preserved(self) -> None:
        response = json.dumps(
            {
                "protocol_version": "1",
                "thought_summary": "verified",
                "decision": {"kind": "final", "answer": "Fixed and tested."},
            }
        )
        decision = DecisionValidator.from_path(SCHEMAS).validate(self.backend(response).complete(request()))
        self.assertIsInstance(decision, FinalDecision)
        self.assertEqual(decision.answer, "Fixed and tested.")

    def test_non_json_is_left_for_strict_validator(self) -> None:
        response = "I need to inspect the file first."
        self.assertEqual(self.backend(response).complete(request()), response)


if __name__ == "__main__":
    unittest.main()
