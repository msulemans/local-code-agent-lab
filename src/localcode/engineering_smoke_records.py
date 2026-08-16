"""Immutable evidence records for bounded real-model repair smoke attempts."""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

from .engineering_smoke import EngineeringSmokeRun
from .loop import TerminationReason
from .preflight import SmokeBaseline


_RUN_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{2,79}$")
_TERMINAL_STATES = {
    "blocked_preflight",
    "setup_error",
    "backend_error",
    "completed",
    "completed_without_solution",
}


class EngineeringSmokeRecordError(RuntimeError):
    """Raised when engineering-smoke evidence cannot be recorded safely."""


class EngineeringSmokeRecorder:
    """Advance one unique run record through explicit immutable states."""

    def __init__(self, directory: Path, record: dict[str, Any]) -> None:
        self.directory = directory
        self._record = record

    @classmethod
    def create(
        cls,
        *,
        runs_root: str | Path,
        run_id: str,
        model: str,
        context_mode: str,
        allow_retained_swap: bool,
        case_id: str,
        issue: str,
        expected_changed_paths: tuple[str, ...],
    ) -> "EngineeringSmokeRecorder":
        if not isinstance(run_id, str) or _RUN_ID.fullmatch(run_id) is None:
            raise EngineeringSmokeRecordError(
                "run ID must be 3-80 lowercase safe characters"
            )
        if not isinstance(case_id, str) or _RUN_ID.fullmatch(case_id) is None:
            raise EngineeringSmokeRecordError(
                "case ID must be 3-80 lowercase safe characters"
            )
        if (
            not isinstance(expected_changed_paths, tuple)
            or not expected_changed_paths
            or any(not isinstance(path, str) or not path for path in expected_changed_paths)
        ):
            raise EngineeringSmokeRecordError(
                "expected changed paths must be a non-empty tuple of strings"
            )

        directory = Path(runs_root) / "engineering-smoke" / run_id
        try:
            directory.mkdir(parents=True)
        except FileExistsError as exc:
            raise EngineeringSmokeRecordError(
                f"run directory already exists: {directory}"
            ) from exc
        except OSError as exc:
            raise EngineeringSmokeRecordError(
                f"could not create run directory: {directory}"
            ) from exc

        recorder = cls(
            directory,
            {
                "schema_version": 1,
                "run_id": run_id,
                "model": model,
                "context_mode": context_mode,
                "allow_retained_swap": allow_retained_swap,
                "case_id": case_id,
                "issue": issue,
                "expected_changed_paths": list(sorted(expected_changed_paths)),
                "state": "created",
                "baseline": None,
                "resource_snapshots": [],
                "events": [],
                "observations": [],
                "first_context_chars": None,
                "first_selected_paths": [],
                "termination_reason": None,
                "final_answer": None,
                "diff": None,
                "diff_truncated": None,
                "changed_paths": [],
                "test_exit_codes": [],
                "source_unchanged": None,
                "solved": None,
                "error": None,
                "exit_code": None,
            },
        )
        recorder._write()
        return recorder

    def record_baseline(self, baseline: SmokeBaseline) -> None:
        self._require_state("created")
        self._record.update(
            state="baseline_accepted",
            baseline={
                "swap_used_bytes": baseline.swap_used_bytes,
                "memory_free_percent": baseline.memory_free_percent,
                "loaded_models": list(baseline.loaded_models),
            },
        )
        self._write()

    def record_result(self, smoke: EngineeringSmokeRun) -> int:
        self._require_state("baseline_accepted")
        events = smoke.result.events
        if not events:
            raise EngineeringSmokeRecordError(
                "engineering smoke result must contain at least one event"
            )
        run_id = self._record["run_id"]
        if any(event.run_id != run_id for event in events):
            raise EngineeringSmokeRecordError(
                "engineering smoke event run IDs must match the recorder"
            )
        if tuple(event.sequence for event in events) != tuple(range(len(events))):
            raise EngineeringSmokeRecordError(
                "engineering smoke event sequences must be contiguous from zero"
            )
        if list(smoke.expected_changed_paths) != self._record["expected_changed_paths"]:
            raise EngineeringSmokeRecordError(
                "engineering smoke expected paths must match the recorder"
            )
        if smoke.context_mode != self._record["context_mode"]:
            raise EngineeringSmokeRecordError(
                "engineering smoke context mode must match the recorder"
            )
        recorded_baseline = self._record["baseline"]
        if recorded_baseline != {
            "swap_used_bytes": smoke.baseline.swap_used_bytes,
            "memory_free_percent": smoke.baseline.memory_free_percent,
            "loaded_models": list(smoke.baseline.loaded_models),
        }:
            raise EngineeringSmokeRecordError(
                "engineering smoke baseline must match the accepted baseline"
            )
        if smoke.solved and not (
            smoke.result.termination_reason is TerminationReason.FINAL_ANSWER
            and smoke.result.final_answer is not None
            and bool(smoke.test_exit_codes)
            and smoke.test_exit_codes[-1] == 0
            and bool(smoke.diff)
            and not smoke.diff_truncated
            and smoke.changed_paths == smoke.expected_changed_paths
            and smoke.source_unchanged
        ):
            raise EngineeringSmokeRecordError(
                "solved engineering smoke lacks complete patch and test evidence"
            )

        if smoke.solved:
            state = "completed"
            exit_code = 0
        elif smoke.result.termination_reason is TerminationReason.BACKEND_ERROR:
            state = "backend_error"
            exit_code = 2
        else:
            state = "completed_without_solution"
            exit_code = 1
        self._record.update(
            state=state,
            resource_snapshots=[
                {
                    "turn_index": snapshot.turn_index,
                    "phase": snapshot.phase,
                    "swap_used_bytes": snapshot.swap_used_bytes,
                    "memory_free_percent": snapshot.memory_free_percent,
                }
                for snapshot in smoke.resource_snapshots
            ],
            events=[event.to_dict() for event in events],
            observations=[
                {
                    "content": observation.content,
                    "truncated": observation.truncated,
                    "metadata": observation.metadata_dict(),
                }
                for observation in smoke.result.observations
            ],
            first_context_chars=smoke.first_context_chars,
            first_selected_paths=list(smoke.first_selected_paths),
            termination_reason=smoke.result.termination_reason.value,
            final_answer=smoke.result.final_answer,
            diff=smoke.diff,
            diff_truncated=smoke.diff_truncated,
            changed_paths=list(smoke.changed_paths),
            test_exit_codes=list(smoke.test_exit_codes),
            source_unchanged=smoke.source_unchanged,
            solved=smoke.solved,
            exit_code=exit_code,
        )
        self._write()
        return exit_code

    def record_error(self, *, state: str, code: str, message: str) -> None:
        transition = (self._record["state"], state)
        if transition not in {
            ("created", "blocked_preflight"),
            ("created", "setup_error"),
            ("baseline_accepted", "setup_error"),
        }:
            raise EngineeringSmokeRecordError(
                f"invalid engineering smoke transition: {transition[0]} -> {transition[1]}"
            )
        if not isinstance(code, str) or not code or not isinstance(message, str) or not message:
            raise EngineeringSmokeRecordError(
                "engineering smoke error code and message must be non-empty strings"
            )
        self._record.update(
            state=state,
            error={"code": code, "message": message},
            exit_code=2,
        )
        self._write()

    def _require_state(self, expected: str) -> None:
        actual = self._record["state"]
        if actual in _TERMINAL_STATES or actual != expected:
            raise EngineeringSmokeRecordError(
                f"engineering smoke record must be {expected!r}; observed {actual!r}"
            )

    def _write(self) -> None:
        destination = self.directory / "run.json"
        temporary = self.directory / "run.json.tmp"
        try:
            temporary.write_text(
                json.dumps(self._record, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            temporary.replace(destination)
        except OSError as exc:
            raise EngineeringSmokeRecordError(
                f"could not write engineering smoke evidence: {destination}"
            ) from exc
