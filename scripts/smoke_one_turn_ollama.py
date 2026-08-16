#!/usr/bin/env python3
"""Run the single bounded Qwen3.5 smoke turn after a clean-host preflight."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
from typing import Callable, Sequence

from localcode.compatibility import CompatibilityError
from localcode.controller import ModelBackendError
from localcode.preflight import SmokePreflightError
from localcode.smoke import SmokeRun, run_one_turn_smoke
from localcode.smoke_records import SmokeRecordError, SmokeRecorder


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = REPOSITORY_ROOT / "tests/fixtures/micro_repos/parser_none"
TOOL_SCHEMAS = REPOSITORY_ROOT / "benchmarks/model_compatibility/tool_schemas.json"
RUNS_ROOT = REPOSITORY_ROOT / "runs"
MODEL = "qwen3.5:9b-q4_K_M"
ISSUE = "Parser crashes when given None. Inspect the repository for the relevant definition."
SmokeRunner = Callable[..., SmokeRun]


def run_cli(
    argv: Sequence[str] | None = None,
    *,
    smoke_runner: SmokeRunner = run_one_turn_smoke,
    runs_root: str | Path = RUNS_ROOT,
    clock: Callable[[], str] | None = None,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    arguments = parser.parse_args(argv)

    tool_document = json.loads(TOOL_SCHEMAS.read_text(encoding="utf-8"))
    try:
        recorder = SmokeRecorder.create(
            runs_root=runs_root,
            run_id=arguments.run_id,
            model=MODEL,
            issue=ISSUE,
        )
    except SmokeRecordError as exc:
        print(json.dumps({"error": str(exc), "code": "record_error"}, sort_keys=True))
        return 2

    try:
        smoke = smoke_runner(
            run_id=arguments.run_id,
            issue=ISSUE,
            model=MODEL,
            repository_root=FIXTURE_ROOT,
            tool_document=tool_document,
            clock=clock
            if clock is not None
            else lambda: datetime.now().astimezone().isoformat(timespec="microseconds"),
            baseline_observer=recorder.record_baseline,
        )
    except (SmokePreflightError, ModelBackendError, CompatibilityError) as exc:
        code = getattr(exc, "code", "backend_error")
        state = "blocked_preflight" if isinstance(exc, SmokePreflightError) else "backend_error"
        recorder.record_error(state=state, code=code, message=str(exc))
        print(f"ARTIFACT {recorder.directory}")
        print(json.dumps({"error": str(exc), "code": code}, sort_keys=True))
        return 2

    print("BASELINE")
    print(
        json.dumps(
            {
                "swap_used_bytes": smoke.baseline.swap_used_bytes,
                "memory_free_percent": smoke.baseline.memory_free_percent,
                "loaded_models": list(smoke.baseline.loaded_models),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    print("EVENTS")
    for event in smoke.result.events:
        print(event.to_json())
    print("OBSERVATION")
    print(
        json.dumps(
            {
                "content": smoke.result.observation.content,
                "truncated": smoke.result.observation.truncated,
                "metadata": smoke.result.observation.metadata_dict(),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    exit_code = recorder.record_result(smoke.result)
    print(f"ARTIFACT {recorder.directory}")
    return exit_code


def main() -> int:
    return run_cli()


if __name__ == "__main__":
    raise SystemExit(main())
