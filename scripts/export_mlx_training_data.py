#!/usr/bin/env python3
"""Export the verified repair corpus to MLX-LM chat JSONL development splits."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from localcode.training_data import TrainingDataError, load_training_jsonl
from localcode.training_export import export_mlx_chat_data


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", default=str(ROOT / "data/processed/repair-training-v1.jsonl"))
    parser.add_argument("--output", default=str(ROOT / "data/processed/mlx-m015"))
    parser.add_argument(
        "--validation-evaluation-output",
        default=str(ROOT / "data/processed/mlx-m015-validation-eval"),
    )
    parser.add_argument("--report", default=str(ROOT / "data/processed/mlx-m015-export.json"))
    arguments = parser.parse_args()
    try:
        summary = export_mlx_chat_data(
            load_training_jsonl(arguments.corpus),
            output_directory=arguments.output,
            validation_evaluation_directory=arguments.validation_evaluation_output,
        )
        report = Path(arguments.report)
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(summary.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except (OSError, TrainingDataError) as exc:
        code = exc.code if isinstance(exc, TrainingDataError) else "filesystem"
        print(json.dumps({"status": "invalid", "code": code, "error": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps({**summary.to_dict(), "status": "mlx_data_ready"}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
