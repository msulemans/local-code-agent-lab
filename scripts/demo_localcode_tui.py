#!/usr/bin/env python3
"""Render the fake parser repair run through the LocalCode terminal UI."""

from __future__ import annotations

import sys

from localcode.demo_repair import PARSER_FIXTURE, run_parser_repair_demo
from localcode.tui import TerminalEventStream, TerminalRenderer


RUN_ID = "demo-localcode-tui"


def main() -> int:
    issue = (PARSER_FIXTURE / "ISSUE.md").read_text(encoding="utf-8")
    renderer = TerminalRenderer(sys.stdout)
    stream = TerminalEventStream(renderer)
    stream.start(run_id=RUN_ID, issue=issue)
    demo = run_parser_repair_demo(run_id=RUN_ID, observer=stream)
    stream.finish(
        demo.result,
        final_diff=demo.final_diff,
        source_fixture_unchanged=demo.source_fixture_unchanged,
    )
    return 0 if demo.result.final_answer is not None and demo.source_fixture_unchanged else 1


if __name__ == "__main__":
    raise SystemExit(main())
