from __future__ import annotations

from dataclasses import FrozenInstanceError
import json
from pathlib import Path
import tempfile
import unittest

from localcode.training_data import (
    TrainingDataError,
    TrainingDataPolicy,
    TrainingExample,
    TrainingSplit,
    TrainingTask,
    assigned_split,
    evaluation_denylist_counts,
    load_training_jsonl,
    validate_training_corpus,
)


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "benchmarks/training_data/manifest_v1.json"


def example_document(
    policy: TrainingDataPolicy,
    *,
    example_id: str = "repair-example-001",
    lineage_id: str = "lineage-example-001",
    task_type: TrainingTask = TrainingTask.ISSUE_TO_DIFF,
    source_id: str = "source-example-001",
    source_revision: str = "a" * 40,
    input_text: str = "Parser crashes when the input is absent.",
    target_text: str | None = None,
    changed_paths: list[str] | None = None,
) -> dict[str, object]:
    paths = ["src/parser.py"] if changed_paths is None else changed_paths
    if target_text is None:
        target_text = (
            "diff --git a/src/parser.py b/src/parser.py\n"
            "--- a/src/parser.py\n"
            "+++ b/src/parser.py\n"
            "@@ -1 +1 @@\n"
            "-return text.strip()\n"
            "+return (text or '').strip()\n"
        )
    test_command = None
    test_exit_code = None
    if task_type is TrainingTask.TEST_FAILURE_TO_PATCH:
        test_command = "python -m unittest tests.test_parser"
        test_exit_code = 1
    return {
        "schema_version": 1,
        "example_id": example_id,
        "task_type": task_type.value,
        "lineage_id": lineage_id,
        "split": assigned_split(lineage_id, policy).value,
        "source_id": source_id,
        "source_repository": "example/parser",
        "source_revision": source_revision,
        "source_license": "Apache-2.0",
        "license_reviewed": True,
        "instruction": "Repair the described behavior and return the minimal implementation change.",
        "input_text": input_text,
        "target_text": target_text,
        "changed_paths": paths,
        "test_command": test_command,
        "test_exit_code": test_exit_code,
    }


class TrainingDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.policy = TrainingDataPolicy.from_path(MANIFEST)

    def test_registered_manifest_freezes_tasks_splits_and_eval_denylist(self) -> None:
        self.assertEqual(self.policy.dataset_id, "localcode-repair-training-v1")
        self.assertEqual(sum(self.policy.bucket_map().values()), 10_000)
        self.assertEqual(set(self.policy.task_types), set(TrainingTask))
        self.assertEqual(
            self.policy.evaluation_manifests,
            ("benchmarks/real_benchmark/manifest_v1.json",),
        )
        self.assertEqual(
            evaluation_denylist_counts(self.policy, project_root=ROOT),
            (20, 20),
        )

    def test_example_is_strict_immutable_and_canonical(self) -> None:
        example = TrainingExample.from_dict(example_document(self.policy))
        round_trip = TrainingExample.from_json(example.to_json())

        self.assertEqual(round_trip, example)
        self.assertEqual(json.loads(example.to_json()), example.to_dict())
        self.assertEqual(len(example.content_sha256()), 64)
        with self.assertRaises(FrozenInstanceError):
            example.example_id = "changed"  # type: ignore[misc]

        unknown = example_document(self.policy)
        unknown["gold_patch"] = "must never be accepted"
        with self.assertRaisesRegex(TrainingDataError, "fields must match"):
            TrainingExample.from_dict(unknown)
        with self.assertRaisesRegex(TrainingDataError, "duplicate JSON field"):
            TrainingExample.from_json('{"schema_version":1,"schema_version":1}')

    def test_patch_tasks_require_exact_declared_diff_paths(self) -> None:
        mismatch = example_document(self.policy, changed_paths=["src/other.py"])
        example = TrainingExample.from_dict(mismatch)
        with self.assertRaisesRegex(TrainingDataError, "diff paths"):
            validate_training_corpus((example,), self.policy, project_root=ROOT)

        failure = example_document(
            self.policy,
            task_type=TrainingTask.TEST_FAILURE_TO_PATCH,
        )
        failure["test_exit_code"] = 0
        with self.assertRaisesRegex(TrainingDataError, "failing test exit code"):
            TrainingExample.from_dict(failure)

    def test_all_four_task_types_form_one_valid_deterministic_corpus(self) -> None:
        records = []
        for index, task in enumerate(TrainingTask, 1):
            kwargs: dict[str, object] = {
                "example_id": f"repair-example-{index:03d}",
                "lineage_id": f"lineage-example-{index:03d}",
                "source_id": f"source-example-{index:03d}",
                "source_revision": f"{index:x}" * 40,
                "task_type": task,
                "input_text": f"Independent repair input {index}",
            }
            if task not in {TrainingTask.ISSUE_TO_DIFF, TrainingTask.TEST_FAILURE_TO_PATCH}:
                kwargs["target_text"] = f"def repaired_{index}():\n    return True\n"
            records.append(TrainingExample.from_dict(example_document(self.policy, **kwargs)))

        first = validate_training_corpus(records, self.policy, project_root=ROOT)
        second = validate_training_corpus(reversed(records), self.policy, project_root=ROOT)

        self.assertEqual(first.corpus_sha256, second.corpus_sha256)
        self.assertEqual(first.examples, 4)
        self.assertEqual(dict(first.task_counts), {task.value: 1 for task in TrainingTask})
        self.assertEqual(first.evaluation_ids_denied, 20)
        self.assertEqual(first.evaluation_revisions_denied, 20)

    def test_pinned_evaluation_ids_and_revisions_are_rejected(self) -> None:
        manifest = json.loads((ROOT / "benchmarks/real_benchmark/manifest_v1.json").read_text())
        pinned = manifest["instances"][0]
        leaked_id = TrainingExample.from_dict(
            example_document(self.policy, source_id=pinned["instance_id"])
        )
        with self.assertRaisesRegex(TrainingDataError, "evaluation ID"):
            validate_training_corpus((leaked_id,), self.policy, project_root=ROOT)

        leaked_revision = TrainingExample.from_dict(
            example_document(self.policy, source_revision=pinned["base_commit"])
        )
        with self.assertRaisesRegex(TrainingDataError, "evaluation revision"):
            validate_training_corpus((leaked_revision,), self.policy, project_root=ROOT)

    def test_exact_content_cannot_cross_splits_even_with_different_lineages(self) -> None:
        by_split: dict[TrainingSplit, str] = {}
        index = 0
        while len(by_split) < 2:
            lineage = f"overlap-lineage-{index:04d}"
            by_split.setdefault(assigned_split(lineage, self.policy), lineage)
            index += 1
        first_lineage, second_lineage = list(by_split.values())[:2]
        first = TrainingExample.from_dict(
            example_document(
                self.policy,
                example_id="overlap-example-001",
                lineage_id=first_lineage,
                source_id="overlap-source-001",
            )
        )
        second = TrainingExample.from_dict(
            example_document(
                self.policy,
                example_id="overlap-example-002",
                lineage_id=second_lineage,
                source_id="overlap-source-002",
                source_revision="b" * 40,
            )
        )
        with self.assertRaisesRegex(TrainingDataError, "exact input content crosses splits"):
            validate_training_corpus((first, second), self.policy, project_root=ROOT)

    def test_jsonl_loader_rejects_blank_and_reports_line_number(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "examples.jsonl"
            path.write_text(TrainingExample.from_dict(example_document(self.policy)).to_json() + "\n\n")
            with self.assertRaisesRegex(TrainingDataError, "blank JSONL record at line 2"):
                load_training_jsonl(path)

    def test_unreviewed_license_and_wrong_split_are_rejected(self) -> None:
        unreviewed = example_document(self.policy)
        unreviewed["license_reviewed"] = False
        with self.assertRaisesRegex(TrainingDataError, "license is not reviewed"):
            validate_training_corpus(
                (TrainingExample.from_dict(unreviewed),),
                self.policy,
                project_root=ROOT,
            )

        wrong = example_document(self.policy)
        actual = TrainingSplit(wrong["split"])
        wrong["split"] = next(split.value for split in TrainingSplit if split is not actual)
        with self.assertRaisesRegex(TrainingDataError, "must be in"):
            validate_training_corpus(
                (TrainingExample.from_dict(wrong),),
                self.policy,
                project_root=ROOT,
            )


if __name__ == "__main__":
    unittest.main()
