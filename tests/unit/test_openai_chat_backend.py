from __future__ import annotations

import json
import os
from pathlib import Path
import unittest

from localcode.backends.openai_chat import OpenAIChatClient, OpenAIChatLoopBackend
from localcode.decisions import DecisionValidator, FinalDecision
from localcode.loop import LoopRequest


SCHEMAS = Path("benchmarks/micro_agent/tool_schemas.json")


class FakeChatClient:
    def __init__(self, response):
        self.response = response
        self.requests = []

    def create_chat_completion(self, payload):
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


def chat_response(*, tool_calls=None, content=None, usage=None):
    message = {}
    if content is not None:
        message["content"] = content
    if tool_calls is not None:
        message["tool_calls"] = tool_calls
    return {
        "choices": [{"message": message}],
        "usage": usage or {"prompt_tokens": 101, "completion_tokens": 17},
    }


class OpenAIChatLoopBackendTests(unittest.TestCase):
    def setUp(self) -> None:
        self.document = json.loads(SCHEMAS.read_text(encoding="utf-8"))
        self.validator = DecisionValidator.from_tool_document(self.document)

    def test_function_call_crosses_the_existing_protocol_validator(self) -> None:
        client = FakeChatClient(chat_response(
            tool_calls=[{
                "id": "call-1",
                "type": "function",
                "function": {"name": "search_code", "arguments": '{"query":"parse"}'},
            }],
        ))
        backend = OpenAIChatLoopBackend(
            model="hosted/coder", tool_document=self.document, client=client,
            allow_tool_subsets=True,
        )

        decision = self.validator.validate(backend.complete(request("search_code")))

        self.assertEqual(decision.tool, "search_code")
        self.assertEqual(decision.arguments_dict()["query"], "parse")
        self.assertEqual(backend.generated_tokens, 17)
        self.assertEqual(backend.input_tokens, 101)
        sent = client.requests[0]
        self.assertEqual([tool["function"]["name"] for tool in sent["tools"]], ["search_code"])
        self.assertEqual(sent["tool_choice"], "auto")
        self.assertFalse(sent["parallel_tool_calls"])
        self.assertFalse(sent["stream"])
        self.assertNotIn("OPENAI_API_KEY", json.dumps(sent))

    def test_plain_output_becomes_a_final_decision(self) -> None:
        client = FakeChatClient(chat_response(content="Patch and tests are complete."))
        backend = OpenAIChatLoopBackend(
            model="hosted/coder", tool_document=self.document, client=client,
        )

        decision = self.validator.validate(backend.complete(request(*backend.tool_names)))

        self.assertIsInstance(decision, FinalDecision)
        self.assertEqual(decision.answer, "Patch and tests are complete.")

    def test_multiple_parallel_calls_use_the_primary_well_formed_call(self) -> None:
        client = FakeChatClient(chat_response(tool_calls=[
            {"id": "call-1", "type": "function", "function": {"name": "search_code", "arguments": '{"query":"a"}'}},
            {"id": "call-2", "type": "function", "function": {"name": "read_file", "arguments": '{"path":"a.py"}'}},
        ]))
        backend = OpenAIChatLoopBackend(
            model="hosted/coder", tool_document=self.document, client=client,
        )

        decision = self.validator.validate(backend.complete(request(*backend.tool_names)))

        # Providers such as DeepSeek parallelize tool calls; the transport
        # maps to the controller's one-decision-per-turn protocol using the
        # first well-formed call (D-055).
        self.assertEqual(decision.tool, "search_code")
        self.assertEqual(decision.arguments_dict()["query"], "a")

    def test_parallel_calls_skip_malformed_leading_entries(self) -> None:
        client = FakeChatClient(chat_response(tool_calls=[
            {"id": "call-1", "type": "function", "function": {"name": "search_code", "arguments": "not-json"}},
            {"id": "call-2", "type": "function", "function": {"name": "read_file", "arguments": '{"path":"a.py"}'}},
        ]))
        backend = OpenAIChatLoopBackend(
            model="hosted/coder", tool_document=self.document, client=client,
        )

        decision = self.validator.validate(backend.complete(request(*backend.tool_names)))

        self.assertEqual(decision.tool, "read_file")
        self.assertEqual(decision.arguments_dict()["path"], "a.py")

    def test_unknown_tool_subset_stops_before_network(self) -> None:
        client = FakeChatClient(chat_response(content=""))
        backend = OpenAIChatLoopBackend(
            model="hosted/coder", tool_document=self.document, client=client,
            allow_tool_subsets=True,
        )

        with self.assertRaisesRegex(Exception, "unknown tool surface"):
            backend.complete(request("terminal"))
        self.assertEqual(client.requests, [])

    def test_arguments_with_extra_whitespace_are_accepted(self) -> None:
        client = FakeChatClient(chat_response(
            tool_calls=[{
                "id": "call-1",
                "type": "function",
                "function": {"name": "read_file", "arguments": '{\n  "path": "src/a.py"\n}'},
            }],
        ))
        backend = OpenAIChatLoopBackend(
            model="hosted/coder", tool_document=self.document, client=client,
            allow_tool_subsets=True,
        )

        decision = self.validator.validate(backend.complete(request("read_file")))

        self.assertEqual(decision.tool, "read_file")
        self.assertEqual(decision.arguments_dict()["path"], "src/a.py")

    def test_cache_usage_is_recorded(self) -> None:
        client = FakeChatClient(chat_response(
            tool_calls=[{
                "id": "call-1", "type": "function",
                "function": {"name": "read_file", "arguments": '{"path":"a.py"}'},
            }],
            usage={"prompt_tokens": 4000, "completion_tokens": 100,
                   "prompt_cache_hit_tokens": 3800, "prompt_cache_miss_tokens": 200},
        ))
        backend = OpenAIChatLoopBackend(
            model="hosted/coder", tool_document=self.document, client=client,
            allow_tool_subsets=True,
        )

        self.validator.validate(backend.complete(request("read_file")))

        self.assertEqual(backend.input_tokens, 4000)
        self.assertEqual(backend.generated_tokens, 100)
        self.assertEqual(backend.cache_hit_tokens, 3800)
        self.assertEqual(backend.cache_miss_tokens, 200)

    def test_cache_usage_from_prompt_tokens_details(self) -> None:
        client = FakeChatClient(chat_response(
            tool_calls=[{
                "id": "call-1", "type": "function",
                "function": {"name": "read_file", "arguments": '{"path":"a.py"}'},
            }],
            usage={"prompt_tokens": 4000, "completion_tokens": 100,
                   "prompt_tokens_details": {"cached_tokens": 3600}},
        ))
        backend = OpenAIChatLoopBackend(
            model="hosted/coder", tool_document=self.document, client=client,
            allow_tool_subsets=True,
        )

        self.validator.validate(backend.complete(request("read_file")))

        self.assertEqual(backend.cache_hit_tokens, 3600)

    def test_api_key_env_name_is_used_by_default(self) -> None:
        os.environ.pop("MY_PROVIDER_KEY", None)
        try:
            with self.assertRaisesRegex(ValueError, "MY_PROVIDER_KEY"):
                OpenAIChatClient(base_url="https://api.example.com/v1", api_key_env="MY_PROVIDER_KEY")
        finally:
            os.environ.pop("MY_PROVIDER_KEY", None)

    def test_api_key_env_reads_a_configured_variable(self) -> None:
        os.environ["MY_PROVIDER_KEY"] = "k"
        try:
            client = OpenAIChatClient(base_url="https://api.example.com/v1", api_key_env="MY_PROVIDER_KEY")
            self.assertIsNotNone(client)
        finally:
            os.environ.pop("MY_PROVIDER_KEY", None)


if __name__ == "__main__":
    unittest.main()
