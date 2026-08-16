from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest

from scripts.smoke_one_turn_ollama import run_cli
from localcode.compatibility import CompatibilityError
from localcode.controller import OneTurnResult
from localcode.events import Event, EventType
from localcode.preflight import SmokeBaseline, SmokePreflightError
from localcode.smoke import SmokeRun
from localcode.tools import ToolResult


NOW = "2026-08-10T11:00:00+10:00"
RUN_ID = "smoke-cli-v1"


def result(event_type: EventType, *, content: str) -> OneTurnResult:
    events = [
        Event(
            schema_version=1,
            run_id=RUN_ID,
            sequence=0,
            timestamp=NOW,
            event_type=EventType.RUN_CREATED,
            state="created",
            summary="created",
        )
    ]
    if event_type is not EventType.RUN_CREATED:
        events.append(
            Event(
                schema_version=1,
                run_id=RUN_ID,
                sequence=1,
                timestamp=NOW,
                event_type=event_type,
                state="observed",
                summary=event_type.value,
            )
        )
    return OneTurnResult(
        events=tuple(events),
        action=None,
        observation=ToolResult(content=content),
    )


def artifact(root: Path) -> dict[str, object]:
    path = root / "one-turn-smoke" / RUN_ID / "run.json"
    return json.loads(path.read_text(encoding="utf-8"))


class SmokeCliTests(unittest.TestCase):
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

    def test_preflight_failure_is_recorded_without_a_baseline(self) -> None:
        def blocked(**_):
            raise SmokePreflightError("retained_swap", "swap is not zero")

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            exit_code, output = self.run_case(root, blocked)
            record = artifact(root)

        self.assertEqual(exit_code, 2)
        self.assertIn("ARTIFACT", output)
        self.assertEqual(record["state"], "blocked_preflight")
        self.assertIsNone(record["baseline"])
        self.assertEqual(record["error"]["code"], "retained_swap")

    def test_backend_failure_preserves_the_accepted_baseline(self) -> None:
        def backend_failure(**arguments):
            arguments["baseline_observer"](SmokeBaseline(0, 91, ()))
            raise CompatibilityError("stream ended early")

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            exit_code, _ = self.run_case(root, backend_failure)
            record = artifact(root)

        self.assertEqual(exit_code, 2)
        self.assertEqual(record["state"], "backend_error")
        self.assertEqual(record["baseline"]["swap_used_bytes"], 0)
        self.assertEqual(record["error"]["message"], "stream ended early")

    def test_rejected_action_is_a_complete_failed_smoke(self) -> None:
        def rejected(**arguments):
            baseline = SmokeBaseline(0, 91, ())
            arguments["baseline_observer"](baseline)
            return SmokeRun(
                baseline=baseline,
                result=result(EventType.ACTION_REJECTED, content="invalid_json"),
            )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            exit_code, _ = self.run_case(root, rejected)
            record = artifact(root)

        self.assertEqual(exit_code, 1)
        self.assertEqual(record["state"], "completed_without_tool_result")
        self.assertEqual(record["events"][-1]["event_type"], "action_rejected")
        self.assertEqual(record["observation"]["content"], "invalid_json")

    def test_successful_tool_result_is_recorded_with_exit_zero(self) -> None:
        def successful(**arguments):
            baseline = SmokeBaseline(0, 91, ())
            arguments["baseline_observer"](baseline)
            return SmokeRun(
                baseline=baseline,
                result=result(EventType.TOOL_RESULT, content="src/tiny_parser.py:1"),
            )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            exit_code, output = self.run_case(root, successful)
            record = artifact(root)

        self.assertEqual(exit_code, 0)
        self.assertIn("src/tiny_parser.py:1", output)
        self.assertEqual(record["state"], "completed")
        self.assertEqual(record["exit_code"], 0)

    def test_duplicate_run_stops_before_the_smoke_runner(self) -> None:
        calls = []

        def blocked_if_called(**arguments):
            calls.append(arguments)
            raise AssertionError("smoke runner must not be called")

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "one-turn-smoke" / RUN_ID).mkdir(parents=True)
            exit_code, output = self.run_case(root, blocked_if_called)

        self.assertEqual(exit_code, 2)
        self.assertIn("record_error", output)
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
