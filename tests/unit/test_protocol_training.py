from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from localcode.protocol_training import (
    PROTOCOL_SYSTEM_PROMPT,
    ProtocolTrainingError,
    build_protocol_dataset,
    build_protocol_row,
)


def source_row(patch: str = "diff --git a/src/a.py b/src/a.py\n@@ -1 +1 @@\n-a\n+b\n") -> dict:
    return {
        "messages": [
            {"role": "system", "content": "old prompt"},
            {"role": "user", "content": "Issue and broken file"},
            {"role": "assistant", "content": patch},
        ]
    }


class ProtocolTrainingTests(unittest.TestCase):
    def test_row_wraps_diff_as_strict_apply_patch_decision(self) -> None:
        row = build_protocol_row(source_row())
        self.assertEqual(row["messages"][0]["content"], PROTOCOL_SYSTEM_PROMPT)
        target = json.loads(row["messages"][-1]["content"])
        self.assertEqual(target["decision"]["tool"], "apply_patch")
        self.assertEqual(target["decision"]["arguments"]["patch"].count("diff --git "), 1)

    def test_rejects_multi_file_or_non_diff_targets(self) -> None:
        with self.assertRaises(ProtocolTrainingError):
            build_protocol_row(source_row("not a patch"))
        with self.assertRaises(ProtocolTrainingError):
            build_protocol_row(source_row("diff --git a/a b/a\ndiff --git a/b b/b\n"))

    def test_dataset_preserves_splits_and_never_loads_sealed_data(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "source"
            output = Path(temporary) / "output"
            source.mkdir()
            for split in ("train", "valid"):
                (source / f"{split}.jsonl").write_text(json.dumps(source_row()) + "\n", encoding="utf-8")
            report = build_protocol_dataset(source_directory=source, output_directory=output)
            self.assertEqual(report["sealed_examples_loaded"], 0)
            self.assertEqual(report["splits"]["train"]["examples"], 1)
            self.assertEqual(json.loads((output / "train.jsonl").read_text())["messages"][0]["role"], "system")

    def test_registered_m020_data_has_protocol_targets_and_frozen_counts(self) -> None:
        root = Path(__file__).parents[2]
        config = json.loads((root / "benchmarks/training/m020_protocol_lora_v1.json").read_text())
        self.assertEqual(config["data_boundary"]["train_examples"], 326)
        self.assertEqual(config["data_boundary"]["validation_examples"], 58)
        self.assertEqual(config["sealed_examples_loaded"], 0)


if __name__ == "__main__":
    unittest.main()
