from __future__ import annotations

import json
from pathlib import Path
import unittest

from localcode.executable_training import (
    ExecutableSource,
    build_executable_corpus,
    reverse_mutation_patch,
)
from localcode.training_data import TrainingDataError, TrainingDataPolicy


ROOT = Path(__file__).resolve().parents[2]
POLICY = TrainingDataPolicy.from_path(ROOT / "benchmarks/training_data/manifest_v2.json")
SOURCE = ExecutableSource.from_document(json.loads(
    (ROOT / "benchmarks/training_data/sources_v2.json").read_text(encoding="utf-8")
))


def row(instance: str = "oauthlib__oauthlib.1fd52536.mutation__one") -> dict[str, object]:
    return {
        "instance_id": instance,
        "patch": (
            "diff --git a/oauthlib/utils.py b/oauthlib/utils.py\n"
            "index 1111111..2222222 100644\n"
            "--- a/oauthlib/utils.py\n"
            "+++ b/oauthlib/utils.py\n"
            "@@ -1,2 +1,2 @@\n"
            " def normalize(value):\n"
            "-    return value.strip()\n"
            "+    return value\n"
        ),
        "FAIL_TO_PASS": ["tests/test_utils.py::test_normalize"],
        "PASS_TO_PASS": ["tests/test_utils.py::test_other"],
        "image_name": "swebench/swesmith.x86_64.oauthlib",
        "repo": "swesmith/oauthlib__oauthlib.1fd52536",
        "problem_statement": "normalize() no longer strips surrounding whitespace",
    }


class ExecutableTrainingTests(unittest.TestCase):
    def test_versioned_m016b_result_pins_real_build_and_export(self) -> None:
        result = json.loads(
            (ROOT / "benchmarks/training/m016b_data_v1.json").read_text(encoding="utf-8")
        )
        self.assertEqual(result["source"]["raw_records"], 4628)
        self.assertEqual(result["normalization"]["selected_records"], 1553)
        self.assertEqual(result["mlx_export"]["train_examples"], 755)
        self.assertEqual(result["mlx_export"]["validation_examples"], 131)
        self.assertEqual(result["mlx_export"]["sealed_examples_tokenized"], 0)
        self.assertFalse(result["development_gate"]["suite_examples_allowed_in_training"])

    def test_reverse_patch_restores_fix_without_leaking_removed_line(self) -> None:
        repair, paths, broken = reverse_mutation_patch(row()["patch"])
        self.assertEqual(paths, ("oauthlib/utils.py",))
        self.assertIn("-    return value\n+    return value.strip()", repair)
        self.assertIn("!     return value", broken)
        self.assertNotIn("return value.strip()", broken)

    def test_builder_records_executable_evidence_and_is_deterministic(self) -> None:
        first, first_summary = build_executable_corpus(
            [row()], source=SOURCE, policy=POLICY, project_root=str(ROOT)
        )
        second, second_summary = build_executable_corpus(
            [row()], source=SOURCE, policy=POLICY, project_root=str(ROOT)
        )
        self.assertEqual(first, second)
        self.assertEqual(first_summary, second_summary)
        self.assertEqual(first[0].test_exit_code, 1)
        self.assertIn("FAIL_TO_PASS", first[0].test_command)
        self.assertEqual(first[0].source_license, "BSD-3-Clause")
        self.assertEqual(first_summary.selected_records, 1)

    def test_builder_rejects_unreviewed_repo_multifile_and_missing_tests(self) -> None:
        unreviewed = row()
        unreviewed["repo"] = "swesmith/agronholm__typeguard.b6a7e438"
        no_tests = row("oauthlib__oauthlib.1fd52536.mutation__two")
        no_tests["FAIL_TO_PASS"] = []
        multi = row("oauthlib__oauthlib.1fd52536.mutation__three")
        multi["patch"] += multi["patch"].replace("oauthlib/utils.py", "oauthlib/other.py")
        _, summary = build_executable_corpus(
            [unreviewed, no_tests, multi, row()],
            source=SOURCE,
            policy=POLICY,
            project_root=str(ROOT),
        )
        rejected = dict(summary.rejection_counts)
        self.assertEqual(rejected["license"], 1)
        self.assertEqual(rejected["test_evidence"], 1)
        self.assertEqual(rejected["path_count"], 1)

    def test_reverse_patch_rejects_file_creation_and_non_python(self) -> None:
        creation = (
            "diff --git a/new.py b/new.py\nnew file mode 100644\n"
            "--- /dev/null\n+++ b/new.py\n@@ -0,0 +1 @@\n+value = 1\n"
        )
        with self.assertRaisesRegex(TrainingDataError, "modifications"):
            reverse_mutation_patch(creation)
        with self.assertRaisesRegex(TrainingDataError, "Python"):
            reverse_mutation_patch(row()["patch"].replace("utils.py", "utils.txt"))


if __name__ == "__main__":
    unittest.main()
