#!/usr/bin/env python3
"""Measure M015 development token lengths using only the pinned local tokenizer."""

from __future__ import annotations

import json
from pathlib import Path
import sys

from transformers import AutoTokenizer


ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / "models/qwen25-coder-1.5b-instruct-m015"
DATA = ROOT / "data/processed/mlx-m015"
REPORT = ROOT / "data/processed/mlx-m015-token-lengths.json"


def main() -> int:
    if Path(sys.prefix).resolve() != (ROOT / ".venv-mlx").resolve():
        raise SystemExit("token inspection must run with .venv-mlx/bin/python")
    tokenizer = AutoTokenizer.from_pretrained(MODEL, local_files_only=True)
    splits = {}
    for filename, label in (("train.jsonl", "train"), ("valid.jsonl", "validation")):
        lengths = []
        with (DATA / filename).open(encoding="utf-8") as handle:
            for line in handle:
                messages = json.loads(line)["messages"]
                encoded = tokenizer.apply_chat_template(
                    messages,
                    tokenize=True,
                    add_generation_prompt=False,
                )
                lengths.append(len(encoded["input_ids"]))
        lengths.sort()
        percentile = lambda value: lengths[min(len(lengths) - 1, int((len(lengths) - 1) * value))]
        splits[label] = {
            "rows": len(lengths),
            "minimum": lengths[0],
            "p50": percentile(0.50),
            "p90": percentile(0.90),
            "p95": percentile(0.95),
            "p99": percentile(0.99),
            "maximum": lengths[-1],
            "over_1024": sum(length > 1024 for length in lengths),
        }
    report = {
        "model": "Qwen/Qwen2.5-Coder-1.5B-Instruct",
        "sealed_examples_loaded": 0,
        "splits": splits,
    }
    REPORT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
