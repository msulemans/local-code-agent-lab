from __future__ import annotations

import json
from pathlib import Path
import unittest

from localcode.decisions import DecisionValidator
from localcode.loop import AgentLoop, CompletionRequirements, LoopBudgets, TerminationReason
from localcode.tools import ToolResult


SCHEMAS = Path("benchmarks/micro_agent/tool_schemas.json")
NOW = "2026-08-10T15:00:00+10:00"


def tool(name: str, arguments: dict[str, object]) -> str:
    return json.dumps(
        {
            "protocol_version": "1",
            "thought_summary": "Continue the engineering workflow.",
            "decision": {"kind": "tool", "tool": name, "arguments": arguments},
        }
    )


def final() -> str:
    return json.dumps(
        {
            "protocol_version": "1",
            "thought_summary": "The patch is verified.",
            "decision": {"kind": "final", "answer": "Fixed and tested."},
        }
    )


class FakeBackend:
    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)

    def complete(self, request) -> str:
        return self.responses.pop(0)


class FakeEngineeringRegistry:
    tool_names = ("apply_patch", "git_diff", "list_files", "read_file", "run_tests", "search_code", "write_file")

    def __init__(self, test_exits: list[int]) -> None:
        self.test_exits = list(test_exits)
        self.executed = []

    def execute(self, action) -> ToolResult:
        self.executed.append(action.tool)
        if action.tool == "run_tests":
            return ToolResult(content="tests", metadata=(("exit_code", self.test_exits.pop(0)),))
        return ToolResult(content=action.tool)


def run(responses: list[str], registry: FakeEngineeringRegistry):
    return AgentLoop(
        FakeBackend(responses),
        DecisionValidator.from_path(SCHEMAS),
        registry,
        LoopBudgets(max_turns=len(responses), max_tool_calls=8),
        clock=lambda: NOW,
        monotonic=lambda: 0.0,
        completion_requirements=CompletionRequirements(
            require_patch=True,
            require_passing_tests=True,
        ),
    ).run(run_id="engineering-loop", issue="Fix parser")


class EngineeringLoopTests(unittest.TestCase):
    def test_final_answer_is_rejected_until_patch_and_tests_pass(self) -> None:
        registry = FakeEngineeringRegistry([0])

        result = run(
            [
                final(),
                tool("apply_patch", {"patch": "patch-one"}),
                tool("run_tests", {"command_name": "python-unittest"}),
                final(),
            ],
            registry,
        )

        self.assertEqual(result.termination_reason, TerminationReason.FINAL_ANSWER)
        self.assertEqual(result.invalid_actions_used, 1)
        self.assertEqual(registry.executed, ["apply_patch", "run_tests"])
        self.assertEqual(result.observations[0].metadata_dict()["code"], "incomplete_work")

    def test_new_patch_invalidates_old_test_success_and_allows_retest(self) -> None:
        registry = FakeEngineeringRegistry([0, 0])

        result = run(
            [
                tool("apply_patch", {"patch": "patch-one"}),
                tool("run_tests", {"command_name": "python-unittest"}),
                tool("apply_patch", {"patch": "patch-two"}),
                final(),
                tool("run_tests", {"command_name": "python-unittest"}),
                final(),
            ],
            registry,
        )

        self.assertEqual(result.termination_reason, TerminationReason.FINAL_ANSWER)
        self.assertEqual(result.invalid_actions_used, 1)
        self.assertEqual(
            registry.executed,
            ["apply_patch", "run_tests", "apply_patch", "run_tests"],
        )


if __name__ == "__main__":
    unittest.main()
