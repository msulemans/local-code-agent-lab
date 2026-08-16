from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from localcode.micro_suite import (
    MicroCaseRun,
    MicroSuiteError,
    load_micro_suite,
    run_micro_suite,
    run_reviewed_micro_case,
)
from localcode.loop import TerminationReason
from localcode.review import ReviewDecision, ReviewDisposition


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "benchmarks/micro_agent/suite_v1.json"
SCHEMAS = ROOT / "benchmarks/micro_agent/tool_schemas.json"


class MicroSuiteTests(unittest.TestCase):
    def test_manifest_registers_eight_varied_complete_cases(self) -> None:
        suite = load_micro_suite(MANIFEST, SCHEMAS, ROOT)

        self.assertEqual(len(suite.cases), 8)
        self.assertEqual(suite.minimum_cases, 8)
        self.assertEqual(suite.minimum_solved, 8)
        self.assertEqual(len({case.category for case in suite.cases}), 8)
        retry = next(case for case in suite.cases if case.case_id == "ratio-retry")
        tools = [json.loads(response)["decision"].get("tool") for response in retry.responses]
        self.assertEqual(tools.count("apply_patch"), 2)
        self.assertEqual(tools.count("run_tests"), 2)

    def test_full_registered_suite_solves_with_current_test_evidence(self) -> None:
        suite = load_micro_suite(MANIFEST, SCHEMAS, ROOT)
        result = run_micro_suite(suite)
        if any("sandbox_unavailable" in case.observation_error_codes for case in result.cases):
            self.skipTest("outer environment prevents nested macOS sandbox verification")

        self.assertTrue(result.milestone_ready)
        self.assertEqual(result.solved, 8)
        self.assertTrue(all(case.source_unchanged for case in result.cases))
        self.assertTrue(all(case.test_exit_codes[-1] == 0 for case in result.cases))
        retry = next(case for case in result.cases if case.case_id == "ratio-retry")
        self.assertNotEqual(retry.test_exit_codes[0], 0)
        self.assertEqual(retry.test_exit_codes[-1], 0)
        multiple = next(case for case in result.cases if case.case_id == "username-consistency")
        self.assertEqual(multiple.changed_paths, ("src/accounts.py", "src/preview.py"))
        self.assertTrue(all(case.context_mode == "simple" for case in result.cases))
        self.assertTrue(all(case.first_context_chars > 0 for case in result.cases))
        self.assertTrue(all(not case.first_selected_paths for case in result.cases))

    def test_retrieval_context_mode_preserves_repairs_and_records_selected_paths(self) -> None:
        suite = load_micro_suite(MANIFEST, SCHEMAS, ROOT)
        result = run_micro_suite(suite, context_mode="retrieval")
        if any("sandbox_unavailable" in case.observation_error_codes for case in result.cases):
            self.skipTest("outer environment prevents nested macOS sandbox verification")

        self.assertTrue(result.milestone_ready)
        self.assertEqual(result.context_mode, "retrieval")
        parser = next(case for case in result.cases if case.case_id == "parser-none")
        self.assertEqual(parser.context_mode, "retrieval")
        self.assertGreater(parser.first_context_chars, 0)
        self.assertEqual(
            parser.first_selected_paths,
            ("tests/test_tiny_parser.py", "src/tiny_parser.py"),
        )
        self.assertTrue(all(case.success for case in result.cases))

    def test_single_shot_mode_runs_one_patch_attempt_without_retry(self) -> None:
        suite = load_micro_suite(MANIFEST, SCHEMAS, ROOT)
        result = run_micro_suite(suite, context_mode="single_shot")
        if any("sandbox_unavailable" in case.observation_error_codes for case in result.cases):
            self.skipTest("outer environment prevents nested macOS sandbox verification")

        self.assertEqual(result.context_mode, "single_shot")
        self.assertTrue(all(case.context_mode == "single_shot" for case in result.cases))
        self.assertTrue(all(case.first_context_chars > 0 for case in result.cases))
        self.assertTrue(all(not case.first_selected_paths for case in result.cases))
        retry = next(case for case in result.cases if case.case_id == "ratio-retry")
        self.assertFalse(retry.success)
        self.assertEqual(retry.test_exit_codes, (1,))
        self.assertEqual(retry.termination_reason, TerminationReason.TURN_EXHAUSTION)
        parser = next(case for case in result.cases if case.case_id == "parser-none")
        self.assertTrue(parser.success)
        self.assertEqual(parser.test_exit_codes[-1], 0)

    def test_invalid_context_mode_is_rejected(self) -> None:
        suite = load_micro_suite(MANIFEST, SCHEMAS, ROOT)

        with self.assertRaisesRegex(ValueError, "context_mode"):
            run_micro_suite(suite, context_mode="invalid")

    def test_reviewed_case_accepts_or_blocks_base_result_without_needing_sandbox(self) -> None:
        suite = load_micro_suite(MANIFEST, SCHEMAS, ROOT)
        case = suite.cases[0]

        def fake_case_runner(*_args, **_kwargs) -> MicroCaseRun:
            return MicroCaseRun(
                case_id=case.case_id,
                category=case.category,
                context_mode="retrieval",
                success=True,
                termination_reason=TerminationReason.FINAL_ANSWER,
                final_answer="done",
                changed_paths=case.expected_changed_paths,
                test_exit_codes=(0,),
                observation_error_codes=(),
                source_unchanged=True,
                first_context_chars=123,
                first_selected_paths=("tests/test_tiny_parser.py", "src/tiny_parser.py"),
                diff="diff --git a/src/tiny_parser.py b/src/tiny_parser.py\n",
            )

        class AcceptReviewer:
            def review(self, request):
                return ReviewDecision(ReviewDisposition.ACCEPT, "accept")

        class RejectReviewer:
            def review(self, request):
                return ReviewDecision(ReviewDisposition.REJECT, "reject", ("finding",))

        accepted = run_reviewed_micro_case(
            case,
            reviewer=AcceptReviewer(),
            case_runner=fake_case_runner,
        )
        rejected = run_reviewed_micro_case(
            case,
            reviewer=RejectReviewer(),
            case_runner=fake_case_runner,
        )

        self.assertTrue(accepted.success)
        self.assertEqual(accepted.review_disposition, "accept")
        self.assertEqual(accepted.context_mode, "reviewed")
        self.assertFalse(rejected.success)
        self.assertEqual(rejected.review_disposition, "reject")
        self.assertIn("review_reject", rejected.observation_error_codes)
        self.assertIsNone(rejected.final_answer)

    def test_manifest_rejects_duplicate_cases_and_missing_final_decision(self) -> None:
        document = json.loads(MANIFEST.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "suite.json"
            document["cases"].append(document["cases"][0])
            path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaises(MicroSuiteError):
                load_micro_suite(path, SCHEMAS, ROOT)

        document = json.loads(MANIFEST.read_text(encoding="utf-8"))
        document["cases"][0]["plan"] = document["cases"][0]["plan"][:-1]
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "suite.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(MicroSuiteError, "final decision"):
                load_micro_suite(path, SCHEMAS, ROOT)


if __name__ == "__main__":
    unittest.main()
