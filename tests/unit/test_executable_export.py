from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from localcode.executable_export import SYSTEM_PROMPT, export_executable_mlx
from localcode.training_data import TrainingDataPolicy, TrainingExample, TrainingSplit, assigned_split


ROOT = Path(__file__).resolve().parents[2]
POLICY = TrainingDataPolicy.from_path(ROOT / "benchmarks/training_data/manifest_v2.json")


def example(example_id: str, wanted_split: TrainingSplit) -> TrainingExample:
    index = 0
    while True:
        lineage = f"export-lineage-{wanted_split.value}-{index}"
        if assigned_split(lineage, POLICY) is wanted_split:
            break
        index += 1
    return TrainingExample.from_dict({
        "schema_version": 1,
        "example_id": example_id,
        "task_type": "issue_to_diff",
        "lineage_id": lineage,
        "split": wanted_split.value,
        "source_id": f"source-{example_id}",
        "source_repository": "example/project",
        "source_revision": "a" * 40,
        "source_license": "MIT",
        "license_reviewed": True,
        "instruction": f"Repair {example_id}",
        "input_text": "Failing tests:\n- tests/test_one.py\n\nBroken repository excerpts:\n! bad",
        "target_text": (
            "diff --git a/src/one.py b/src/one.py\n--- a/src/one.py\n+++ b/src/one.py\n"
            "@@ -1 +1 @@\n-bad\n+good\n"
        ),
        "changed_paths": ["src/one.py"],
        "test_command": "pytest tests/test_one.py",
        "test_exit_code": 1,
    })


class ExecutableExportTests(unittest.TestCase):
    def test_export_skips_sealed_before_tokenization_and_bounds_sequences(self) -> None:
        train = example("export-train", TrainingSplit.TRAIN)
        validation = example("export-validation", TrainingSplit.VALIDATION)
        sealed = example("export-sealed", TrainingSplit.SEALED_TEST)
        seen = []

        def count(messages):
            seen.append(messages[1]["content"])
            return 100

        with tempfile.TemporaryDirectory() as temporary:
            summary = export_executable_mlx(
                [sealed, validation, train], output_directory=temporary, token_counter=count
            )
            self.assertEqual(summary.train_examples, 1)
            self.assertEqual(summary.validation_examples, 1)
            self.assertEqual(summary.sealed_examples_withheld, 1)
            self.assertEqual(summary.sealed_examples_tokenized, 0)
            self.assertEqual(len(seen), 2)
            self.assertFalse(any("export-sealed" in prompt for prompt in seen))
            row = json.loads((Path(temporary) / "train.jsonl").read_text())
            self.assertEqual(row["messages"][0]["content"], SYSTEM_PROMPT)


if __name__ == "__main__":
    unittest.main()
