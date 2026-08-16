#!/usr/bin/env python3
"""Run the registered Milestone 007 micro suite through the guarded runtime."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from localcode.micro_suite import load_micro_suite, run_micro_suite


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--context-mode",
        choices=("simple", "retrieval", "single_shot"),
        default="simple",
        help="run the simple loop, retrieval loop, or true one-shot baseline",
    )
    args = parser.parse_args()
    suite = load_micro_suite(
        ROOT / "benchmarks/micro_agent/suite_v1.json",
        ROOT / "benchmarks/micro_agent/tool_schemas.json",
        ROOT,
    )
    result = run_micro_suite(suite, context_mode=args.context_mode)
    for case in result.cases:
        status = "PASS" if case.success else "FAIL"
        print(
            f"{status} {case.case_id} category={case.category} "
            f"context={case.context_mode} context_chars={case.first_context_chars} "
            f"selected={list(case.first_selected_paths)} "
            f"errors={list(case.observation_error_codes)} "
            f"tests={list(case.test_exit_codes)} paths={list(case.changed_paths)} "
            f"termination={case.termination_reason.value} source_unchanged={case.source_unchanged}"
        )
    print(
        "SUMMARY "
        + json.dumps(
            {
                "context_mode": result.context_mode,
                "suite_id": result.suite_id,
                "registered": result.registered,
                "solved": result.solved,
                "minimum_solved": result.minimum_solved,
                "milestone_ready": result.milestone_ready,
            },
            sort_keys=True,
        )
    )
    return 0 if result.milestone_ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
