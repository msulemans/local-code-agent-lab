from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest

from localcode.engineering_smoke import EngineeringSmokeRun, ResourceSnapshot
from localcode.events import Event, EventType
from localcode.loop import LoopResult, TerminationReason
from localcode.preflight import SmokeBaseline, SmokePreflightError
from localcode.tools import ToolResult
from scripts.smoke_engineering_ollama import run_cli


NOW = "2026-08-12T18:00:00+10:00"
RUN_ID = "engineering-cli-v1"
EXPECTED = ("src/tiny_parser.py",)


def engineering_result(*, solved: bool, reason: TerminationReason) -> EngineeringSmokeRun:
    final_answer = "Fixed and tested." if reason is TerminationReason.FINAL_ANSWER else None
    last_type = EventType.FINAL_ANSWER if final_answer is not None else EventType.RUN_TERMINATED
    result = LoopResult(
        events=(
            Event(1, RUN_ID, 0, NOW, EventType.RUN_CREATED, "created", "created"),
            Event(1, RUN_ID, 1, NOW, last_type, "completed", last_type.value),
        ),
        observations=(
            ToolResult(content="OK", metadata=(("exit_code", 0), ("sandboxed", True))),
        ),
        termination_reason=reason,
        final_answer=final_answer,
        turns_used=3,
        tool_calls_used=2,
        invalid_actions_used=0,
    )
    return EngineeringSmokeRun(
        context_mode="simple",
        baseline=SmokeBaseline(0, 91, ()),
        result=result,
        resource_snapshots=(ResourceSnapshot(0, "before_inference", 0, 91),),
        first_context_chars=376,
        first_selected_paths=(),
        diff="diff --git a/src/tiny_parser.py b/src/tiny_parser.py\n",
        diff_truncated=False,
        changed_paths=EXPECTED,
        expected_changed_paths=EXPECTED,
        test_exit_codes=(0,),
        source_unchanged=True,
        solved=solved,
    )


def artifact(root: Path) -> dict:
    return json.loads(
        (root / "engineering-smoke" / RUN_ID / "run.json").read_text(encoding="utf-8")
    )


class EngineeringSmokeCliTests(unittest.TestCase):
    def run_case(self, root: Path, runner) -> tuple[int, str]:
        output = StringIO()
        with redirect_stdout(output):
            exit_code = run_cli(
                ["--run-id", RUN_ID],
                smoke_runner=runner,
                runs_root=root,
                clock=lambda: NOW,
            )
        return exit_code, output.getvalue()

    def test_preflight_failure_is_recorded_before_any_baseline(self) -> None:
        def blocked(**arguments):
            raise SmokePreflightError("retained_swap", "swap is not zero")

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            exit_code, output = self.run_case(root, blocked)
            record = artifact(root)
        self.assertEqual(exit_code, 2)
        self.assertIn("ARTIFACT", output)
        self.assertEqual(record["state"], "blocked_preflight")
        self.assertIsNone(record["baseline"])

    def test_success_records_diff_tests_and_exit_zero(self) -> None:
        def successful(**arguments):
            result = engineering_result(solved=True, reason=TerminationReason.FINAL_ANSWER)
            arguments["baseline_observer"](result.baseline)
            return result

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            exit_code, output = self.run_case(root, successful)
            record = artifact(root)
        self.assertEqual(exit_code, 0)
        self.assertIn("DIFF", output)
        self.assertEqual(record["state"], "completed")
        self.assertEqual(record["context_mode"], "simple")
        self.assertFalse(record["allow_retained_swap"])
        self.assertEqual(record["test_exit_codes"], [0])
        self.assertIn("src/tiny_parser.py", record["diff"])

    def test_cli_forwards_context_mode_to_smoke_runner(self) -> None:
        captured = {}

        def successful(**arguments):
            captured["context_mode"] = arguments["context_mode"]
            result = engineering_result(
                solved=True,
                reason=TerminationReason.FINAL_ANSWER,
            )
            result = EngineeringSmokeRun(
                context_mode="retrieval",
                baseline=result.baseline,
                result=result.result,
                resource_snapshots=result.resource_snapshots,
                first_context_chars=result.first_context_chars,
                first_selected_paths=result.first_selected_paths,
                diff=result.diff,
                diff_truncated=result.diff_truncated,
                changed_paths=result.changed_paths,
                expected_changed_paths=result.expected_changed_paths,
                test_exit_codes=result.test_exit_codes,
                source_unchanged=result.source_unchanged,
                solved=result.solved,
            )
            arguments["baseline_observer"](result.baseline)
            return result

        with tempfile.TemporaryDirectory() as temporary:
            output = StringIO()
            with redirect_stdout(output):
                exit_code = run_cli(
                    ["--run-id", RUN_ID, "--context-mode", "retrieval"],
                    smoke_runner=successful,
                    runs_root=Path(temporary),
                    clock=lambda: NOW,
                )
            record = artifact(Path(temporary))
        self.assertEqual(exit_code, 0)
        self.assertEqual(captured["context_mode"], "retrieval")
        self.assertEqual(record["context_mode"], "retrieval")
        self.assertIn('"context_mode":"retrieval"', output.getvalue())

    def test_cli_forwards_retained_swap_override_to_smoke_runner(self) -> None:
        captured = {}

        def successful(**arguments):
            captured["allow_retained_swap"] = arguments["allow_retained_swap"]
            result = engineering_result(solved=True, reason=TerminationReason.FINAL_ANSWER)
            arguments["baseline_observer"](result.baseline)
            return result

        with tempfile.TemporaryDirectory() as temporary:
            output = StringIO()
            with redirect_stdout(output):
                exit_code = run_cli(
                    ["--run-id", RUN_ID, "--allow-retained-swap"],
                    smoke_runner=successful,
                    runs_root=Path(temporary),
                    clock=lambda: NOW,
                )
            record = artifact(Path(temporary))
        self.assertEqual(exit_code, 0)
        self.assertTrue(captured["allow_retained_swap"])
        self.assertTrue(record["allow_retained_swap"])
        self.assertIn('"allow_retained_swap":true', output.getvalue())

    def test_bounded_backend_termination_returns_operational_exit_two(self) -> None:
        def backend_error(**arguments):
            result = engineering_result(solved=False, reason=TerminationReason.BACKEND_ERROR)
            arguments["baseline_observer"](result.baseline)
            return result

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            exit_code, _ = self.run_case(root, backend_error)
            record = artifact(root)
        self.assertEqual(exit_code, 2)
        self.assertEqual(record["state"], "backend_error")

    def test_duplicate_run_stops_before_runner(self) -> None:
        calls = []

        def must_not_run(**arguments):
            calls.append(arguments)
            raise AssertionError("runner must not execute")

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "engineering-smoke" / RUN_ID).mkdir(parents=True)
            exit_code, output = self.run_case(root, must_not_run)
        self.assertEqual(exit_code, 2)
        self.assertIn("record_error", output)
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
