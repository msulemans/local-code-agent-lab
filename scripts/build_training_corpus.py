#!/usr/bin/env python3
"""Verify and normalize the pinned CommitPackFT Python training shard."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from localcode.training_data import TrainingDataError, TrainingDataPolicy
from localcode.training_sources import build_commitpackft_corpus, load_sources, verify_artifact


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-manifest", default=str(ROOT / "benchmarks/training_data/sources_v1.json"))
    parser.add_argument("--policy", default=str(ROOT / "benchmarks/training_data/manifest_v1.json"))
    parser.add_argument("--raw", default=str(ROOT / "data/raw/commitpackft-python-v1.jsonl"))
    parser.add_argument("--output", default=str(ROOT / "data/processed/repair-training-v1.jsonl"))
    parser.add_argument("--report", default=str(ROOT / "data/processed/repair-training-v1-report.json"))
    arguments = parser.parse_args()
    try:
        sources = load_sources(arguments.source_manifest)
        if len(sources) != 1:
            raise TrainingDataError("source_count", "builder v1 requires exactly one registered source")
        source = sources[0]
        verify_artifact(arguments.raw, source)
        with Path(arguments.raw).open(encoding="utf-8") as lines:
            examples, summary = build_commitpackft_corpus(
                lines,
                source=source,
                policy=TrainingDataPolicy.from_path(arguments.policy),
                project_root=ROOT,
            )
        output = Path(arguments.output)
        report = Path(arguments.report)
        output.parent.mkdir(parents=True, exist_ok=True)
        report.parent.mkdir(parents=True, exist_ok=True)
        output.write_text("".join(example.to_json() + "\n" for example in examples), encoding="utf-8")
        report.write_text(json.dumps(summary.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except (OSError, TrainingDataError) as exc:
        code = exc.code if isinstance(exc, TrainingDataError) else "filesystem"
        print(json.dumps({"status": "invalid", "code": code, "error": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps({**summary.to_dict(), "status": "corpus_built"}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
