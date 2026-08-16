from __future__ import annotations

import json
from pathlib import Path
import unittest

from localcode.controller import ModelBackendError
from localcode.decisions import DecisionValidator
from localcode.events import EventType
from localcode.loop import LoopBudgets, ReadOnlyAgentLoop, TerminationReason
from localcode.registry import ToolRegistry


ROOT = Path("tests/fixtures/micro_repos/parser_none")
SCHEMAS = Path("benchmarks/model_compatibility/tool_schemas.json")
NOW = "2026-08-10T12:00:00+10:00"


def tool(tool_name: str, arguments: dict[str, object]) -> str:
    return json.dumps(
        {
            "protocol_version": "1",
            "thought_summary": "Inspect one useful piece of evidence.",
            "decision": {"kind": "tool", "tool": tool_name, "arguments": arguments},
        }
    )


def final(answer: str = "The parser is defined in src/tiny_parser.py.") -> str:
    return json.dumps(
        {
            "protocol_version": "1",
            "thought_summary": "Enough evidence is available.",
            "decision": {"kind": "final", "answer": answer},
        }
    )


class FakeBackend:
    def __init__(self, responses: list[str | Exception]) -> None:
        self.responses = list(responses)
        self.requests = []

    def complete(self, request):
        self.requests.append(request)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class SequenceClock:
    def __init__(self, values: list[float]) -> None:
        self.values = list(values)
        self.last = values[-1]

    def __call__(self) -> float:
        if self.values:
            self.last = self.values.pop(0)
        return self.last


def agent(backend: FakeBackend, budgets: LoopBudgets, monotonic=None) -> ReadOnlyAgentLoop:
    return ReadOnlyAgentLoop(
        backend,
        DecisionValidator.from_path(SCHEMAS),
        ToolRegistry(ROOT),
        budgets,
        clock=lambda: NOW,
        monotonic=monotonic if monotonic is not None else lambda: 0.0,
    )


class ReadOnlyAgentLoopTests(unittest.TestCase):
    def test_tool_observation_is_context_for_a_final_answer(self) -> None:
        backend = FakeBackend(
            [tool("search_code", {"query": "def parse_value"}), final()]
        )

        result = agent(backend, LoopBudgets()).run(run_id="loop-success", issue="Find parser")

        self.assertEqual(result.termination_reason, TerminationReason.FINAL_ANSWER)
        self.assertEqual(result.tool_calls_used, 1)
        self.assertEqual(result.turns_used, 2)
        self.assertIn("src/tiny_parser.py:1", backend.requests[1].context)
        self.assertEqual(result.events[-1].event_type, EventType.FINAL_ANSWER)

    def test_invalid_action_exhaustion_is_explicit(self) -> None:
        backend = FakeBackend(["not json", "still not json"])

        result = agent(
            backend,
            LoopBudgets(max_invalid_actions=2),
        ).run(run_id="loop-invalid", issue="Find parser")

        self.assertEqual(result.termination_reason, TerminationReason.INVALID_ACTION_EXHAUSTION)
        self.assertEqual(result.invalid_actions_used, 2)
        self.assertEqual(len(backend.requests), 2)

    def test_tool_exhaustion_stops_before_an_extra_tool_call(self) -> None:
        backend = FakeBackend(
            [
                tool("search_code", {"query": "parse_value"}),
                tool("read_file", {"path": "src/tiny_parser.py"}),
            ]
        )

        result = agent(
            backend,
            LoopBudgets(max_tool_calls=1),
        ).run(run_id="loop-tools", issue="Find parser")

        self.assertEqual(result.termination_reason, TerminationReason.TOOL_EXHAUSTION)
        self.assertEqual(result.tool_calls_used, 1)
        self.assertEqual(len(result.observations), 1)

    def test_repeated_action_is_blocked_before_second_execution(self) -> None:
        same = tool("search_code", {"query": "parse_value"})
        backend = FakeBackend([same, same])

        result = agent(backend, LoopBudgets()).run(
            run_id="loop-repeat",
            issue="Find parser",
        )

        self.assertEqual(result.termination_reason, TerminationReason.REPEATED_ACTION)
        self.assertEqual(result.tool_calls_used, 1)
        self.assertIn(EventType.REPEATED_ACTION, tuple(event.event_type for event in result.events))

    def test_backend_error_is_bounded(self) -> None:
        backend = FakeBackend([ModelBackendError("model unavailable")])

        result = agent(backend, LoopBudgets()).run(
            run_id="loop-backend",
            issue="Find parser",
        )

        self.assertEqual(result.termination_reason, TerminationReason.BACKEND_ERROR)
        self.assertEqual(result.observations[-1].metadata_dict()["code"], "backend_error")

    def test_wall_clock_timeout_stops_after_slow_backend_response(self) -> None:
        backend = FakeBackend([tool("search_code", {"query": "parse_value"})])
        monotonic = SequenceClock([0.0, 0.0, 2.0])

        result = agent(
            backend,
            LoopBudgets(max_wall_seconds=1.0),
            monotonic=monotonic,
        ).run(run_id="loop-timeout", issue="Find parser")

        self.assertEqual(result.termination_reason, TerminationReason.WALL_CLOCK_TIMEOUT)
        self.assertEqual(result.tool_calls_used, 0)
        self.assertEqual(len(backend.requests), 1)

    def test_turn_exhaustion_stops_without_an_unbounded_retry(self) -> None:
        backend = FakeBackend(["bad decision"])

        result = agent(
            backend,
            LoopBudgets(max_turns=1, max_invalid_actions=2),
        ).run(run_id="loop-turns", issue="Find parser")

        self.assertEqual(result.termination_reason, TerminationReason.TURN_EXHAUSTION)
        self.assertEqual(result.turns_used, 1)
        self.assertEqual(len(backend.requests), 1)

    def test_context_and_event_budgets_are_bounded_and_visible(self) -> None:
        backend = FakeBackend(["bad", final("done")])
        budgets = LoopBudgets(max_turns=2, max_invalid_actions=2, max_context_chars=512)

        result = agent(backend, budgets).run(run_id="loop-context", issue="x" * 2_000)

        self.assertEqual(result.termination_reason, TerminationReason.FINAL_ANSWER)
        self.assertLessEqual(len(backend.requests[0].context), 512)
        self.assertIn('"truncated":true', backend.requests[0].context)
        for event in result.events:
            self.assertEqual(
                tuple(name for name, _ in event.budgets_remaining),
                ("invalid_actions", "tool_calls", "turns"),
            )


if __name__ == "__main__":
    unittest.main()
