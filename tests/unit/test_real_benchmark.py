from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from localcode.real_benchmark import (
    EvaluationInstanceResult,
    PatchAttempt,
    RealBenchmarkError,
    RealBenchmarkIssue,
    RealBenchmarkManifest,
    RealBenchmarkConfiguration,
    RealBenchmarkInstance,
    load_real_benchmark_manifest,
    prepare_real_benchmark_run,
    run_real_benchmark,
)


ROOT = Path(__file__).resolve().parents[2]


def manifest_document() -> dict[str, object]:
    return {
        "schema_version": 1,
        "subset_id": "swebench-verified-pinned20-v1",
        "dataset": {
            "name": "princeton-nlp/SWE-bench_Verified",
            "split": "test",
            "revision": "2026-08-12-pinned20",
        },
        "selection": {
            "seed": 17,
            "max_per_repository": 5,
            "compatibility_filters": [
                "python-only",
                "gold-control-passes",
                "arm64-compatible",
            ],
        },
        "fairness_controls": [
            "Same model checkpoint and quantization",
            "Same issue text and base commit",
            "Same generated-token allowance",
            "Same evaluator and container resources",
        ],
        "configurations": [
            {
                "id": "B0",
                "label": "Single-shot base",
                "change": "No tools or retry",
                "kind": "single_shot_base",
                "availability": "implemented",
            },
            {
                "id": "A1",
                "label": "Simple agent",
                "change": "+ tool loop",
                "kind": "simple_agent",
                "availability": "implemented",
            },
            {
                "id": "A2",
                "label": "Retrieval agent",
                "change": "+ ranked context",
                "kind": "retrieval_agent",
                "availability": "implemented",
            },
            {
                "id": "A3",
                "label": "Agent + review",
                "change": "+ fresh critique",
                "kind": "agent_plus_review",
                "availability": "implemented",
            },
        ],
        "instances": [
            {
                "instance_id": f"example__repo-{index:03d}",
                "repository": f"example/repo-{((index - 1) // 5) + 1}",
                "base_commit": f"{index:07x}",
            }
            for index in range(1, 21)
        ],
    }


class FakeIssueResolver:
    def resolve(self, instance: RealBenchmarkInstance) -> RealBenchmarkIssue:
        return RealBenchmarkIssue(
            instance_id=instance.instance_id,
            repository=instance.repository,
            base_commit=instance.base_commit,
            problem_statement=f"Fix {instance.instance_id} in {instance.repository}.",
        )


class FakePatchProducer:
    def produce(
        self,
        configuration: RealBenchmarkConfiguration,
        issue: RealBenchmarkIssue,
    ) -> PatchAttempt:
        number = int(issue.instance_id.rsplit("-", 1)[1])
        if number == 20:
            return PatchAttempt(
                instance_id=issue.instance_id,
                model_name_or_path=f"localcode/{configuration.configuration_id.lower()}",
                patch="",
                status="no_patch",
                failure_category="LOOP_CONTROL",
                reason="budget exhausted before a patch was formed",
                tokens_used=90,
                tool_calls=8,
                wall_seconds=3.5,
            )
        return PatchAttempt(
            instance_id=issue.instance_id,
            model_name_or_path=f"localcode/{configuration.configuration_id.lower()}",
            patch=(
                "diff --git a/sample.py b/sample.py\n"
                "--- a/sample.py\n"
                "+++ b/sample.py\n"
                "@@ -1 +1 @@\n"
                f"-broken-{configuration.configuration_id}-{number}\n"
                f"+fixed-{configuration.configuration_id}-{number}\n"
            ),
            status="produced",
            failure_category=None,
            reason=None,
            tokens_used=100 + number,
            tool_calls=1 if configuration.configuration_id == "B0" else 4,
            wall_seconds=1.0 + (number / 100.0),
        )


