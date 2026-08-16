from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from localcode.actions import ValidatedAction
from localcode.controller import OneTurnResult
from localcode.events import Event, EventType
from localcode.preflight import SmokeBaseline
from localcode.smoke_records import SmokeRecordError, SmokeRecorder
from localcode.tools import ToolResult


NOW = "2026-08-10T10:00:00+10:00"


def event(sequence: int, event_type: EventType) -> Event:
    return Event(
        schema_version=1,
        run_id="smoke-record-v1",
        sequence=sequence,
        timestamp=NOW,
        event_type=event_type,
        state="observed",
        summary=event_type.value,
    )


class SmokeRecorderTests(unittest.TestCase):
    def test_invalid_run_id_is_rejected_without_creating_a_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)

            with self.assertRaises(SmokeRecordError):
                SmokeRecorder.create(
                    runs_root=root,
                    run_id="../escape",
                    model="qwen3.5:9b-q4_K_M",
                    issue="Parser issue",
                )

            self.assertEqual(list(root.iterdir()), [])

    def test_existing_run_directory_is_never_reused(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            arguments = {
                "runs_root": temporary,
                "run_id": "smoke-record-v1",
                "model": "qwen3.5:9b-q4_K_M",
                "issue": "Parser issue",
            }
            SmokeRecorder.create(**arguments)

            with self.assertRaises(SmokeRecordError):
                SmokeRecorder.create(**arguments)

    def test_backend_error_preserves_an_accepted_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            recorder = SmokeRecorder.create(
                runs_root=temporary,
                run_id="smoke-record-v1",
                model="qwen3.5:9b-q4_K_M",
                issue="Parser issue",
            )
            recorder.record_baseline(SmokeBaseline(0, 91, ()))
            recorder.record_error(
                state="backend_error",
                code="backend_error",
                message="connection closed",
            )

            record = json.loads((recorder.directory / "run.json").read_text(encoding="utf-8"))
            self.assertEqual(record["state"], "backend_error")
            self.assertEqual(record["baseline"]["swap_used_bytes"], 0)
            self.assertEqual(record["error"]["message"], "connection closed")
            self.assertEqual(record["exit_code"], 2)

    def test_success_records_events_observation_and_exit_code(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            recorder = SmokeRecorder.create(
                runs_root=temporary,
                run_id="smoke-record-v1",
                model="qwen3.5:9b-q4_K_M",
                issue="Parser issue",
            )
            recorder.record_baseline(SmokeBaseline(0, 91, ()))
            action = ValidatedAction(
                protocol_version="1",
                thought_summary="Search first.",
                tool="search_code",
                arguments=(("query", "parse_value"),),
            )
            result = OneTurnResult(
                events=(event(0, EventType.RUN_CREATED), event(1, EventType.TOOL_RESULT)),
                action=action,
                observation=ToolResult(content="src/parser.py:1", metadata=(("matches", 1),)),
            )

            exit_code = recorder.record_result(result)

            record = json.loads((recorder.directory / "run.json").read_text(encoding="utf-8"))
            self.assertEqual(exit_code, 0)
            self.assertEqual(record["state"], "completed")
            self.assertEqual(len(record["events"]), 2)
            self.assertEqual(record["observation"]["content"], "src/parser.py:1")
            self.assertEqual(record["exit_code"], 0)

    def test_result_cannot_be_recorded_before_the_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            recorder = SmokeRecorder.create(
                runs_root=temporary,
                run_id="smoke-record-v1",
                model="qwen3.5:9b-q4_K_M",
                issue="Parser issue",
            )
            result = OneTurnResult(
                events=(event(0, EventType.RUN_CREATED),),
                action=None,
                observation=ToolResult(content="rejected"),
            )

            with self.assertRaisesRegex(SmokeRecordError, "baseline_accepted"):
                recorder.record_result(result)

    def test_terminal_record_cannot_be_mutated(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            recorder = SmokeRecorder.create(
                runs_root=temporary,
                run_id="smoke-record-v1",
                model="qwen3.5:9b-q4_K_M",
                issue="Parser issue",
            )
            recorder.record_error(
                state="blocked_preflight",
                code="retained_swap",
                message="swap is not zero",
            )

            with self.assertRaises(SmokeRecordError):
                recorder.record_baseline(SmokeBaseline(0, 91, ()))

    def test_result_events_must_belong_to_this_run_in_sequence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            recorder = SmokeRecorder.create(
                runs_root=temporary,
                run_id="smoke-record-v1",
                model="qwen3.5:9b-q4_K_M",
                issue="Parser issue",
            )
            recorder.record_baseline(SmokeBaseline(0, 91, ()))
            wrong_run_event = Event(
                schema_version=1,
                run_id="different-run",
                sequence=0,
                timestamp=NOW,
                event_type=EventType.RUN_CREATED,
                state="created",
                summary="wrong run",
            )

            with self.assertRaisesRegex(SmokeRecordError, "run IDs"):
                recorder.record_result(
                    OneTurnResult(
                        events=(wrong_run_event,),
                        action=None,
                        observation=ToolResult(content="wrong run"),
                    )
                )

            noncontiguous = OneTurnResult(
                events=(event(0, EventType.RUN_CREATED), event(2, EventType.TOOL_RESULT)),
                action=None,
                observation=ToolResult(content="bad sequence"),
            )
            with self.assertRaisesRegex(SmokeRecordError, "contiguous"):
                recorder.record_result(noncontiguous)


if __name__ == "__main__":
    unittest.main()
