from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

from localcode.engineering_smoke import EngineeringSmokeRun, ResourceSnapshot
from localcode.engineering_smoke_records import (
    EngineeringSmokeRecordError,
    EngineeringSmokeRecorder,
)
from localcode.events import Event, EventType
from localcode.loop import LoopResult, TerminationReason
from localcode.preflight import SmokeBaseline
from localcode.tools import ToolResult


NOW = "2026-08-12T18:00:00+10:00"
RUN_ID = "engineering-record-v1"
EXPECTED = ("src/tiny_parser.py",)


def event(sequence: int, event_type: EventType) -> Event:
    return Event(
        schema_version=1,
        run_id=RUN_ID,
        sequence=sequence,
        timestamp=NOW,
        event_type=event_type,
        state="completed" if event_type is EventType.FINAL_ANSWER else "created",
        summary=event_type.value,
    )


def smoke_result(
    *,
    reason: TerminationReason = TerminationReason.FINAL_ANSWER,
    solved: bool = True,
    context_mode: str = "simple",
) -> EngineeringSmokeRun:
    final = "Fixed and tested." if reason is TerminationReason.FINAL_ANSWER else None
    events = (
        (event(0, EventType.RUN_CREATED), event(1, EventType.FINAL_ANSWER))
        if final is not None
        else (event(0, EventType.RUN_CREATED), event(1, EventType.RUN_TERMINATED))
    )
    result = LoopResult(
        events=events,
        observations=(
            ToolResult(
                content="OK",
                metadata=(("command", "python-unittest"), ("exit_code", 0)),
            ),
        ),
        termination_reason=reason,
        final_answer=final,
        turns_used=3,
        tool_calls_used=2,
        invalid_actions_used=0,
    )
    return EngineeringSmokeRun(
        context_mode=context_mode,
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


class EngineeringSmokeRecorderTests(unittest.TestCase):
    def create(self, root: str | Path) -> EngineeringSmokeRecorder:
        return EngineeringSmokeRecorder.create(
            runs_root=root,
            run_id=RUN_ID,
            model="qwen3.5:9b-q4_K_M",
            context_mode="simple",
            allow_retained_swap=False,
            case_id="parser-none",
            issue="Parser crashes on None",
            expected_changed_paths=EXPECTED,
        )

    def test_success_records_complete_portable_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            recorder = self.create(temporary)
            recorder.record_baseline(SmokeBaseline(0, 91, ()))

            exit_code = recorder.record_result(smoke_result())

            record = json.loads((recorder.directory / "run.json").read_text(encoding="utf-8"))
        self.assertEqual(exit_code, 0)
        self.assertEqual(record["state"], "completed")
        self.assertTrue(record["solved"])
        self.assertEqual(record["context_mode"], "simple")
        self.assertFalse(record["allow_retained_swap"])
        self.assertEqual(record["first_context_chars"], 376)
        self.assertEqual(record["changed_paths"], list(EXPECTED))
        self.assertEqual(record["test_exit_codes"], [0])
        self.assertEqual(record["resource_snapshots"][0]["phase"], "before_inference")

    def test_backend_termination_is_recorded_as_operational_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            recorder = self.create(temporary)
            recorder.record_baseline(SmokeBaseline(0, 91, ()))
            exit_code = recorder.record_result(
                smoke_result(reason=TerminationReason.BACKEND_ERROR, solved=False)
            )
            record = json.loads((recorder.directory / "run.json").read_text(encoding="utf-8"))
        self.assertEqual(exit_code, 2)
        self.assertEqual(record["state"], "backend_error")
        self.assertEqual(record["termination_reason"], "backend_error")

    def test_preflight_failure_is_terminal_and_preserves_no_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            recorder = self.create(temporary)
            recorder.record_error(
                state="blocked_preflight",
                code="retained_swap",
                message="swap is not zero",
            )
            with self.assertRaises(EngineeringSmokeRecordError):
                recorder.record_baseline(SmokeBaseline(0, 91, ()))
            record = json.loads((recorder.directory / "run.json").read_text(encoding="utf-8"))
        self.assertEqual(record["state"], "blocked_preflight")
        self.assertIsNone(record["baseline"])
        self.assertEqual(record["exit_code"], 2)

    def test_invalid_or_duplicate_run_directory_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(EngineeringSmokeRecordError):
                EngineeringSmokeRecorder.create(
                    runs_root=temporary,
                    run_id="../escape",
                    model="qwen3.5:9b-q4_K_M",
                    context_mode="simple",
                    allow_retained_swap=False,
                    case_id="parser-none",
                    issue="issue",
                    expected_changed_paths=EXPECTED,
                )
            self.create(temporary)
            with self.assertRaises(EngineeringSmokeRecordError):
                self.create(temporary)

    def test_result_events_must_match_the_record(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            recorder = self.create(temporary)
            recorder.record_baseline(SmokeBaseline(0, 91, ()))
            valid = smoke_result()
            wrong_event = Event(
                schema_version=1,
                run_id="different-run",
                sequence=0,
                timestamp=NOW,
                event_type=EventType.RUN_CREATED,
                state="created",
                summary="wrong",
            )
            wrong_loop = LoopResult(
                events=(wrong_event,),
                observations=valid.result.observations,
                termination_reason=valid.result.termination_reason,
                final_answer=valid.result.final_answer,
                turns_used=valid.result.turns_used,
                tool_calls_used=valid.result.tool_calls_used,
                invalid_actions_used=valid.result.invalid_actions_used,
            )
            wrong = EngineeringSmokeRun(
                context_mode=valid.context_mode,
                baseline=valid.baseline,
                result=wrong_loop,
                resource_snapshots=valid.resource_snapshots,
                first_context_chars=valid.first_context_chars,
                first_selected_paths=valid.first_selected_paths,
                diff=valid.diff,
                diff_truncated=valid.diff_truncated,
                changed_paths=valid.changed_paths,
                expected_changed_paths=valid.expected_changed_paths,
                test_exit_codes=valid.test_exit_codes,
                source_unchanged=valid.source_unchanged,
                solved=valid.solved,
            )
            with self.assertRaisesRegex(EngineeringSmokeRecordError, "run IDs"):
                recorder.record_result(wrong)
            with self.assertRaisesRegex(EngineeringSmokeRecordError, "baseline"):
                recorder.record_result(
                    replace(valid, baseline=SmokeBaseline(0, 72, ()))
                )
            with self.assertRaisesRegex(EngineeringSmokeRecordError, "context mode"):
                recorder.record_result(
                    replace(valid, context_mode="retrieval")
                )


if __name__ == "__main__":
    unittest.main()
