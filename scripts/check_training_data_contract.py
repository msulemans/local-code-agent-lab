#!/usr/bin/env python3
"""Validate the Phase 4 training manifest and an optional JSONL corpus."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from localcode.training_data import (
    TrainingDataError,
    TrainingDataPolicy,
    evaluation_denylist_counts,
    load_training_jsonl,
    validate_training_corpus,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "benchmarks/training_data/manifest_v1.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--corpus", default=None, help="optional prepared training JSONL")
    arguments = parser.parse_args()
    try:
        policy = TrainingDataPolicy.from_path(arguments.manifest)
        if arguments.corpus is None:
            denied_ids, denied_revisions = evaluation_denylist_counts(
                policy,
                project_root=ROOT,
            )
            summary = {
                "dataset_id": policy.dataset_id,
                "schema_version": policy.schema_version,
                "split_seed": policy.split_seed,
                "split_buckets": {split.value: size for split, size in policy.split_buckets},
                "task_types": [task.value for task in policy.task_types],
                "evaluation_manifests": list(policy.evaluation_manifests),
                "evaluation_ids_denied": denied_ids,
                "evaluation_revisions_denied": denied_revisions,
                "status": "contract_ready_no_corpus",
            }
        else:
            examples = load_training_jsonl(arguments.corpus)
            summary = validate_training_corpus(examples, policy, project_root=ROOT).to_dict()
            summary["status"] = "corpus_valid"
    except TrainingDataError as exc:
        print(json.dumps({"status": "invalid", "code": exc.code, "error": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