class FakeEvaluator:
    def evaluate(
        self,
        manifest: RealBenchmarkManifest,
        configuration: RealBenchmarkConfiguration,
        predictions_path: Path,
        output_directory: Path,
    ) -> tuple[EvaluationInstanceResult, ...]:
        lines = [json.loads(line) for line in predictions_path.read_text(encoding="utf-8").splitlines()]
        self._assert_prediction_shape(lines, configuration.configuration_id)

        resolved_sets = {
            "B0": set(range(1, 8)),
            "A1": set(range(1, 9)),
            "A2": set(range(1, 10)),
            "A3": set(range(1, 10)),
        }
        results = []
        for row in lines:
            number = int(row["instance_id"].rsplit("-", 1)[1])
            if number == 19:
                results.append(
                    EvaluationInstanceResult(
                        instance_id=row["instance_id"],
                        resolved=False,
                        status="environment_error",
                        reason="docker image failed before a fair attempt",
                    )
                )
                continue
            resolved = number in resolved_sets[configuration.configuration_id]
            results.append(
                EvaluationInstanceResult(
                    instance_id=row["instance_id"],
                    resolved=resolved,
                    status="resolved" if resolved else "unresolved",
                    reason=None if resolved else "patch did not satisfy the evaluator tests",
                )
            )
        return tuple(results)

    def _assert_prediction_shape(self, rows: list[dict[str, object]], configuration_id: str) -> None:
        assert len(rows) == 20
        for row in rows:
            assert set(row) == {"instance_id", "model_name_or_path", "model_patch"}
            assert row["model_name_or_path"] == f"localcode/{configuration_id.lower()}"
        issue_20 = next(row for row in rows if row["instance_id"] == "example__repo-020")
        assert issue_20["model_patch"] == ""


class FailingEvaluator:
    def evaluate(self, *args, **kwargs):
        raise RealBenchmarkError("official SWE-bench evaluator failed: docker daemon unreachable")


