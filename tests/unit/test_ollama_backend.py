from __future__ import annotations

import json
from pathlib import Path
import unittest

from localcode.actions import ActionValidationError, ActionValidator
from localcode.backends import BackendError, OllamaBackend
from localcode.backends.ollama import ONE_TURN_SYSTEM_PROMPT, SCHEMA_VALIDITY_RULES
from localcode.compatibility import ChatResult
from localcode.controller import OneTurnController, OneTurnRequest
from localcode.events import EventType
from localcode.registry import ToolRegistry


SCHEMAS = Path("benchmarks/model_compatibility/tool_schemas.json")


def chat_result(*, content: str = "", calls: tuple[dict, ...] = ()) -> ChatResult:
    return ChatResult(
        content=content,
        thinking="private reasoning must not cross the adapter",
        tool_calls=calls,
        prompt_eval_count=10,
        prompt_eval_duration_ns=1,
        eval_count=1,
        eval_duration_ns=1,
        load_duration_ns=1,
        total_duration_ns=1,
        time_to_first_output_seconds=0.1,
        wall_seconds=0.2,
        chunks=(),
    )


class FakeClient:
    def __init__(self, result: ChatResult) -> None:
        self.result = result
        self.payloads: list[dict] = []

    def stream_chat(self, payload: dict) -> ChatResult:
        self.payloads.append(payload)
        return self.result


def native_call(name: str, arguments: dict) -> dict:
    return {"function": {"name": name, "arguments": arguments}}


class OllamaBackendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.document = json.loads(SCHEMAS.read_text(encoding="utf-8"))
        cls.allowed_tools = ("git_diff", "list_files", "read_file", "search_code")

    def request(self, *, tools: tuple[str, ...] | None = None) -> OneTurnRequest:
        return OneTurnRequest(
            issue="Parser crashes when given None.",
            allowed_tools=self.allowed_tools if tools is None else tools,
        )

    def test_one_turn_system_prompt_carries_schema_validity_rules(self) -> None:
        self.assertIn(SCHEMA_VALIDITY_RULES, ONE_TURN_SYSTEM_PROMPT)
        self.assertIn("Never pass null", ONE_TURN_SYSTEM_PROMPT)
        self.assertIn("python-unittest", ONE_TURN_SYSTEM_PROMPT)

    def test_native_call_becomes_a_valid_protocol_envelope_without_argument_repair(self) -> None:
        client = FakeClient(chat_result(calls=(native_call("search_code", {"query": "parse", "max_results": 7}),)))
        backend = OllamaBackend(model="fake:latest", tool_document=self.document, client=client)

        payload = backend.complete(self.request())
        action = ActionValidator.from_path(SCHEMAS).validate(payload)

        self.assertEqual(action.tool, "search_code")
        self.assertEqual(action.arguments_dict()["query"], "parse")
        self.assertEqual(action.arguments_dict()["max_results"], 7)
        self.assertNotIn("private reasoning", payload)

    def test_request_is_deterministic_bounded_and_unloads_after_completion(self) -> None:
        client = FakeClient(chat_result(content="not a tool call"))
        backend = OllamaBackend(model="fake:latest", tool_document=self.document, client=client)

        self.assertEqual(backend.complete(self.request()), "not a tool call")

        sent = client.payloads[0]
        self.assertEqual(sent["model"], "fake:latest")
        self.assertEqual(sent["messages"][-1]["content"], "Parser crashes when given None.")
        self.assertEqual(sent["options"], {"temperature": 0, "seed": 42, "num_predict": 256, "num_ctx": 4096})
        self.assertEqual(sent["keep_alive"], 0)
        self.assertFalse(sent["think"])

    def test_multiple_or_malformed_native_calls_are_not_rescued(self) -> None:
        multiple = FakeClient(chat_result(calls=(native_call("list_files", {}), native_call("git_diff", {}))))
        malformed = FakeClient(chat_result(calls=({"function": {"name": "list_files"}},)))

        self.assertEqual(OllamaBackend(model="fake:latest", tool_document=self.document, client=multiple).complete(self.request()), "")
        self.assertEqual(OllamaBackend(model="fake:latest", tool_document=self.document, client=malformed).complete(self.request()), "")

    def test_unknown_native_tool_remains_visible_to_the_action_validator(self) -> None:
        client = FakeClient(chat_result(calls=(native_call("terminal", {"command": "pwd"}),)))
        payload = OllamaBackend(model="fake:latest", tool_document=self.document, client=client).complete(self.request())

        with self.assertRaises(ActionValidationError) as raised:
            ActionValidator.from_path(SCHEMAS).validate(payload)

        self.assertEqual(raised.exception.code, "unknown_tool")

    def test_tool_surface_mismatch_stops_before_inference(self) -> None:
        client = FakeClient(chat_result())
        backend = OllamaBackend(model="fake:latest", tool_document=self.document, client=client)

        with self.assertRaises(BackendError):
            backend.complete(self.request(tools=("read_file",)))

        self.assertEqual(client.payloads, [])

    def test_fake_ollama_response_crosses_the_full_one_turn_runtime(self) -> None:
        client = FakeClient(chat_result(calls=(native_call("search_code", {"query": "def parse"}),)))
        backend = OllamaBackend(model="fake:latest", tool_document=self.document, client=client)
        controller = OneTurnController(
            backend,
            ActionValidator.from_path(SCHEMAS),
            ToolRegistry("tests/fixtures/micro_repos/parser_none"),
            clock=lambda: "2026-08-09T21:00:00+10:00",
        )

        result = controller.run(run_id="fake-ollama", issue="Parser crashes when given None.")

        self.assertIn("src/tiny_parser.py:1", result.observation.content)
        self.assertEqual(
            tuple(event.event_type for event in result.events),
            (EventType.RUN_CREATED, EventType.ACTION_ACCEPTED, EventType.TOOL_RESULT),
        )
        self.assertEqual(len(client.payloads), 1)


if __name__ == "__main__":
    unittest.main()
