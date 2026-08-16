#!/usr/bin/env python3
"""Print the loop context produced by the retrieval context treatment."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from localcode.context import ContextRequest, RetrievalContextCompiler
from localcode.micro_suite import load_micro_suite


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "benchmarks/micro_agent/suite_v1.json"
SCHEMAS = ROOT / "benchmarks/micro_agent/tool_schemas.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", default="parser-none", help="registered micro-suite case id")
    parser.add_argument("--max-files", type=int, default=3)
    parser.add_argument("--max-context-chars", type=int, default=4_000)
    args = parser.parse_args()

    suite = load_micro_suite(MANIFEST, SCHEMAS, ROOT)
    cases = {case.case_id: case for case in suite.cases}
    if args.case not in cases:
        parser.error(f"unknown case: {args.case}")
    case = cases[args.case]
    issue = (case.fixture / case.issue_file).read_text(encoding="utf-8")
    context = RetrievalContextCompiler(case.fixture, max_files=args.max_files).compile(
        ContextRequest(
            issue=issue,
            history=(),
            budgets_remaining=(("invalid_actions", 3), ("tool_calls", 6), ("turns", 8)),
            max_chars=args.max_context_chars,
        )
    )
    payload = json.loads(context)
    evidence = payload["retrieved_evidence"]
    print(f"CASE {case.case_id}")
    print(f"CONTEXT_CHARS {len(context)}")
    print("SELECTED " + ", ".join(evidence["selected_paths"]))
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
