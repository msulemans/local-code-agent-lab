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


class RecordingBackend(FakeBackend):
    def __init__(self, responses: list[str]) -> None:
        super().__init__(responses)
        self.requests = []

    def complete(self, request) -> str:
        self.requests.append(request)
        return super().complete(request)


class FakeEngineeringRegistry:
    tool_names = ("apply_patch", "edit_file", "git_diff", "list_files", "read_file", "run_tests", "search_code", "write_file")

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

    def test_auto_test_after_edit_runs_registered_tests_without_a_model_call(self) -> None:
        registry = FakeEngineeringRegistry([0])

        result = AgentLoop(
            FakeBackend([tool("apply_patch", {"patch": "patch-one"}), final()]),
            DecisionValidator.from_path(SCHEMAS),
            registry,
            LoopBudgets(max_turns=2, max_tool_calls=8, auto_test_after_edit=True),
            clock=lambda: NOW,
            monotonic=lambda: 0.0,
            completion_requirements=CompletionRequirements(
                require_patch=True,
                require_passing_tests=True,
            ),
        ).run(run_id="auto-test", issue="Fix parser")

        # The controller runs the tests itself after the edit (m050-m055:
        # models churn on read/edit re-checks and die one call short of
        # run_tests), so the final answer is verified without a model test call.
        self.assertEqual(result.termination_reason, TerminationReason.FINAL_ANSWER)
        self.assertEqual(registry.executed, ["apply_patch", "run_tests"])
        self.assertEqual(result.tests_executed, 1)

    def test_all_successful_edit_tools_satisfy_the_patch_requirement(self) -> None:
        edit_actions = (
            tool(
                "edit_file",
                {"path": "src/parser.py", "old_string": "old", "new_string": "new"},
            ),
            tool("write_file", {"path": "src/parser.py", "content": "new file"}),
        )

        for edit_action in edit_actions:
            with self.subTest(edit_action=edit_action):
                registry = FakeEngineeringRegistry([0])
                result = AgentLoop(
                    FakeBackend([edit_action, final()]),
                    DecisionValidator.from_path(SCHEMAS),
                    registry,
                    LoopBudgets(max_turns=2, max_tool_calls=3, auto_test_after_edit=True),
                    clock=lambda: NOW,
                    monotonic=lambda: 0.0,
                    completion_requirements=CompletionRequirements(
                        require_patch=True,
                        require_test_execution=True,
                    ),
                ).run(run_id="non-patch-edit", issue="Fix parser")

                self.assertEqual(result.termination_reason, TerminationReason.FINAL_ANSWER)
                self.assertEqual(result.invalid_actions_used, 0)
                self.assertEqual(result.tests_executed, 1)

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

    def test_phase_policy_allows_multiple_distinct_reads_before_editing(self) -> None:
        backend = RecordingBackend(
            [
                tool("search_code", {"query": "parse"}),
                tool("read_file", {"path": "src/parser.py"}),
                tool("read_file", {"path": "tests/test_parser.py"}),
            ]
        )
        registry = FakeEngineeringRegistry([])

        AgentLoop(
            backend,
            DecisionValidator.from_path(SCHEMAS),
            registry,
            LoopBudgets(max_turns=3, max_tool_calls=3, phase_tool_policy=True),
            clock=lambda: NOW,
            monotonic=lambda: 0.0,
        ).run(run_id="multi-read", issue="Fix parser")

        self.assertEqual(backend.requests[1].allowed_tools, ("read_file",))
        self.assertIn("read_file", backend.requests[2].allowed_tools)
        self.assertEqual(registry.executed, ["search_code", "read_file", "read_file"])

    def test_test_execution_requirement_accepts_observed_failure_for_external_review(self) -> None:
        registry = FakeEngineeringRegistry([1])
        result = AgentLoop(
            FakeBackend(
                [
                    tool("apply_patch", {"patch": "patch-one"}),
                    final(),
                    tool("run_tests", {"command_name": "python-unittest"}),
                    final(),
                ]
            ),
            DecisionValidator.from_path(SCHEMAS),
            registry,
            LoopBudgets(max_turns=4, max_tool_calls=2),
            clock=lambda: NOW,
            monotonic=lambda: 0.0,
            completion_requirements=CompletionRequirements(
                require_patch=True,
                require_test_execution=True,
            ),
        ).run(run_id="test-observed", issue="Fix parser")

        self.assertEqual(result.termination_reason, TerminationReason.FINAL_ANSWER)
        self.assertEqual(result.tests_executed, 1)
        self.assertEqual(result.invalid_actions_used, 1)

    def test_phase_policy_allows_failure_investigation_after_tests(self) -> None:
        backend = RecordingBackend(
            [
                tool("apply_patch", {"patch": "patch-one"}),
                tool("run_tests", {"command_name": "python-unittest"}),
                tool("read_file", {"path": "tests/test_parser.py"}),
            ]
        )
        registry = FakeEngineeringRegistry([1])

        AgentLoop(
            backend,
            DecisionValidator.from_path(SCHEMAS),
            registry,
            LoopBudgets(max_turns=3, max_tool_calls=3, phase_tool_policy=True),
            clock=lambda: NOW,
            monotonic=lambda: 0.0,
        ).run(run_id="post-test-read", issue="Fix parser")

        self.assertIn("read_file", backend.requests[2].allowed_tools)
        self.assertEqual(registry.executed, ["apply_patch", "run_tests", "read_file"])


if __name__ == "__main__":
    unittest.main()
