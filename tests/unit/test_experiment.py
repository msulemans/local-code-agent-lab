from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

from localcode.experiment import ExperimentError, load_experiment_manifest, run_experiment
from localcode.loop import TerminationReason
from localcode.micro_suite import MicroCase, MicroCaseRun, MicroSuite, MicroSuiteRun


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "benchmarks/experiment/manifest_v1.json"


def fake_suite() -> MicroSuite:
    return MicroSuite(
        suite_id="micro-eval-v1",
        minimum_cases=2,
        maximum_cases=2,
        minimum_solved=1,
        cases=(
            MicroCase(
                case_id="parser-none",
                category="one-file-bug",
                fixture=ROOT / "tests/fixtures/micro_repos/parser_none",
                issue_file="ISSUE.md",
                expected_changed_paths=("src/tiny_parser.py",),
                responses=(),
            ),
            MicroCase(
                case_id="username-consistency",
                category="multi-file-repair",
                fixture=ROOT / "tests/fixtures/micro_repos/username_consistency",
                issue_file="ISSUE.md",
                expected_changed_paths=("src/accounts.py", "src/preview.py"),
                responses=(),
            ),
        ),
    )


def fake_suite_loader(manifest_path, tool_schemas_path, repository_root) -> MicroSuite:
    return fake_suite()


def fake_suite_runner(suite: MicroSuite, *, context_mode: str = "simple") -> MicroSuiteRun:
    if context_mode == "single_shot":
        success_by_case = {"parser-none": False, "username-consistency": False}
        context_chars = 1120
        selected_paths = ()
    elif context_mode == "simple":
        success_by_case = {"parser-none": False, "username-consistency": True}
        context_chars = 377
        selected_paths = ()
    else:
        success_by_case = {"parser-none": True, "username-consistency": True}
        context_chars = 1948
        selected_paths = ("tests/test_tiny_parser.py", "src/tiny_parser.py")
    cases = tuple(
        MicroCaseRun(
            case_id=case.case_id,
            category=case.category,
            context_mode=context_mode,
            success=success_by_case[case.case_id],
            termination_reason=TerminationReason.FINAL_ANSWER
            if success_by_case[case.case_id]
            else TerminationReason.INVALID_ACTION_EXHAUSTION,
            final_answer="done" if success_by_case[case.case_id] else None,
            changed_paths=case.expected_changed_paths if success_by_case[case.case_id] else (),
            test_exit_codes=(0,) if success_by_case[case.case_id] else (),
            observation_error_codes=() if success_by_case[case.case_id] else ("invalid_json",),
            source_unchanged=True,
            first_context_chars=context_chars,
            first_selected_paths=selected_paths,
            diff="diff --git a/example b/example\n" if success_by_case[case.case_id] else "",
        )
        for case in suite.cases
    )
    return MicroSuiteRun(
        suite_id=suite.suite_id,
        context_mode=context_mode,
        cases=cases,
        minimum_cases=suite.minimum_cases,
        maximum_cases=suite.maximum_cases,
        minimum_solved=suite.minimum_solved,
    )


def fake_reviewed_suite_runner(suite: MicroSuite) -> MicroSuiteRun:
    base = fake_suite_runner(suite, context_mode="retrieval")
    return MicroSuiteRun(
        suite_id=base.suite_id,
        context_mode="reviewed",
        cases=tuple(
            replace(
                case,
                context_mode="reviewed",
                review_disposition="accept",
                review_findings=(),
            )
            for case in base.cases
        ),
        minimum_cases=base.minimum_cases,
        maximum_cases=base.maximum_cases,
        minimum_solved=base.minimum_solved,
    )


class ExperimentTests(unittest.TestCase):
    def test_manifest_loads_frozen_four_configuration_order(self) -> None:
        manifest = load_experiment_manifest(MANIFEST, ROOT)

        self.assertEqual(manifest.experiment_id, "localcode-experiment-v1")
        self.assertEqual(
            tuple(configuration.configuration_id for configuration in manifest.configurations),
            ("B0", "A1", "A2", "A3"),
        )
        self.assertGreaterEqual(len(manifest.fairness_controls), 4)

    def test_runner_measures_b0_a1_a2_and_marks_a3_unavailable(self) -> None:
        manifest = load_experiment_manifest(MANIFEST, ROOT)

        result = run_experiment(
            manifest,
            suite_loader=fake_suite_loader,
            suite_runner=fake_suite_runner,
            reviewed_suite_runner=fake_reviewed_suite_runner,
        )

        by_id = {configuration.configuration_id: configuration for configuration in result.configurations}
        self.assertEqual(by_id["B0"].status, "measured")
        self.assertEqual(by_id["B0"].solved, 0)
        self.assertEqual(by_id["A1"].status, "measured")
        self.assertEqual(by_id["A1"].solved, 1)
        self.assertEqual(by_id["A2"].status, "measured")
        self.assertEqual(by_id["A2"].solved, 2)
        self.assertEqual(by_id["A3"].status, "measured")
        self.assertEqual(by_id["A3"].solved, 2)
        self.assertEqual(by_id["B0"].cases[0].first_selected_paths, ())
        self.assertEqual(by_id["A2"].cases[0].first_selected_paths, ("tests/test_tiny_parser.py", "src/tiny_parser.py"))
        self.assertEqual(by_id["A3"].cases[0].review_disposition, "accept")

    def test_adjacent_comparison_reports_retrieval_gain(self) -> None:
        manifest = load_experiment_manifest(MANIFEST, ROOT)

        result = run_experiment(
            manifest,
            suite_loader=fake_suite_loader,
            suite_runner=fake_suite_runner,
            reviewed_suite_runner=fake_reviewed_suite_runner,
        )

        comparisons = {
            (comparison.previous_configuration_id, comparison.next_configuration_id): comparison
            for comparison in result.adjacent_comparisons
        }
        self.assertEqual(comparisons[("B0", "A1")].status, "measured")
        self.assertEqual(comparisons[("B0", "A1")].gained, ("username-consistency",))
        self.assertEqual(comparisons[("A1", "A2")].status, "measured")
        self.assertEqual(comparisons[("A1", "A2")].gained, ("parser-none",))
        self.assertEqual(comparisons[("A1", "A2")].lost, ())
        self.assertEqual(comparisons[("A2", "A3")].status, "measured")
        self.assertEqual(comparisons[("A2", "A3")].gained, ())
        self.assertEqual(comparisons[("A2", "A3")].solved_both, ("parser-none", "username-consistency"))

    def test_invalid_manifest_rejects_out_of_order_configuration_ids(self) -> None:
        document = json.loads(MANIFEST.read_text(encoding="utf-8"))
        document["configurations"][0]["id"] = "A1"
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "manifest.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(ExperimentError, "configuration order"):
                load_experiment_manifest(path, ROOT)


if __name__ == "__main__":
    unittest.main()
