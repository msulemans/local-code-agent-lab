#!/usr/bin/env python3
"""Run one bounded Qwen repair against the parser-none micro repository."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
from typing import Callable, Sequence

from localcode.compatibility import CompatibilityError
from localcode.controller import ModelBackendError
from localcode.engineering_smoke import EngineeringSmokeRun, run_engineering_smoke
from localcode.engineering_smoke_records import (
    EngineeringSmokeRecordError,
    EngineeringSmokeRecorder,
)
from localcode.preflight import SmokePreflightError
from localcode.tools import ToolError


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = REPOSITORY_ROOT / "tests/fixtures/micro_repos/parser_none"
TOOL_SCHEMAS = REPOSITORY_ROOT / "benchmarks/micro_agent/tool_schemas.json"
RUNS_ROOT = REPOSITORY_ROOT / "runs"
MODEL = "qwen3.5:9b-q4_K_M"
CASE_ID = "parser-none"
EXPECTED_CHANGED_PATHS = ("src/tiny_parser.py",)
SmokeRunner = Callable[..., EngineeringSmokeRun]


def run_cli(
    argv: Sequence[str] | None = None,
    *,
    smoke_runner: SmokeRunner = run_engineering_smoke,
    runs_root: str | Path = RUNS_ROOT,
    clock: Callable[[], str] | None = None,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument(
        "--context-mode",
        choices=("simple", "retrieval"),
        default="simple",
    )
    parser.add_argument(
        "--allow-retained-swap",
        action="store_true",
        help="exploratory only: bypass the zero-swap preflight gate",
    )
    arguments = parser.parse_args(argv)

    issue = (FIXTURE_ROOT / "ISSUE.md").read_text(encoding="utf-8")
    tool_document = json.loads(TOOL_SCHEMAS.read_text(encoding="utf-8"))
    try:
        recorder = EngineeringSmokeRecorder.create(
            runs_root=runs_root,
            run_id=arguments.run_id,
            model=MODEL,
            context_mode=arguments.context_mode,
            allow_retained_swap=arguments.allow_retained_swap,
            case_id=CASE_ID,
            issue=issue,
            expected_changed_paths=EXPECTED_CHANGED_PATHS,
        )
    except EngineeringSmokeRecordError as exc:
        print(json.dumps({"error": str(exc), "code": "record_error"}, sort_keys=True))
        return 2

    try:
        smoke = smoke_runner(
            run_id=arguments.run_id,
            issue=issue,
            model=MODEL,
            fixture_root=FIXTURE_ROOT,
            expected_changed_paths=EXPECTED_CHANGED_PATHS,
            tool_document=tool_document,
            clock=(
                clock
                if clock is not None
                else lambda: datetime.now().astimezone().isoformat(timespec="microseconds")
            ),
            baseline_observer=recorder.record_baseline,
            context_mode=arguments.context_mode,
            allow_retained_swap=arguments.allow_retained_swap,
        )
    except SmokePreflightError as exc:
        recorder.record_error(state="blocked_preflight", code=exc.code, message=str(exc))
        print(f"ARTIFACT {recorder.directory}")
        print(json.dumps({"error": str(exc), "code": exc.code}, sort_keys=True))
        return 2
    except (CompatibilityError, ModelBackendError, ToolError, OSError, ValueError) as exc:
        recorder.record_error(
            state="setup_error",
            code=getattr(exc, "code", "setup_error"),
            message=str(exc),
        )
        print(f"ARTIFACT {recorder.directory}")
        print(json.dumps({"error": str(exc), "code": "setup_error"}, sort_keys=True))
        return 2

    print("BASELINE")
    print(
        json.dumps(
            {
                "swap_used_bytes": smoke.baseline.swap_used_bytes,
                "memory_free_percent": smoke.baseline.memory_free_percent,
                "loaded_models": list(smoke.baseline.loaded_models),
                "allow_retained_swap": arguments.allow_retained_swap,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    print("EVENTS")
    for event in smoke.result.events:
        print(event.to_json())
    print("OBSERVATIONS")
    for observation in smoke.result.observations:
        print(
            json.dumps(
                {
                    "content": observation.content,
                    "truncated": observation.truncated,
                    "metadata": observation.metadata_dict(),
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
    print("DIFF")
    print(smoke.diff, end="" if smoke.diff.endswith("\n") else "\n")
    print("RESULT")
    print(
        json.dumps(
            {
                "context_mode": smoke.context_mode,
                "solved": smoke.solved,
                "termination_reason": smoke.result.termination_reason.value,
                "first_context_chars": smoke.first_context_chars,
                "first_selected_paths": list(smoke.first_selected_paths),
                "changed_paths": list(smoke.changed_paths),
                "test_exit_codes": list(smoke.test_exit_codes),
                "source_unchanged": smoke.source_unchanged,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    exit_code = recorder.record_result(smoke)
    print(f"ARTIFACT {recorder.directory}")
    return exit_code


def main() -> int:
    return run_cli()


if __name__ == "__main__":
    raise SystemExit(main())
