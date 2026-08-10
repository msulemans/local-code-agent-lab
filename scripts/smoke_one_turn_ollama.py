#!/usr/bin/env python3
"""Run the single bounded Qwen3.5 smoke turn after a clean-host preflight."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path

from localcode.compatibility import CompatibilityError
from localcode.events import EventType
from localcode.preflight import SmokePreflightError
from localcode.smoke import run_one_turn_smoke


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = REPOSITORY_ROOT / "tests/fixtures/micro_repos/parser_none"
TOOL_SCHEMAS = REPOSITORY_ROOT / "benchmarks/model_compatibility/tool_schemas.json"
MODEL = "qwen3.5:9b-q4_K_M"
ISSUE = "Parser crashes when given None. Inspect the repository for the relevant definition."


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    arguments = parser.parse_args()

    tool_document = json.loads(TOOL_SCHEMAS.read_text(encoding="utf-8"))
    try:
        smoke = run_one_turn_smoke(
            run_id=arguments.run_id,
            issue=ISSUE,
            model=MODEL,
            repository_root=FIXTURE_ROOT,
            tool_document=tool_document,
            clock=lambda: datetime.now().astimezone().isoformat(timespec="microseconds"),
        )
    except (SmokePreflightError, CompatibilityError) as exc:
        code = getattr(exc, "code", "backend_error")
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
    return 0 if smoke.result.events[-1].event_type is EventType.TOOL_RESULT else 1


if __name__ == "__main__":
    raise SystemExit(main())
