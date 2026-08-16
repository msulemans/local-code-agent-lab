from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from localcode.real_benchmark import RealBenchmarkConfiguration, RealBenchmarkError, RealBenchmarkIssue, RealBenchmarkInstance
from localcode.real_benchmark_adapters import DatasetControlPatchProducer, JsonDatasetIssueResolver


class RealBenchmarkAdapterTests(unittest.TestCase):
    def _dataset(self, directory: Path) -> Path:
        path = directory / "snapshot.jsonl"
        row = {
            "instance_id": "owner__repo-1",
            "repo": "owner/repo",
            "base_commit": "1234567890abcdef1234567890abcdef12345678",
            "problem_statement": "Fix the parser.",
            "patch": "diff --git a/src/parser.py b/src/parser.py\n",
            "test_patch": "hidden",
        }
        path.write_text(json.dumps(row) + "\n", encoding="utf-8")
        return path

    def test_issue_resolver_reads_only_public_issue_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = self._dataset(Path(temporary))
            resolver = JsonDatasetIssueResolver(path)
            issue = resolver.resolve(
                RealBenchmarkInstance(
                    "owner__repo-1", "owner/repo", "1234567890abcdef1234567890abcdef12345678"
                )
            )
            self.assertEqual(issue.problem_statement, "Fix the parser.")
            self.assertFalse(hasattr(issue, "patch"))

    def test_control_producer_separates_gold_and_empty_modes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = self._dataset(Path(temporary))
            issue = RealBenchmarkIssue(
                "owner__repo-1", "owner/repo", "1234567890abcdef1234567890abcdef12345678", "Fix the parser."
            )
            configuration = RealBenchmarkConfiguration("B0", "Base", "control", "single_shot_base", "implemented")
            gold = DatasetControlPatchProducer(path, mode="gold").produce(configuration, issue)
            empty = DatasetControlPatchProducer(path, mode="empty").produce(configuration, issue)
            self.assertEqual(gold.status, "produced")
            self.assertTrue(gold.patch.startswith("diff --git "))
            self.assertEqual(empty.status, "no_patch")
            self.assertEqual(empty.patch, "")

    def test_missing_dataset_issue_is_typed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            resolver = JsonDatasetIssueResolver(self._dataset(Path(temporary)))
            with self.assertRaises(RealBenchmarkError):
                resolver.resolve(RealBenchmarkInstance("owner__repo-2", "owner/repo", "1234567"))


if __name__ == "__main__":
    unittest.main()
