#!/usr/bin/env python3
"""Select and freeze a reproducible 20-instance SWE-bench manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def load_rows(path: Path) -> list[dict[str, object]]:
    if path.suffix == ".jsonl":
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    elif path.suffix == ".json":
        rows = json.loads(path.read_text(encoding="utf-8"))
    else:
        raise SystemExit("dataset must be a JSON or JSONL snapshot; convert parquet first")
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise SystemExit("dataset snapshot must contain a list of objects")
    return rows


def rank(seed: int, instance_id: str) -> bytes:
    return hashlib.sha256(f"{seed}:{instance_id}".encode("utf-8")).digest()


def select(rows: list[dict[str, object]], *, seed: int, count: int, cap: int) -> list[dict[str, object]]:
    candidates = [
        row for row in rows
        if isinstance(row.get("instance_id"), str)
        and isinstance(row.get("repo"), str)
        and isinstance(row.get("base_commit"), str)
        and isinstance(row.get("problem_statement"), str)
    ]
    by_repo: dict[str, list[dict[str, object]]] = {}
    for row in candidates:
        by_repo.setdefault(str(row["repo"]), []).append(row)
    for repo_rows in by_repo.values():
        repo_rows.sort(key=lambda row: rank(seed, str(row["instance_id"])))
    selected: list[dict[str, object]] = []
    used: dict[str, int] = {}
    while len(selected) < count:
        progressed = False
        for repo in sorted(by_repo):
            if used.get(repo, 0) >= cap or not by_repo[repo]:
                continue
            selected.append(by_repo[repo].pop(0))
            used[repo] = used.get(repo, 0) + 1
            progressed = True
            if len(selected) == count:
                break
        if not progressed:
            raise SystemExit("not enough eligible rows for the requested subset")
    return selected


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--dataset-name", default="SWE-bench/SWE-bench_Verified")
    parser.add_argument("--dataset-split", default="test")
    parser.add_argument("--dataset-revision", required=True)
    parser.add_argument("--seed", type=int, default=20260813)
    parser.add_argument("--count", type=int, default=20)
    parser.add_argument("--max-per-repository", type=int, default=5)
    arguments = parser.parse_args()
    rows = select(
        load_rows(Path(arguments.dataset)),
        seed=arguments.seed,
        count=arguments.count,
        cap=arguments.max_per_repository,
    )
    document = {
        "schema_version": 1,
        "subset_id": "swebench-verified-pinned20-v1",
        "dataset": {
            "name": arguments.dataset_name,
            "split": arguments.dataset_split,
            "revision": arguments.dataset_revision,
        },
        "selection": {
            "seed": arguments.seed,
            "max_per_repository": arguments.max_per_repository,
            "compatibility_filters": [
                "verified test split",
                "Python repositories",
                "gold control required before scoring",
                "ARM64 environment compatibility required",
            ],
        },
        "fairness_controls": [
            "Same pinned instance IDs and base commits",
            "Same model checkpoint, quantization, backend, and seed",
            "Same generated-token, tool-call, test, patch, and wall budgets",
            "Same network policy and Docker evaluator resources",
            "Gold and evaluator-only fields are hidden from agent context",
            "Every configuration runs against the same ordered 20 instances",
        ],
        "configurations": [
            {"id": "B0", "label": "Single-shot base", "change": "Issue plus bounded map; one patch", "kind": "single_shot_base", "availability": "implemented"},
            {"id": "A1", "label": "Simple agent", "change": "+ typed tools and bounded retry loop", "kind": "simple_agent", "availability": "implemented"},
            {"id": "A2", "label": "Retrieval agent", "change": "+ ranked repository context", "kind": "retrieval_agent", "availability": "implemented"},
            {"id": "A3", "label": "Agent plus review", "change": "+ one fresh critique and revision", "kind": "agent_plus_review", "availability": "implemented"},
        ],
        "instances": [
            {
                "instance_id": row["instance_id"],
                "repository": row["repo"],
                "base_commit": row["base_commit"],
            }
            for row in rows
        ],
    }
    output = Path(arguments.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(document, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "instances": len(rows), "repositories": sorted({row["repo"] for row in rows})}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
