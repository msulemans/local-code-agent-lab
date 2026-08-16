from __future__ import annotations

import json
from pathlib import Path
import unittest

from localcode.compatibility import ChatResult, CompatibilityError
from localcode.controller import ModelBackendError
from localcode.events import EventType
from localcode.preflight import SmokePreflightError
from localcode.smoke import run_one_turn_smoke


ROOT = Path("tests/fixtures/micro_repos/parser_none")
SCHEMAS = Path("benchmarks/model_compatibility/tool_schemas.json")
NOW = "2026-08-09T21:00:00+10:00"
ZERO_SWAP = "vm.swapusage: total = 0.00M  used = 0.00M  free = 0.00M  (encrypted)"
RETAINED_SWAP = (
    "vm.swapusage: total = 3072.00M  used = 2213.88M "
    "free = 858.12M  (encrypted)"
)
MEMORY = "System-wide memory free percentage: 91%"


class FakeOllamaClient:
    def __init__(
        self,
        *,
        running: list[dict[str, object]] | None = None,
        fail_chat: bool = False,
    ) -> None:
        self.running = [] if running is None else running
        self.fail_chat = fail_chat
        self.chat_payloads: list[dict[str, object]] = []

    def running_models(self) -> list[dict[str, object]]:
        return self.running

    def stream_chat(self, payload: dict[str, object]) -> ChatResult:
        self.chat_payloads.append(payload)
        if self.fail_chat:
            raise CompatibilityError("fake backend failure")
        return ChatResult(
            content="Search for the parser definition.",
            thinking="private reasoning must not cross the boundary",
            tool_calls=(
                {
                    "type": "function",
                    "function": {
                        "name": "search_code",
                        "arguments": {"query": "def parse_value"},
                    },
                },
            ),
            prompt_eval_count=100,
            prompt_eval_duration_ns=1,
            eval_count=10,
            eval_duration_ns=1,
            load_duration_ns=1,
            total_duration_ns=1,
            time_to_first_output_seconds=0.1,
            wall_seconds=0.2,
            chunks=(),
        )


def command_runner(swap_output: str):
    def run(arguments: tuple[str, ...]) -> str:
        if arguments == ("sysctl", "vm.swapusage"):
            return swap_output
        if arguments == ("memory_pressure", "-Q"):
            return MEMORY
        raise AssertionError(f"unexpected command: {arguments}")

    return run


class SmokeRunTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tool_document = json.loads(SCHEMAS.read_text(encoding="utf-8"))

    def test_retained_swap_stops_before_model_inference(self) -> None:
        client = FakeOllamaClient()

        with self.assertRaises(SmokePreflightError) as captured:
            run_one_turn_smoke(
                run_id="smoke-blocked",
                issue="Parser crashes on None",
                model="qwen3.5:9b-q4_K_M",
                repository_root=ROOT,
                tool_document=self.tool_document,
                clock=lambda: NOW,
                client=client,
                command_runner=command_runner(RETAINED_SWAP),
            )

        self.assertEqual(captured.exception.code, "retained_swap")
        self.assertEqual(client.chat_payloads, [])

    def test_clean_baseline_permits_exactly_one_complete_turn(self) -> None:
        client = FakeOllamaClient()

        smoke = run_one_turn_smoke(
            run_id="smoke-clean",
            issue="Parser crashes on None",
            model="qwen3.5:9b-q4_K_M",
            repository_root=ROOT,
            tool_document=self.tool_document,
            clock=lambda: NOW,
            client=client,
            command_runner=command_runner(ZERO_SWAP),
        )

        self.assertEqual(smoke.baseline.swap_used_bytes, 0)
        self.assertEqual(len(client.chat_payloads), 1)
        self.assertIn("src/tiny_parser.py:1", smoke.result.observation.content)
        self.assertEqual(
            tuple(event.event_type for event in smoke.result.events),
            (EventType.RUN_CREATED, EventType.ACTION_ACCEPTED, EventType.TOOL_RESULT),
        )

    def test_loaded_model_stops_before_model_inference(self) -> None:
        client = FakeOllamaClient(running=[{"name": "another:model"}])

        with self.assertRaises(SmokePreflightError) as captured:
            run_one_turn_smoke(
                run_id="smoke-loaded",
                issue="Parser crashes on None",
                model="qwen3.5:9b-q4_K_M",
                repository_root=ROOT,
                tool_document=self.tool_document,
                clock=lambda: NOW,
                client=client,
                command_runner=command_runner(ZERO_SWAP),
            )

        self.assertEqual(captured.exception.code, "model_already_loaded")
        self.assertEqual(client.chat_payloads, [])

    def test_accepted_baseline_is_observed_before_backend_failure(self) -> None:
        client = FakeOllamaClient(fail_chat=True)
        observed = []

        with self.assertRaises(ModelBackendError):
            run_one_turn_smoke(
                run_id="smoke-backend-error",
                issue="Parser crashes on None",
                model="qwen3.5:9b-q4_K_M",
                repository_root=ROOT,
                tool_document=self.tool_document,
                clock=lambda: NOW,
                client=client,
                command_runner=command_runner(ZERO_SWAP),
                baseline_observer=observed.append,
            )

        self.assertEqual(len(observed), 1)
        self.assertEqual(observed[0].swap_used_bytes, 0)
        self.assertEqual(len(client.chat_payloads), 1)


if __name__ == "__main__":
    unittest.main()
