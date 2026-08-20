#!/usr/bin/env python3
"""Build the pinned M016b SWE-smith issue-to-repair corpus."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from localcode.executable_training import ExecutableSource, build_executable_corpus
from localcode.training_data import TrainingDataPolicy


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", default=str(ROOT / "data/raw/swe-smith-py-train-00000.parquet"))
    parser.add_argument("--policy", default=str(ROOT / "benchmarks/training_data/manifest_v2.json"))
    parser.add_argument("--sources", default=str(ROOT / "benchmarks/training_data/sources_v2.json"))
    parser.add_argument("--output", default=str(ROOT / "data/processed/executable-repair-v2.jsonl"))
    parser.add_argument("--report", default=str(ROOT / "data/processed/executable-repair-v2-report.json"))
    arguments = parser.parse_args()

    source_document = json.loads(Path(arguments.sources).read_text(encoding="utf-8"))
    source = ExecutableSource.from_document(source_document)
    raw = Path(arguments.raw)
    if raw.stat().st_size != source.artifact_bytes:
        raise SystemExit("pinned SWE-smith shard byte size mismatch")
    if hashlib.sha256(raw.read_bytes()).hexdigest() != source.artifact_sha256:
        raise SystemExit("pinned SWE-smith shard SHA-256 mismatch")

    try:
        import pyarrow.parquet as parquet
    except ImportError as exc:
        raise SystemExit("pyarrow is required; run with .venv-realbench/bin/python") from exc
    table = parquet.read_table(raw)
    rows = ({name: table[name][index].as_py() for name in table.column_names}
            for index in range(table.num_rows))
    examples, summary = build_executable_corpus(
        rows,
        source=source,
        policy=TrainingDataPolicy.from_path(arguments.policy),
        project_root=str(ROOT),
    )
    output = Path(arguments.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("".join(example.to_json() + "\n" for example in examples), encoding="utf-8")
    report = summary.to_dict()
    report.update({
        "schema_version": 1,
        "source_id": source.source_id,
        "source_revision": source.dataset_revision,
        "source_sha256": source.artifact_sha256,
        "sealed_examples_loaded_for_training": 0,
    })
    Path(arguments.report).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
