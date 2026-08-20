#!/usr/bin/env python3
"""Export the M016b corpus under a declared pinned-Qwen token ceiling."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from localcode.executable_export import export_executable_mlx
from localcode.training_data import load_training_jsonl


ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = ROOT / "models/qwen25-coder-1.5b-instruct-m015"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", default=str(ROOT / "data/processed/executable-repair-v2.jsonl"))
    parser.add_argument("--output", default=str(ROOT / "data/processed/mlx-m016b"))
    parser.add_argument("--report", default=str(ROOT / "data/processed/mlx-m016b-report.json"))
    parser.add_argument("--maximum-sequence-tokens", type=int, default=1024)
    arguments = parser.parse_args()
    if Path(sys.prefix).resolve() != (ROOT / ".venv-mlx").resolve():
        raise SystemExit("M016b export must run with .venv-mlx/bin/python")

    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(str(MODEL_PATH), local_files_only=True)

    def count(messages: tuple[dict[str, str], ...]) -> int:
        encoded = tokenizer.apply_chat_template(list(messages), tokenize=True, return_dict=True)
        return len(encoded["input_ids"])

    summary = export_executable_mlx(
        load_training_jsonl(arguments.corpus),
        output_directory=arguments.output,
        token_counter=count,
        maximum_sequence_tokens=arguments.maximum_sequence_tokens,
    )
    report = summary.to_dict()
    report.update({
        "schema_version": 1,
        "model": "Qwen/Qwen2.5-Coder-1.5B-Instruct",
        "model_revision": "cc932d8a05bf5a3dcd700f50584714d17fc4d03a",
        "sealed_examples_loaded_for_training": 0,
    })
    Path(arguments.report).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
