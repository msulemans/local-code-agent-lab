from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from localcode.real_benchmark import RealBenchmarkConfiguration, RealBenchmarkError, RealBenchmarkIssue, RealBenchmarkInstance
from localcode.real_benchmark_adapters import (
    DatasetControlPatchProducer,
    JsonDatasetIssueResolver,
    LocalCodePatchProducer,
    OfficialSwebenchEvaluator,
)


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

    @patch("localcode.real_benchmark_adapters.platform.machine", return_value="arm64")
    @patch("localcode.real_benchmark_adapters.platform.system", return_value="Darwin")
    def test_evaluator_builds_locally_by_default_on_apple_arm(
        self,
        _system: object,
        _machine: object,
    ) -> None:
        evaluator = OfficialSwebenchEvaluator(dataset_name="snapshot.jsonl")

        self.assertEqual(evaluator.namespace, "none")

    def test_evaluator_namespace_can_be_selected_explicitly(self) -> None:
        evaluator = OfficialSwebenchEvaluator(
            dataset_name="snapshot.jsonl",
            namespace="custom-images",
        )

        self.assertEqual(evaluator.namespace, "custom-images")

    def test_preflight_runs_once_but_resource_baseline_refreshes_per_instance(self) -> None:
        issue = RealBenchmarkIssue(
            "owner__repo-1",
            "owner/repo",
            "1234567890abcdef1234567890abcdef12345678",
            "Fix the parser.",
        )
        configuration = RealBenchmarkConfiguration(
            "A2", "Retrieval agent", "+ ranked repository context", "retrieval_agent", "implemented"
        )
        preflight_calls = {"count": 0}
        snapshot_calls = {"count": 0}

        def fake_validate(**kwargs):
            preflight_calls["count"] += 1
            return None

        class FakeResources:
            swap_used_bytes = 0
            memory_free_percent = 80

        def fake_parse(**kwargs):
            snapshot_calls["count"] += 1
            return FakeResources()

        with (
            patch("localcode.preflight.validate_smoke_baseline", side_effect=fake_validate),
            patch("localcode.preflight.parse_host_resource_snapshot", side_effect=fake_parse),
            patch("localcode.smoke._run_host_command", return_value=""),
            patch("localcode.compatibility.OllamaClient"),
            patch(
                "localcode.real_benchmark_adapters._clone_at_commit",
                side_effect=RealBenchmarkError("no network"),
            ),
        ):
            producer = LocalCodePatchProducer(model="m", tool_document={}, allow_retained_swap=True)
            with self.assertRaises(RealBenchmarkError):
                producer.produce(configuration, issue)
            with self.assertRaises(RealBenchmarkError):
                producer.produce(configuration, issue)

        # The empty-ollama preflight is a once-per-run gate (m041), but the
        # per-turn swap/memory guard needs a fresh baseline per instance so
        # drift from earlier instances does not stop later ones (m042).
        self.assertEqual(preflight_calls["count"], 1)
        self.assertEqual(snapshot_calls["count"], 2)


if __name__ == "__main__":
    unittest.main()
