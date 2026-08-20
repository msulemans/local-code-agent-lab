from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from localcode.training_data import TrainingDataError, TrainingDataPolicy, TrainingExample, assigned_split
from localcode.training_export import SYSTEM_PROMPT, export_mlx_chat_data


ROOT = Path(__file__).resolve().parents[2]
POLICY = TrainingDataPolicy.from_path(ROOT / "benchmarks/training_data/manifest_v1.json")


def example_for_split(target_split: str, *, suffix: str) -> TrainingExample:
    index = 0
    while True:
        lineage = f"export-lineage-{suffix}-{index:04d}"
        if assigned_split(lineage, POLICY).value == target_split:
            break
        index += 1
    return TrainingExample.from_dict(
        {
            "schema_version": 1,
            "example_id": f"export-example-{suffix}",
            "task_type": "broken_to_corrected",
            "lineage_id": lineage,
            "split": target_split,
            "source_id": f"export-source-{suffix}",
            "source_repository": "example/repair",
            "source_revision": suffix[0] * 40,
            "source_license": "mit",
            "license_reviewed": True,
            "instruction": f"Repair example {suffix}",
            "input_text": f"value = '{suffix}-broken'\n",
            "target_text": f"value = '{suffix}-fixed'\n",
            "changed_paths": [f"src/{suffix}.py"],
            "test_command": None,
            "test_exit_code": None,
        }
    )


class TrainingExportTests(unittest.TestCase):
    def test_export_writes_only_train_and_validation_chat_rows(self) -> None:
        examples = (
            example_for_split("train", suffix="aaa"),
            example_for_split("validation", suffix="bbb"),
            example_for_split("sealed_test", suffix="ccc"),
        )
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "mlx"
            evaluation = Path(temporary) / "validation-eval"
            summary = export_mlx_chat_data(
                reversed(examples),
                output_directory=output,
                validation_evaluation_directory=evaluation,
            )
            self.assertEqual(sorted(path.name for path in output.iterdir()), ["train.jsonl", "valid.jsonl"])
            self.assertEqual(sorted(path.name for path in evaluation.iterdir()), ["README.txt", "test.jsonl"])
            self.assertEqual(
                (evaluation / "test.jsonl").read_text(),
                (output / "valid.jsonl").read_text(),
            )
            self.assertIn("not the sealed-test split", (evaluation / "README.txt").read_text())
            self.assertEqual(summary.train_examples, 1)
            self.assertEqual(summary.validation_examples, 1)
            self.assertEqual(summary.sealed_examples_withheld, 1)
            self.assertEqual(summary.sealed_examples_exported, 0)
            train = json.loads((output / "train.jsonl").read_text())
            self.assertEqual(train["messages"][0], {"role": "system", "content": SYSTEM_PROMPT})
            self.assertEqual(train["messages"][-1]["content"], "value = 'aaa-fixed'\n")

    def test_export_is_order_independent_and_rejects_unsupported_task(self) -> None:
        train = example_for_split("train", suffix="ddd")
        valid = example_for_split("validation", suffix="eee")
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            first_summary = export_mlx_chat_data((train, valid), output_directory=first)
            second_summary = export_mlx_chat_data((valid, train), output_directory=second)
            self.assertEqual(first_summary, second_summary)

        document = train.to_dict()
        document["task_type"] = "function_to_implementation"
        unsupported = TrainingExample.from_dict(document)
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(TrainingDataError, "does not format"):
                export_mlx_chat_data((unsupported, valid), output_directory=temporary)


if __name__ == "__main__":
    unittest.main()