class RealBenchmarkTests(unittest.TestCase):
    def test_manifest_loads_exactly_twenty_instances_and_four_configurations(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "manifest.json"
            path.write_text(json.dumps(manifest_document()), encoding="utf-8")

            manifest = load_real_benchmark_manifest(path)

        self.assertEqual(manifest.subset_id, "swebench-verified-pinned20-v1")
        self.assertEqual(len(manifest.instances), 20)
        self.assertEqual(
            tuple(configuration.configuration_id for configuration in manifest.configurations),
            ("B0", "A1", "A2", "A3"),
        )

    def test_manifest_rejects_non_pinned_instance_count(self) -> None:
        document = manifest_document()
        document["instances"] = document["instances"][:-1]
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "manifest.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(RealBenchmarkError, "exactly 20 instances"):
                load_real_benchmark_manifest(path)

    def test_prepare_writes_exact_prediction_jsonl_and_attempt_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            manifest_path = Path(temporary) / "manifest.json"
            manifest_path.write_text(json.dumps(manifest_document()), encoding="utf-8")
            manifest = load_real_benchmark_manifest(manifest_path)

            prepared = prepare_real_benchmark_run(
                manifest,
                run_id="realbench-v1",
                runs_root=Path(temporary) / "runs",
                issue_resolver=FakeIssueResolver(),
                patch_producer=FakePatchProducer(),
            )

            b0 = prepared.configurations[0]
            self.assertEqual(b0.status, "prepared")
            self.assertEqual(b0.registered, 20)
            self.assertEqual(b0.attempted, 19)
            self.assertEqual(b0.valid_patches, 19)
            self.assertTrue((prepared.run_directory / "manifest_snapshot.json").is_file())
            self.assertTrue((prepared.run_directory / "prepared_run.json").is_file())
            self.assertIsNotNone(b0.predictions_path)
            self.assertIsNotNone(b0.attempts_path)
            predictions = [
                json.loads(line)
                for line in b0.predictions_path.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(len(predictions), 20)
            self.assertEqual(
                set(predictions[0]),
                {"instance_id", "model_name_or_path", "model_patch"},
            )
            no_patch = next(row for row in predictions if row["instance_id"] == "example__repo-020")
            self.assertEqual(no_patch["model_patch"], "")

    def test_prepare_reports_one_progress_line_per_instance(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            manifest_path = Path(temporary) / "manifest.json"
            manifest_path.write_text(json.dumps(manifest_document()), encoding="utf-8")
            manifest = load_real_benchmark_manifest(manifest_path)

            lines: list[str] = []
            prepare_real_benchmark_run(
                manifest,
                run_id="realbench-v3",
                runs_root=Path(temporary) / "runs",
                issue_resolver=FakeIssueResolver(),
                patch_producer=FakePatchProducer(),
                progress_observer=lines.append,
            )

            # Four implemented configurations x 20 instances = 80 lines.
            self.assertEqual(len(lines), 80)
            self.assertTrue(lines[0].startswith("B0 example__repo-001 status="))
            self.assertIn("wall=", lines[0])

    def test_run_real_benchmark_aggregates_resolved_counts_and_failures(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            manifest_path = Path(temporary) / "manifest.json"
            manifest_path.write_text(json.dumps(manifest_document()), encoding="utf-8")
            manifest = load_real_benchmark_manifest(manifest_path)

            result = run_real_benchmark(
                manifest,
                run_id="realbench-v2",
                runs_root=Path(temporary) / "runs",
                issue_resolver=FakeIssueResolver(),
                patch_producer=FakePatchProducer(),
                evaluator=FakeEvaluator(),
            )

            by_id = {configuration.configuration_id: configuration for configuration in result.configurations}
            self.assertEqual(by_id["B0"].resolved, 7)
            self.assertEqual(by_id["A1"].resolved, 8)
            self.assertEqual(by_id["A2"].resolved, 9)
            self.assertEqual(by_id["A3"].resolved, 9)
            self.assertEqual(by_id["A1"].attempted, 19)
            self.assertEqual(by_id["A2"].valid_patches, 19)
            self.assertTrue((result.run_directory / "run_summary.json").is_file())

            issue_19 = next(case for case in by_id["A3"].cases if case.instance_id == "example__repo-019")
            self.assertEqual(issue_19.primary_failure_category, "ENVIRONMENT")
            issue_20 = next(case for case in by_id["A3"].cases if case.instance_id == "example__repo-020")
            self.assertEqual(issue_20.primary_failure_category, "LOOP_CONTROL")
            issue_10 = next(case for case in by_id["A1"].cases if case.instance_id == "example__repo-010")
            self.assertEqual(issue_10.primary_failure_category, "FIX_INCOMPLETE")

            comparisons = {
                (comparison.previous_configuration_id, comparison.next_configuration_id): comparison
                for comparison in result.adjacent_comparisons
            }
            self.assertEqual(comparisons[("B0", "A1")].gained, ("example__repo-008",))
            self.assertEqual(comparisons[("A1", "A2")].gained, ("example__repo-009",))
            self.assertEqual(comparisons[("A2", "A3")].gained, ())
            self.assertEqual(comparisons[("A2", "A3")].resolved_both, tuple(f"example__repo-{index:03d}" for index in range(1, 10)))

    def test_evaluator_failure_preserves_the_run_as_environment_errors(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            manifest_path = Path(temporary) / "manifest.json"
            manifest_path.write_text(json.dumps(manifest_document()), encoding="utf-8")
            manifest = load_real_benchmark_manifest(manifest_path)

            result = run_real_benchmark(
                manifest,
                run_id="realbench-v4",
                runs_root=Path(temporary) / "runs",
                issue_resolver=FakeIssueResolver(),
                patch_producer=FakePatchProducer(),
                evaluator=FailingEvaluator(),
            )

            self.assertTrue((result.run_directory / "run_summary.json").is_file())
            measured = [c for c in result.configurations if c.status == "measured"]
            self.assertEqual(len(measured), 4)
            for configuration in measured:
                self.assertEqual(configuration.resolved, 0)
                self.assertEqual(len(configuration.cases), 20)
                self.assertTrue(
                    all(case.evaluation_status == "environment_error" for case in configuration.cases)
                )
                self.assertTrue(
                    all(case.primary_failure_category == "ENVIRONMENT" for case in configuration.cases)
                )


if __name__ == "__main__":
    unittest.main()
