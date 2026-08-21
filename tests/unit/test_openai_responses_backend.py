from __future__ import annotations

import json
from pathlib import Path
import unittest

from localcode.backends.openai_responses import OpenAIResponsesLoopBackend
from localcode.decisions import DecisionValidator, FinalDecision
from localcode.loop import LoopRequest


SCHEMAS = Path("benchmarks/micro_agent/tool_schemas.json")


class FakeClient:
    def __init__(self, response):
        self.response = response
        self.requests = []

    def create_response(self, payload):
        self.requests.append(payload)
        return self.response


def request(*tools: str) -> LoopRequest:
    return LoopRequest(
        issue="Fix parser",
        context='{"issue":"Fix parser"}',
        allowed_tools=tools,
        turn_index=0,
        budgets_remaining=(("turns", 3),),
    )


class OpenAIResponsesLoopBackendTests(unittest.TestCase):
    def setUp(self) -> None:
        self.document = json.loads(SCHEMAS.read_text(encoding="utf-8"))
        self.validator = DecisionValidator.from_tool_document(self.document)

    def test_function_call_crosses_the_existing_protocol_validator(self) -> None:
        client = FakeClient({
            "output": [{"type": "function_call", "name": "search_code", "arguments": '{"query":"parse"}'}],
            "usage": {"input_tokens": 101, "output_tokens": 17},
        })
        backend = OpenAIResponsesLoopBackend(
            model="gpt-5.6-terra", tool_document=self.document, client=client,
            allow_tool_subsets=True,
        )

        decision = self.validator.validate(backend.complete(request("search_code")))

        self.assertEqual(decision.tool, "search_code")
        self.assertEqual(decision.arguments_dict()["query"], "parse")
        self.assertEqual(backend.generated_tokens, 17)
        self.assertEqual(backend.input_tokens, 101)
        sent = client.requests[0]
        self.assertEqual([tool["name"] for tool in sent["tools"]], ["search_code"])
        self.assertFalse(sent["parallel_tool_calls"])
        self.assertFalse(sent["store"])
        self.assertEqual(sent["reasoning"], {"effort": "medium"})
        self.assertNotIn("OPENAI_API_KEY", json.dumps(sent))

    def test_plain_output_becomes_a_final_decision(self) -> None:
        client = FakeClient({"output": [{"type": "message", "content": [
            {"type": "output_text", "text": "Patch and tests are complete."}
        ]}]})
        backend = OpenAIResponsesLoopBackend(
            model="gpt-5.6-terra", tool_document=self.document, client=client,
        )

        decision = self.validator.validate(backend.complete(request(*backend.tool_names)))

        self.assertIsInstance(decision, FinalDecision)
        self.assertEqual(decision.answer, "Patch and tests are complete.")

    def test_multiple_calls_are_not_silently_selected(self) -> None:
        client = FakeClient({"output": [
            {"type": "function_call", "name": "search_code", "arguments": '{"query":"a"}'},
            {"type": "function_call", "name": "read_file", "arguments": '{"path":"a.py"}'},
        ]})
        backend = OpenAIResponsesLoopBackend(
            model="gpt-5.6-terra", tool_document=self.document, client=client,
        )

        with self.assertRaisesRegex(Exception, "valid JSON"):
            self.validator.validate(backend.complete(request(*backend.tool_names)))

    def test_unknown_tool_subset_stops_before_network(self) -> None:
        client = FakeClient({"output": []})
        backend = OpenAIResponsesLoopBackend(
            model="gpt-5.6-terra", tool_document=self.document, client=client,
            allow_tool_subsets=True,
        )

        with self.assertRaisesRegex(Exception, "unknown tool surface"):
            backend.complete(request("terminal"))
        self.assertEqual(client.requests, [])

    def test_provider_reasoning_summary_is_captured_without_changing_the_decision(self) -> None:
        client = FakeClient({
            "output": [
                {
                    "type": "reasoning",
                    "summary": [
                        {"type": "summary_text", "text": "The boundary condition is off by one."},
                        {"type": "summary_text", "text": "Change > 100 to >= 100."},
                    ],
                },
                {"type": "function_call", "name": "read_file", "arguments": '{"path":"a.py"}'},
            ],
            "usage": {"input_tokens": 5, "output_tokens": 3},
        })
        backend = OpenAIResponsesLoopBackend(
            model="gpt-5.6-terra", tool_document=self.document, client=client,
            allow_tool_subsets=True,
        )

        decision = self.validator.validate(backend.complete(request("read_file")))

        self.assertEqual(decision.tool, "read_file")
        self.assertEqual(
            backend.last_reasoning,
            "The boundary condition is off by one.\nChange > 100 to >= 100.",
        )

    def test_last_reasoning_is_empty_when_provider_returns_none(self) -> None:
        client = FakeClient({"output": [{"type": "message", "content": [
            {"type": "output_text", "text": "Done."}
        ]}]})
        backend = OpenAIResponsesLoopBackend(
            model="gpt-5.6-terra", tool_document=self.document, client=client,
        )

        backend.complete(request(*backend.tool_names))

        self.assertEqual(backend.last_reasoning, "")


if __name__ == "__main__":
    unittest.main()
