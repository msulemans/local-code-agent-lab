from __future__ import annotations

import json
from pathlib import Path
import unittest

from localcode.actions import ActionValidator
from localcode.controller import OneTurnController, OneTurnRequest
from localcode.events import EventType
from localcode.registry import ToolRegistry


ROOT = Path("tests/fixtures/micro_repos/parser_none")
SCHEMAS = Path("benchmarks/model_compatibility/tool_schemas.json")
NOW = "2026-08-09T19:00:00+10:00"


class FakeBackend:
    def __init__(self, response: str) -> None:
        self.response = response
        self.requests: list[OneTurnRequest] = []

    def complete(self, request: OneTurnRequest) -> str:
        self.requests.append(request)
        return self.response


def action_payload(tool: str, arguments: dict[str, object]) -> str:
    return json.dumps(
        {
            "protocol_version": "1",
            "thought_summary": "Inspect the most relevant repository evidence.",
            "action": {"tool": tool, "arguments": arguments},
        }
    )


def controller(response: str) -> tuple[OneTurnController, FakeBackend]:
    backend = FakeBackend(response)
    instance = OneTurnController(
        backend,
        ActionValidator.from_path(SCHEMAS),
        ToolRegistry(ROOT),
        clock=lambda: NOW,
    )
    return instance, backend


class OneTurnControllerTests(unittest.TestCase):
    def test_valid_call_executes_exactly_one_read_only_tool(self) -> None:
        instance, backend = controller(action_payload("search_code", {"query": "def parse"}))

        result = instance.run(run_id="turn-valid", issue="Parser crashes on None")

        self.assertIn("src/tiny_parser.py:1", result.observation.content)
        self.assertEqual([event.event_type for event in result.events], [
            EventType.RUN_CREATED,
            EventType.ACTION_ACCEPTED,
            EventType.TOOL_RESULT,
        ])
        self.assertEqual(len(backend.requests), 1)
        self.assertEqual(backend.requests[0].allowed_tools, ("git_diff", "list_files", "read_file", "search_code"))

    def test_invalid_json_becomes_an_observation_without_a_tool_call(self) -> None:
        instance, backend = controller("I should search the code")

        result = instance.run(run_id="turn-invalid", issue="Parser crashes")

        self.assertIsNone(result.action)
        self.assertEqual(result.observation.metadata_dict()["code"], "invalid_json")
        self.assertEqual(result.events[-1].event_type, EventType.ACTION_REJECTED)
        self.assertEqual(len(backend.requests), 1)

    def test_unknown_tool_becomes_an_observation(self) -> None:
        instance, _ = controller(action_payload("terminal", {"command": "pwd"}))

        result = instance.run(run_id="turn-unknown", issue="Inspect repository")

        self.assertEqual(result.observation.metadata_dict()["code"], "unknown_tool")
        self.assertEqual(result.events[-1].event_type, EventType.ACTION_REJECTED)

    def test_tool_policy_error_becomes_an_observation(self) -> None:
        instance, _ = controller(action_payload("read_file", {"path": "../secret.txt"}))

        result = instance.run(run_id="turn-policy", issue="Read file")

        self.assertEqual(result.observation.metadata_dict()["code"], "path_escape")
        self.assertEqual(result.events[-1].event_type, EventType.TOOL_ERROR)

    def test_identical_fake_inputs_produce_identical_event_sequences(self) -> None:
        response = action_payload("list_files", {})
        first, _ = controller(response)
        second, _ = controller(response)

        first_result = first.run(run_id="deterministic", issue="Map repository")
        second_result = second.run(run_id="deterministic", issue="Map repository")

        self.assertEqual(
            tuple(event.to_json() for event in first_result.events),
            tuple(event.to_json() for event in second_result.events),
        )
        self.assertEqual(first_result.observation, second_result.observation)


if __name__ == "__main__":
    unittest.main()
