from __future__ import annotations

import json
from pathlib import Path
import unittest

from localcode.decisions import DecisionValidator
from localcode.events import Event, EventType
from localcode.loop import LoopBudgets, ReadOnlyAgentLoop, TerminationReason
from localcode.registry import ToolRegistry
from localcode.tools import ToolResult


ROOT = Path("tests/fixtures/micro_repos/parser_none")
SCHEMAS = Path("benchmarks/model_compatibility/tool_schemas.json")
NOW = "2026-08-12T12:00:00+10:00"


def tool(name: str, arguments: dict[str, object]) -> str:
    return json.dumps(
        {
            "protocol_version": "1",
            "thought_summary": "Inspect repository evidence.",
            "decision": {"kind": "tool", "tool": name, "arguments": arguments},
        }
    )


def final() -> str:
    return json.dumps(
        {
            "protocol_version": "1",
            "thought_summary": "Enough evidence is available.",
            "decision": {"kind": "final", "answer": "Found the parser."},
        }
    )


class FakeBackend:
    def __init__(self) -> None:
        self.responses = [tool("search_code", {"query": "parse_value"}), final()]

    def complete(self, request) -> str:
        return self.responses.pop(0)


class RecordingObserver:
    def __init__(self) -> None:
        self.entries: list[tuple[str, str]] = []

    def on_event(self, event: Event) -> None:
        self.entries.append(("event", event.event_type.value))

    def on_observation(self, observation: ToolResult) -> None:
        self.entries.append(("observation", observation.content))


class RaisingObserver:
    def on_event(self, event: Event) -> None:
        raise RuntimeError("renderer failed")

    def on_observation(self, observation: ToolResult) -> None:
        raise RuntimeError("renderer failed")


def loop(observer=None) -> ReadOnlyAgentLoop:
    return ReadOnlyAgentLoop(
        FakeBackend(),
        DecisionValidator.from_path(SCHEMAS),
        ToolRegistry(ROOT),
        LoopBudgets(max_turns=4, max_tool_calls=2),
        clock=lambda: NOW,
        monotonic=lambda: 0.0,
        observer=observer,
    )


class LoopObserverTests(unittest.TestCase):
    def test_observer_receives_events_and_observations_in_trace_order(self) -> None:
        observer = RecordingObserver()

        result = loop(observer).run(run_id="observer-order", issue="Find parser")

        self.assertEqual(result.termination_reason, TerminationReason.FINAL_ANSWER)
        self.assertEqual(
            observer.entries,
            [
                ("event", EventType.RUN_CREATED.value),
                ("event", EventType.ACTION_ACCEPTED.value),
                ("observation", result.observations[0].content),
                ("event", EventType.TOOL_RESULT.value),
                ("event", EventType.FINAL_ANSWER.value),
            ],
        )

    def test_observer_errors_do_not_change_loop_result(self) -> None:
        baseline = loop().run(run_id="observer-isolated", issue="Find parser")
        observed = loop(RaisingObserver()).run(run_id="observer-isolated", issue="Find parser")

        self.assertEqual(
            tuple(event.to_json() for event in observed.events),
            tuple(event.to_json() for event in baseline.events),
        )
        self.assertEqual(observed.observations, baseline.observations)
        self.assertEqual(observed.final_answer, baseline.final_answer)


if __name__ == "__main__":
    unittest.main()
