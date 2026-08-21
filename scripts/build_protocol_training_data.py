#!/usr/bin/env python3
"""Build the protocol-aligned MLX training treatment without sealed data."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from localcode.protocol_training import ProtocolTrainingError, build_protocol_dataset


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default=str(ROOT / "data/processed/mlx-m016b-768"))
    parser.add_argument("--output", default=str(ROOT / "data/processed/mlx-m020-protocol-768"))
    parser.add_argument("--model", default=str(ROOT / "models/qwen25-coder-7b-instruct-4bit"))
    parser.add_argument("--max-sequence-tokens", type=int, default=768)
    arguments = parser.parse_args()
    try:
        from transformers import AutoTokenizer

        tokenizer = AutoTokenizer.from_pretrained(arguments.model, trust_remote_code=True)
        report = build_protocol_dataset(
            source_directory=arguments.source,
            output_directory=arguments.output,
            tokenizer=tokenizer,
            max_sequence_tokens=arguments.max_sequence_tokens,
        )
    except (OSError, ImportError, ProtocolTrainingError) as exc:
        print(json.dumps({"status": "invalid", "error": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps({"status": "protocol_dataset_built", **report}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
