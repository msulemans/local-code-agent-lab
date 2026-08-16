"""Immutable-directory evidence records for one-turn model smoke attempts."""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

from .controller import OneTurnResult
from .events import EventType
from .preflight import SmokeBaseline


_RUN_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{2,79}$")


class SmokeRecordError(RuntimeError):
    """Raised when a smoke evidence directory cannot be created safely."""


class SmokeRecorder:
    """Update one run record without ever reusing its directory."""

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
        issue: str,
    ) -> "SmokeRecorder":
        if not isinstance(run_id, str) or _RUN_ID.fullmatch(run_id) is None:
            raise SmokeRecordError("run ID must be 3-80 lowercase safe characters")

        directory = Path(runs_root) / "one-turn-smoke" / run_id
        try:
            directory.mkdir(parents=True)
        except FileExistsError as exc:
            raise SmokeRecordError(f"run directory already exists: {directory}") from exc
        except OSError as exc:
            raise SmokeRecordError(f"could not create run directory: {directory}") from exc

        recorder = cls(
            directory,
            {
                "schema_version": 1,
                "run_id": run_id,
                "model": model,
                "issue": issue,
                "state": "created",
                "baseline": None,
                "events": [],
                "observation": None,
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

    def record_result(self, result: OneTurnResult) -> int:
        self._require_state("baseline_accepted")
        if not result.events:
            raise SmokeRecordError("smoke result must contain at least one event")
        run_id = self._record["run_id"]
        if any(event.run_id != run_id for event in result.events):
            raise SmokeRecordError("smoke result event run IDs must match the recorder")
        if tuple(event.sequence for event in result.events) != tuple(range(len(result.events))):
            raise SmokeRecordError("smoke result event sequences must be contiguous from zero")

        successful = result.events[-1].event_type is EventType.TOOL_RESULT
        exit_code = 0 if successful else 1
        self._record.update(
            state="completed" if successful else "completed_without_tool_result",
            events=[event.to_dict() for event in result.events],
            observation={
                "content": result.observation.content,
                "truncated": result.observation.truncated,
                "metadata": result.observation.metadata_dict(),
            },
            exit_code=exit_code,
        )
        self._write()
        return exit_code

    def record_error(self, *, state: str, code: str, message: str) -> None:
        allowed_transition = (
            (self._record["state"], state)
            in {
                ("created", "blocked_preflight"),
                ("baseline_accepted", "backend_error"),
            }
        )
        if not allowed_transition:
            raise SmokeRecordError(
                f"invalid smoke record transition: {self._record['state']} -> {state}"
            )
        if not isinstance(code, str) or not code or not isinstance(message, str) or not message:
            raise SmokeRecordError("smoke error code and message must be non-empty strings")
        self._record.update(
            state=state,
            error={"code": code, "message": message},
            exit_code=2,
        )
        self._write()

    def _require_state(self, expected: str) -> None:
        actual = self._record["state"]
        if actual != expected:
            raise SmokeRecordError(
                f"smoke record must be {expected!r}; observed {actual!r}"
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
            raise SmokeRecordError(f"could not write smoke evidence: {destination}") from exc
