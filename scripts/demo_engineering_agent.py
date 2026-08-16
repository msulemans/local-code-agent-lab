#!/usr/bin/env python3
"""Solve the parser fixture with the complete fake-model engineering loop."""

from __future__ import annotations

import json

from localcode.demo_repair import run_parser_repair_demo


def main() -> int:
    demo = run_parser_repair_demo()

    print("TRACE")
    for event in demo.result.events:
        print(f"{event.sequence:02d} {event.state:10s} {event.event_type.value:18s} {event.summary}")
    print("TEST EVIDENCE")
    print(json.dumps(dict(demo.test_metadata), sort_keys=True))
    print("DIFF")
    print(demo.final_diff)
    print("FINAL")
    print(demo.result.final_answer)
    print("TERMINATION")
    print(demo.result.termination_reason.value)
    print("SOURCE FIXTURE UNCHANGED")
    print(demo.source_fixture_unchanged)
    return 0 if demo.result.final_answer is not None and demo.source_fixture_unchanged else 1


if __name__ == "__main__":
    raise SystemExit(main())
