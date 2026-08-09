from io import BytesIO
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from localcode.compatibility import (
    ChatResult,
    OllamaClient,
    arguments_match_schema,
    schema_map,
    score_prompt,
)


class FakeResponse:
    def __init__(self, body: bytes) -> None:
        self.stream = BytesIO(body)

    def __enter__(self):
        return self

    def __exit__(self, *args: object) -> None:
        self.stream.close()

    def __iter__(self):
        return iter(self.stream)

    def read(self, size: int = -1) -> bytes:
        return self.stream.read(size)


def fake_urlopen(request, timeout: float) -> FakeResponse:
    del timeout
    if request.full_url.endswith("/api/ps"):
        payload = {"models": [{"name": "fake:latest", "size": 1234, "size_vram": 1200}]}
        return FakeResponse(json.dumps(payload).encode())
    if request.full_url.endswith("/api/chat"):
        fake_urlopen.received.append(json.loads(request.data))
        chunks = [
            {
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [{"function": {"name": "read_file", "arguments": {"path": "src/a.py"}}}],
                },
                "done": False,
            },
            {
                "message": {"role": "assistant", "content": ""},
                "done": True,
                "prompt_eval_count": 100,
                "prompt_eval_duration": 2_000_000_000,
                "eval_count": 20,
                "eval_duration": 1_000_000_000,
                "load_duration": 3_000_000_000,
                "total_duration": 6_000_000_000,
            },
        ]
        return FakeResponse(b"".join(json.dumps(chunk).encode() + b"\n" for chunk in chunks))
    raise AssertionError(f"unexpected fake URL: {request.full_url}")


fake_urlopen.received = []


def result_with(*, content: str = "", calls: tuple[dict, ...] = ()) -> ChatResult:
    return ChatResult(
        content=content,
        thinking="",
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


class CompatibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        fake_urlopen.received.clear()
        cls.client = OllamaClient("http://127.0.0.1:11434")
        document = json.loads(Path("benchmarks/model_compatibility/tool_schemas.json").read_text())
        cls.tools = schema_map(document)

    def test_client_is_loopback_only(self) -> None:
        with self.assertRaisesRegex(ValueError, "loopback"):
            OllamaClient("https://example.com")

    @patch("localcode.compatibility.urlopen", side_effect=fake_urlopen)
    def test_fake_server_stream_and_metrics(self, _urlopen) -> None:
        payload = {"model": "fake:latest", "messages": [{"role": "user", "content": "read"}], "stream": True}

        result = self.client.stream_chat(payload)

        self.assertEqual(result.tool_calls[0]["function"]["name"], "read_file")
        self.assertEqual(result.output_tokens_per_second, 20.0)
        self.assertEqual(result.prompt_tokens_per_second, 50.0)
        self.assertGreaterEqual(result.time_to_first_output_seconds, 0)
        self.assertEqual(fake_urlopen.received[-1], payload)
        self.assertEqual(self.client.running_models()[0]["size"], 1234)

    def test_schema_validation_rejects_unknown_and_wrong_typed_arguments(self) -> None:
        read_schema = self.tools["read_file"]

        self.assertTrue(arguments_match_schema({"path": "src/a.py", "start_line": 1}, read_schema))
        self.assertFalse(arguments_match_schema({"path": "src/a.py", "surprise": True}, read_schema))
        self.assertFalse(arguments_match_schema({"path": "src/a.py", "start_line": "1"}, read_schema))

    def test_scores_exact_tool_policy_and_reasoning_decisions(self) -> None:
        tool_prompt = {
            "id": "tool",
            "category": "tool_selection",
            "expected": {"kind": "tool", "name": "read_file", "arguments": {"path": "src/a.py"}},
        }
        call = {"function": {"name": "read_file", "arguments": {"path": "src/a.py"}}}
        tool_score = score_prompt(tool_prompt, result_with(calls=(call,)), self.tools)
        self.assertTrue(tool_score["schema_valid"])
        self.assertTrue(tool_score["decision_correct"])

        policy_prompt = {
            "id": "safe",
            "category": "policy_judgment",
            "expected": {"kind": "no_tool", "must_mention_any": ["outside", "cannot"]},
        }
        self.assertTrue(score_prompt(policy_prompt, result_with(content="That is outside the repository."), self.tools)["decision_correct"])

        reasoning_prompt = {
            "id": "reason",
            "category": "code_reasoning",
            "expected": {"kind": "answer", "exact": "B"},
        }
        self.assertTrue(score_prompt(reasoning_prompt, result_with(content="B"), self.tools)["reasoning_correct"])


if __name__ == "__main__":
    unittest.main()
