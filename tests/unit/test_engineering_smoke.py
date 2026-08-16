from __future__ import annotations

import json
from pathlib import Path
import unittest

from localcode.compatibility import ChatResult, CompatibilityError
from localcode.engineering_registry import EngineeringToolRegistry
from localcode.engineering_smoke import run_engineering_smoke
from localcode.loop import LoopBudgets, TerminationReason
from localcode.preflight import SmokePreflightError
from localcode.tools import ToolResult


ROOT = Path("tests/fixtures/micro_repos/parser_none")
SCHEMAS = Path("benchmarks/micro_agent/tool_schemas.json")
NOW = "2026-08-12T18:00:00+10:00"
ZERO_SWAP = "vm.swapusage: total = 0.00M used = 0.00M free = 0.00M (encrypted)"
RETAINED_SWAP = "vm.swapusage: total = 4096.00M used = 3612.62M free = 483.38M (encrypted)"
HIGH_SWAP = "vm.swapusage: total = 3072.00M used = 2200.00M free = 872.00M (encrypted)"
MEMORY_91 = "System-wide memory free percentage: 91%"


def chat_result(*, content: str = "", calls: tuple[dict, ...] = ()) -> ChatResult:
    return ChatResult(
        content=content,
        thinking="private reasoning must not cross the boundary",
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


class FakeOllamaClient:
    def __init__(
        self,
        results: list[ChatResult] | None = None,
        *,
        running: list[dict] | None = None,
        fail_chat: bool = False,
    ) -> None:
        self.results = [] if results is None else list(results)
        self.running = [] if running is None else running
        self.fail_chat = fail_chat
        self.chat_payloads: list[dict] = []

    def running_models(self) -> list[dict]:
        return self.running

    def stream_chat(self, payload: dict) -> ChatResult:
        self.chat_payloads.append(payload)
        if self.fail_chat:
            raise CompatibilityError("fake Ollama stream failed")
        return self.results.pop(0)


class PassingTestRunner:
    def run(self, workspace, command_name: str, **arguments) -> ToolResult:
        self.workspace = workspace
        return ToolResult(
            content="Ran 2 tests\nOK\n",
            metadata=(
                ("command", command_name),
                ("exit_code", 0),
                ("sandboxed", True),
            ),
        )


def registry_factory(workspace):
    return EngineeringToolRegistry(workspace, PassingTestRunner())


def constant_host(swap: str = ZERO_SWAP, memory: str = MEMORY_91):
    def run(arguments: tuple[str, ...]) -> str:
        if arguments == ("sysctl", "vm.swapusage"):
            return swap
        if arguments == ("memory_pressure", "-Q"):
            return memory
        raise AssertionError(f"unexpected host command: {arguments}")

    return run


class EngineeringSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.document = json.loads(SCHEMAS.read_text(encoding="utf-8"))
        cls.issue = (ROOT / "ISSUE.md").read_text(encoding="utf-8")

    def run_smoke(self, client, **overrides):
        arguments = {
            "run_id": "engineering-smoke-v1",
            "issue": self.issue,
            "model": "qwen3.5:9b-q4_K_M",
            "fixture_root": ROOT,
            "expected_changed_paths": ("src/tiny_parser.py",),
            "tool_document": self.document,
            "clock": lambda: NOW,
            "monotonic": lambda: 0.0,
            "client": client,
            "command_runner": constant_host(),
            "registry_factory": registry_factory,
            "budgets": LoopBudgets(max_turns=5, max_tool_calls=4, max_wall_seconds=60),
        }
        arguments.update(overrides)
        return run_engineering_smoke(**arguments)

    def test_clean_fake_ollama_repairs_disposable_copy_and_preserves_diff(self) -> None:
        patch = (
            "diff --git a/src/tiny_parser.py b/src/tiny_parser.py\n"
            "--- a/src/tiny_parser.py\n"
            "+++ b/src/tiny_parser.py\n"
            "@@ -1,2 +1,4 @@\n"
            " def parse_value(text: str | None) -> str:\n"
            "+    if text is None:\n"
            "+        return \"\"\n"
            "     return text.strip()\n"
        )
        client = FakeOllamaClient(
            [
                chat_result(calls=(native_call("search_code", {"query": "parse_value"}),)),
                chat_result(calls=(native_call("read_file", {"path": "src/tiny_parser.py"}),)),
                chat_result(calls=(native_call("apply_patch", {"patch": patch}),)),
                chat_result(
                    calls=(native_call("run_tests", {"command_name": "python-unittest"}),)
                ),
                chat_result(content="Handled None and verified both parser tests."),
            ]
        )
        original = (ROOT / "src/tiny_parser.py").read_text(encoding="utf-8")

        smoke = self.run_smoke(client)

        self.assertTrue(smoke.solved)
        self.assertEqual(smoke.context_mode, "simple")
        self.assertEqual(smoke.result.termination_reason, TerminationReason.FINAL_ANSWER)
        self.assertEqual(smoke.changed_paths, ("src/tiny_parser.py",))
        self.assertEqual(smoke.test_exit_codes, (0,))
        self.assertGreater(smoke.first_context_chars, 0)
        self.assertEqual(smoke.first_selected_paths, ())
        self.assertIn("+    if text is None:", smoke.diff)
        self.assertTrue(smoke.source_unchanged)
        self.assertEqual((ROOT / "src/tiny_parser.py").read_text(encoding="utf-8"), original)
        self.assertEqual(len(client.chat_payloads), 5)
        self.assertEqual(len(smoke.resource_snapshots), 10)

    def test_retrieval_context_mode_is_forwarded_to_the_real_model_payload(self) -> None:
        patch = (
            "diff --git a/src/tiny_parser.py b/src/tiny_parser.py\n"
            "--- a/src/tiny_parser.py\n"
            "+++ b/src/tiny_parser.py\n"
            "@@ -1,2 +1,4 @@\n"
            " def parse_value(text: str | None) -> str:\n"
            "+    if text is None:\n"
            "+        return \"\"\n"
            "     return text.strip()\n"
        )
        client = FakeOllamaClient(
            [
                chat_result(calls=(native_call("search_code", {"query": "parse_value"}),)),
                chat_result(calls=(native_call("read_file", {"path": "src/tiny_parser.py"}),)),
                chat_result(calls=(native_call("apply_patch", {"patch": patch}),)),
                chat_result(
                    calls=(native_call("run_tests", {"command_name": "python-unittest"}),)
                ),
                chat_result(content="Handled None and verified both parser tests."),
            ]
        )

        smoke = self.run_smoke(client, context_mode="retrieval")

        payload = json.loads(client.chat_payloads[0]["messages"][1]["content"])
        self.assertEqual(smoke.context_mode, "retrieval")
        self.assertGreater(smoke.first_context_chars, 376)
        self.assertEqual(
            smoke.first_selected_paths,
            ("tests/test_tiny_parser.py", "src/tiny_parser.py"),
        )
        self.assertEqual(payload["retrieval_treatment"]["kind"], "deterministic_v1")
        self.assertEqual(
            payload["retrieved_evidence"]["selected_paths"],
            ["tests/test_tiny_parser.py", "src/tiny_parser.py"],
        )

    def test_retained_swap_and_loaded_model_block_before_chat(self) -> None:
        cases = (
            (FakeOllamaClient(), constant_host(RETAINED_SWAP), "retained_swap"),
            (
                FakeOllamaClient(running=[{"name": "qwen3.5:9b-q4_K_M"}]),
                constant_host(),
                "model_already_loaded",
            ),
        )
        for client, host, expected_code in cases:
            with self.subTest(expected_code=expected_code):
                with self.assertRaises(SmokePreflightError) as captured:
                    self.run_smoke(client, command_runner=host)
                self.assertEqual(captured.exception.code, expected_code)
                self.assertEqual(client.chat_payloads, [])

    def test_retained_swap_can_be_explicitly_allowed_for_exploratory_run(self) -> None:
        patch = (
            "diff --git a/src/tiny_parser.py b/src/tiny_parser.py\n"
            "--- a/src/tiny_parser.py\n"
            "+++ b/src/tiny_parser.py\n"
            "@@ -1,2 +1,4 @@\n"
            " def parse_value(text: str | None) -> str:\n"
            "+    if text is None:\n"
            "+        return \"\"\n"
            "     return text.strip()\n"
        )
        client = FakeOllamaClient(
            [
                chat_result(calls=(native_call("search_code", {"query": "parse_value"}),)),
                chat_result(calls=(native_call("read_file", {"path": "src/tiny_parser.py"}),)),
                chat_result(calls=(native_call("apply_patch", {"patch": patch}),)),
                chat_result(
                    calls=(native_call("run_tests", {"command_name": "python-unittest"}),)
                ),
                chat_result(content="Handled None and verified both parser tests."),
            ]
        )

        smoke = self.run_smoke(
            client,
            command_runner=constant_host(RETAINED_SWAP),
            allow_retained_swap=True,
        )

        self.assertTrue(smoke.solved)
        self.assertEqual(smoke.baseline.swap_used_bytes, round(3612.62 * 1_024 * 1_024))
        self.assertEqual(len(client.chat_payloads), 5)

    def test_low_memory_blocks_before_chat(self) -> None:
        client = FakeOllamaClient()
        with self.assertRaises(SmokePreflightError) as captured:
            self.run_smoke(
                client,
                command_runner=constant_host(memory="System-wide memory free percentage: 4%"),
            )
        self.assertEqual(captured.exception.code, "low_memory")
        self.assertEqual(client.chat_payloads, [])

    def test_swap_growth_after_inference_stops_before_tool_execution(self) -> None:
        sysctl_calls = 0

        def growing_host(arguments: tuple[str, ...]) -> str:
            nonlocal sysctl_calls
            if arguments == ("sysctl", "vm.swapusage"):
                sysctl_calls += 1
                return HIGH_SWAP if sysctl_calls >= 3 else ZERO_SWAP
            if arguments == ("memory_pressure", "-Q"):
                return MEMORY_91
            raise AssertionError(arguments)

        client = FakeOllamaClient(
            [chat_result(calls=(native_call("search_code", {"query": "parse_value"}),))]
        )

        smoke = self.run_smoke(client, command_runner=growing_host)

        self.assertFalse(smoke.solved)
        self.assertEqual(smoke.result.termination_reason, TerminationReason.BACKEND_ERROR)
        self.assertEqual(smoke.result.tool_calls_used, 0)
        self.assertEqual(len(client.chat_payloads), 1)
        self.assertIn("swap growth", smoke.result.observations[-1].content)
        self.assertEqual(smoke.diff, "")

    def test_backend_failure_is_a_bounded_loop_result(self) -> None:
        client = FakeOllamaClient(fail_chat=True)

        smoke = self.run_smoke(client)

        self.assertFalse(smoke.solved)
        self.assertEqual(smoke.result.termination_reason, TerminationReason.BACKEND_ERROR)
        self.assertEqual(smoke.result.tool_calls_used, 0)
        self.assertEqual(len(smoke.resource_snapshots), 2)
        self.assertIn("fake Ollama stream failed", smoke.result.observations[-1].content)

    def test_invalid_context_mode_is_rejected(self) -> None:
        client = FakeOllamaClient()

        with self.assertRaisesRegex(ValueError, "context_mode"):
            self.run_smoke(client, context_mode="invalid")


if __name__ == "__main__":
    unittest.main()
