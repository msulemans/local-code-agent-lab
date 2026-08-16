from __future__ import annotations

import json
from pathlib import Path
import unittest

from localcode.actions import ActionValidationError
from localcode.backends.ollama import BackendError, SCHEMA_VALIDITY_RULES
from localcode.backends.ollama_loop import LOOP_SYSTEM_PROMPT, REVIEW_SYSTEM_PROMPT, OllamaLoopBackend
from localcode.compatibility import ChatResult, CompatibilityError
from localcode.decisions import DecisionValidator, FinalDecision
from localcode.loop import AgentLoop, CompletionRequirements, LoopBudgets, LoopRequest, TerminationReason
from localcode.tools import ToolResult


SCHEMAS = Path("benchmarks/micro_agent/tool_schemas.json")
NOW = "2026-08-12T16:00:00+10:00"


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


def native_call(name: str, arguments: dict) -> dict:
    return {"function": {"name": name, "arguments": arguments}}


class FakeClient:
    def __init__(self, results: list[ChatResult]) -> None:
        self.results = list(results)
        self.payloads: list[dict] = []

    def stream_chat(self, payload: dict) -> ChatResult:
        self.payloads.append(payload)
        return self.results.pop(0)


class FailingClient:
    def stream_chat(self, payload: dict) -> ChatResult:
        raise CompatibilityError("local transport failed")


class FakeRegistry:
    tool_names = ("apply_patch", "edit_file", "git_diff", "list_files", "read_file", "run_tests", "search_code", "write_file")

    def __init__(self) -> None:
        self.executed: list[str] = []

    def execute(self, action) -> ToolResult:
        self.executed.append(action.tool)
        if action.tool == "run_tests":
            return ToolResult(content="OK", metadata=(("exit_code", 0), ("sandboxed", True)))
        return ToolResult(content=action.tool)


class OllamaLoopBackendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.document = json.loads(SCHEMAS.read_text(encoding="utf-8"))
        cls.tools = tuple(sorted(tool["function"]["name"] for tool in cls.document["tools"]))
        cls.validator = DecisionValidator.from_path(SCHEMAS)

    def request(self, *, tools: tuple[str, ...] | None = None) -> LoopRequest:
        return LoopRequest(
            issue="Parser crashes.",
            context='{"issue":"Parser crashes.","history":[],"truncated":false}',
            allowed_tools=self.tools if tools is None else tools,
            turn_index=0,
            budgets_remaining=(("turns", 3),),
        )

    def test_loop_system_prompt_carries_schema_validity_rules(self) -> None:
        self.assertIn(SCHEMA_VALIDITY_RULES, LOOP_SYSTEM_PROMPT)
        self.assertIn("Never pass zero", LOOP_SYSTEM_PROMPT)
        self.assertIn("python-unittest", LOOP_SYSTEM_PROMPT)

    def test_review_system_prompt_carries_rules_and_can_replace_the_loop_prompt(self) -> None:
        self.assertIn(SCHEMA_VALIDITY_RULES, REVIEW_SYSTEM_PROMPT)
        self.assertIn("review component", REVIEW_SYSTEM_PROMPT)

        client = FakeClient([chat_result(content="Done")])
        backend = OllamaLoopBackend(
            model="fake:latest",
            tool_document=self.document,
            client=client,
            system_prompt="REVIEW ONLY",
        )

        backend.complete(self.request())

        self.assertEqual(client.payloads[0]["messages"][0]["content"], "REVIEW ONLY")

    def test_invalid_system_prompt_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "system_prompt"):
            OllamaLoopBackend(model="fake:latest", tool_document=self.document, system_prompt="  ")

    def test_native_tool_call_becomes_exact_loop_decision(self) -> None:
        client = FakeClient(
            [chat_result(calls=(native_call("search_code", {"query": "parse_value"}),))]
        )
        backend = OllamaLoopBackend(model="fake:latest", tool_document=self.document, client=client)

        decision = self.validator.validate(backend.complete(self.request()))

        self.assertEqual(decision.tool, "search_code")
        self.assertEqual(decision.arguments_dict()["query"], "parse_value")

    def test_native_tool_call_discards_transport_index(self) -> None:
        client = FakeClient(
            [
                chat_result(
                    calls=(
                        {
                            "type": "function",
                            "id": "call-test",
                            "function": {
                                "name": "search_code",
                                "arguments": {"query": "parse_value"},
                                "index": 0,
                            },
                        },
                    )
                )
            ]
        )
        backend = OllamaLoopBackend(model="fake:latest", tool_document=self.document, client=client)
        decision = self.validator.validate(backend.complete(self.request()))
        self.assertEqual(decision.tool, "search_code")

    def test_plain_content_becomes_bounded_final_decision(self) -> None:
        client = FakeClient([chat_result(content="The guarded patch is tested.")])
        backend = OllamaLoopBackend(model="fake:latest", tool_document=self.document, client=client)

        decision = self.validator.validate(backend.complete(self.request()))

        self.assertIsInstance(decision, FinalDecision)
        self.assertEqual(decision.answer, "The guarded patch is tested.")

    def test_content_form_json_tool_call_becomes_tool_decision(self) -> None:
        # Real Qwen checkpoints can emit a tool call as plain JSON text in
        # content instead of a native tool_calls entry (m004c stream evidence).
        emitted = json.dumps(
            {"name": "search_code", "arguments": {"query": "parse_value"}},
            sort_keys=True,
        )
        client = FakeClient([chat_result(content=emitted)])
        backend = OllamaLoopBackend(model="fake:latest", tool_document=self.document, client=client)

        decision = self.validator.validate(backend.complete(self.request()))

        self.assertEqual(decision.tool, "search_code")
        self.assertEqual(decision.arguments_dict()["query"], "parse_value")

    def test_content_form_json_wrapped_in_markdown_fence_becomes_tool_decision(self) -> None:
        # m031 showed the 14B wrapping its content-form tool call in a markdown
        # code fence; the fence is presentation, not intent.
        emitted = "```json\n" + json.dumps(
            {"name": "read_file", "arguments": {"path": "src/flask/blueprints.py", "start_line": 117}},
            sort_keys=True,
        ) + "\n```"
        client = FakeClient([chat_result(content=emitted)])
        backend = OllamaLoopBackend(model="fake:latest", tool_document=self.document, client=client)

        decision = self.validator.validate(backend.complete(self.request()))

        self.assertEqual(decision.tool, "read_file")
        self.assertEqual(decision.arguments_dict()["path"], "src/flask/blueprints.py")

    def test_content_form_tool_alias_key_becomes_tool_decision(self) -> None:
        # m032 showed the 14B naming the tool field `tool` instead of `name`;
        # that is a transport alias, not a different intent.
        emitted = json.dumps(
            {"tool": "git_diff", "arguments": {"path": "src/flask/app.py", "staged": False}},
            sort_keys=True,
        )
        client = FakeClient([chat_result(content=emitted)])
        backend = OllamaLoopBackend(model="fake:latest", tool_document=self.document, client=client)

        decision = self.validator.validate(backend.complete(self.request()))

        self.assertEqual(decision.tool, "git_diff")
        self.assertEqual(decision.arguments_dict()["path"], "src/flask/app.py")

    def test_content_form_echoed_history_is_not_repaired_into_a_tool_call(self) -> None:
        # m032 turn 5 echoed an entire history observation (extra keys) as
        # content; that must stay a final decision, never a tool call.
        emitted = json.dumps(
            {
                "arguments": {"max_bytes": 1024, "path": "src/flask/app.py", "staged": False},
                "controller_guidance": "Review complete.",
                "metadata": {"file_count": 0},
                "observation": "",
                "tool": "git_diff",
            },
            sort_keys=True,
        )
        client = FakeClient([chat_result(content=emitted)])
        backend = OllamaLoopBackend(model="fake:latest", tool_document=self.document, client=client)

        decision = self.validator.validate(backend.complete(self.request()))

        self.assertIsInstance(decision, FinalDecision)

    def test_content_form_json_still_passes_strict_argument_schema(self) -> None:
        # Translation must not weaken validation: an invalid argument value is
        # rejected exactly as it would be for a native tool call.
        emitted = json.dumps(
            {"name": "search_code", "arguments": {"query": "parse_value", "max_results": "many"}},
            sort_keys=True,
        )
        client = FakeClient([chat_result(content=emitted)])
        backend = OllamaLoopBackend(model="fake:latest", tool_document=self.document, client=client)

        with self.assertRaises(ActionValidationError) as raised:
            self.validator.validate(backend.complete(self.request()))
        self.assertEqual(raised.exception.code, "invalid_arguments")

    def test_non_tool_json_content_is_not_repaired_into_a_tool_call(self) -> None:
        # Narration or structured answers must stay final decisions.
        emitted = json.dumps({"status": "complete", "summary": "all tests pass"}, sort_keys=True)
        client = FakeClient([chat_result(content=emitted)])
        backend = OllamaLoopBackend(model="fake:latest", tool_document=self.document, client=client)

        decision = self.validator.validate(backend.complete(self.request()))

        self.assertIsInstance(decision, FinalDecision)

    def test_content_form_sequence_crosses_patch_test_and_final_loop(self) -> None:
        client = FakeClient(
            [
                chat_result(content=json.dumps({"name": "apply_patch", "arguments": {"patch": "patch-one"}}, sort_keys=True)),
                chat_result(content=json.dumps({"name": "run_tests", "arguments": {"command_name": "python-unittest"}}, sort_keys=True)),
                chat_result(content="Fixed and tested."),
            ]
        )
        backend = OllamaLoopBackend(model="fake:latest", tool_document=self.document, client=client)
        registry = FakeRegistry()

        result = AgentLoop(
            backend,
            self.validator,
            registry,
            LoopBudgets(max_turns=3, max_tool_calls=2),
            clock=lambda: NOW,
            monotonic=lambda: 0.0,
            completion_requirements=CompletionRequirements(
                require_patch=True,
                require_passing_tests=True,
            ),
        ).run(run_id="fake-content-form-loop", issue="Fix parser")

        self.assertEqual(result.termination_reason, TerminationReason.FINAL_ANSWER)
        self.assertEqual(result.final_answer, "Fixed and tested.")
        self.assertEqual(registry.executed, ["apply_patch", "run_tests"])
        self.assertEqual(len(client.payloads), 3)

    def test_multiple_malformed_and_unknown_calls_are_not_repaired(self) -> None:
        results = [
            chat_result(calls=(native_call("list_files", {}), native_call("git_diff", {}))),
            chat_result(calls=({"function": {"name": "list_files"}},)),
            chat_result(calls=(native_call("terminal", {"command": "pwd"}),)),
        ]
        client = FakeClient(results)
        backend = OllamaLoopBackend(model="fake:latest", tool_document=self.document, client=client)

        with self.assertRaises(ActionValidationError):
            self.validator.validate(backend.complete(self.request()))
        with self.assertRaises(ActionValidationError):
            self.validator.validate(backend.complete(self.request()))
        with self.assertRaises(ActionValidationError) as raised:
            self.validator.validate(backend.complete(self.request()))
        self.assertEqual(raised.exception.code, "unknown_tool")

    def test_request_is_bounded_deterministic_and_unloads_each_smoke_turn(self) -> None:
        client = FakeClient([chat_result(content="Done")])
        backend = OllamaLoopBackend(model="fake:latest", tool_document=self.document, client=client)

        backend.complete(self.request())

        payload = client.payloads[0]
        self.assertEqual(payload["messages"][-1]["content"], self.request().context)
        self.assertEqual(
            payload["options"],
            {"temperature": 0, "seed": 42, "num_predict": 512, "num_ctx": 4096},
        )
        self.assertEqual(payload["keep_alive"], 0)
        self.assertFalse(payload["think"])

    def test_loop_backend_honors_a_resident_keep_alive(self) -> None:
        client = FakeClient([chat_result(content="Done")])
        backend = OllamaLoopBackend(
            model="fake:latest",
            tool_document=self.document,
            client=client,
            keep_alive=300,
        )

        backend.complete(self.request())

        self.assertEqual(client.payloads[0]["keep_alive"], 300)

    def test_gpt_oss_reasoning_mode_and_generated_tokens_are_recorded(self) -> None:
        client = FakeClient([chat_result(content="Done"), chat_result(content="Done again")])
        backend = OllamaLoopBackend(
            model="gpt-oss:20b",
            tool_document=self.document,
            client=client,
            think="medium",
        )

        backend.complete(self.request())
        backend.complete(self.request())

        self.assertEqual(client.payloads[0]["think"], "medium")
        self.assertEqual(backend.generated_tokens, 2)

    def test_invalid_reasoning_mode_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "think"):
            OllamaLoopBackend(
                model="fake:latest",
                tool_document=self.document,
                think="maximum",
            )

    def test_surface_mismatch_and_transport_failure_are_bounded(self) -> None:
        client = FakeClient([chat_result()])
        backend = OllamaLoopBackend(model="fake:latest", tool_document=self.document, client=client)
        with self.assertRaises(BackendError):
            backend.complete(self.request(tools=("read_file",)))
        self.assertEqual(client.payloads, [])

        failing = OllamaLoopBackend(
            model="fake:latest",
            tool_document=self.document,
            client=FailingClient(),
        )
        with self.assertRaisesRegex(BackendError, "local transport failed"):
            failing.complete(self.request())

    def test_fake_ollama_sequence_crosses_patch_test_and_final_loop(self) -> None:
        client = FakeClient(
            [
                chat_result(calls=(native_call("apply_patch", {"patch": "patch-one"}),)),
                chat_result(calls=(native_call("run_tests", {"command_name": "python-unittest"}),)),
                chat_result(content="Fixed and tested."),
            ]
        )
        backend = OllamaLoopBackend(model="fake:latest", tool_document=self.document, client=client)
        registry = FakeRegistry()

        result = AgentLoop(
            backend,
            self.validator,
            registry,
            LoopBudgets(max_turns=3, max_tool_calls=2),
            clock=lambda: NOW,
            monotonic=lambda: 0.0,
            completion_requirements=CompletionRequirements(
                require_patch=True,
                require_passing_tests=True,
            ),
        ).run(run_id="fake-ollama-loop", issue="Fix parser")

        self.assertEqual(result.termination_reason, TerminationReason.FINAL_ANSWER)
        self.assertEqual(result.final_answer, "Fixed and tested.")
        self.assertEqual(registry.executed, ["apply_patch", "run_tests"])
        self.assertEqual(len(client.payloads), 3)
        self.assertIn("patch-one", client.payloads[1]["messages"][-1]["content"])


if __name__ == "__main__":
    unittest.main()
