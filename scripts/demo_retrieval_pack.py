#!/usr/bin/env python3
"""Print the deterministic retrieval pack for one registered micro case."""

from __future__ import annotations

import argparse
from pathlib import Path

from localcode.micro_suite import load_micro_suite
from localcode.retrieval import evaluate_relevant_file_recall, select_retrieval_evidence


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "benchmarks/micro_agent/suite_v1.json"
SCHEMAS = ROOT / "benchmarks/micro_agent/tool_schemas.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", default="parser-none", help="registered micro-suite case id")
    parser.add_argument("--max-files", type=int, default=3)
    parser.add_argument("--max-total-chars", type=int, default=3_000)
    args = parser.parse_args()

    suite = load_micro_suite(MANIFEST, SCHEMAS, ROOT)
    cases = {case.case_id: case for case in suite.cases}
    if args.case not in cases:
        parser.error(f"unknown case: {args.case}")
    case = cases[args.case]
    issue = (case.fixture / case.issue_file).read_text(encoding="utf-8")
    pack = select_retrieval_evidence(
        case.fixture,
        issue,
        max_files=args.max_files,
        max_total_chars=args.max_total_chars,
    )
    recall = evaluate_relevant_file_recall(pack, case.expected_changed_paths)

    print(f"CASE {case.case_id}")
    print(f"EXPECTED {', '.join(case.expected_changed_paths)}")
    print(f"RECALL {recall.numerator}/{recall.denominator}")
    print("SELECTED")
    for excerpt in pack.excerpts:
        print(
            f"- {excerpt.path} score={excerpt.score} reason={excerpt.reason} "
            f"lines={excerpt.start_line}-{excerpt.end_line}"
        )
    print("CONTEXT")
    print(pack.to_context())
    return 0 if recall.numerator == recall.denominator else 1


if __name__ == "__main__":
    raise SystemExit(main())
