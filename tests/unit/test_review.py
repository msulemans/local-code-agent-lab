from __future__ import annotations

import unittest

from localcode.review import (
    DeterministicReviewer,
    ReviewDecision,
    ReviewDisposition,
    ReviewRequest,
)


def request(
    *,
    diff: str = "diff --git a/src/example.py b/src/example.py\n--- a/src/example.py\n+++ b/src/example.py\n@@ -1 +1 @@\n-a\n+b\n",
    final_answer: str | None = "done",
    test_exit_codes: tuple[int, ...] = (0,),
    observation_error_codes: tuple[str, ...] = (),
) -> ReviewRequest:
    return ReviewRequest(
        issue="Fix the example behavior.",
        category="one-file-bug",
        diff=diff,
        final_answer=final_answer,
        test_exit_codes=test_exit_codes,
        observation_error_codes=observation_error_codes,
        changed_paths=("src/example.py",),
        selected_paths=("tests/test_example.py", "src/example.py"),
    )


class ReviewTests(unittest.TestCase):
    def test_accepts_passing_patch_with_final_answer(self) -> None:
        decision = DeterministicReviewer().review(request())

        self.assertEqual(decision.disposition, ReviewDisposition.ACCEPT)
        self.assertEqual(decision.findings, ())

    def test_requests_revision_for_failing_tests_or_runtime_errors(self) -> None:
        failing = DeterministicReviewer().review(request(test_exit_codes=(1,)))
        errored = DeterministicReviewer().review(request(observation_error_codes=("sandbox_unavailable",)))

        self.assertEqual(failing.disposition, ReviewDisposition.REVISE)
        self.assertIn("latest_exit_code:1", failing.findings)
        self.assertEqual(errored.disposition, ReviewDisposition.REVISE)
        self.assertIn("error:sandbox_unavailable", errored.findings)

    def test_rejects_absent_patch_diff(self) -> None:
        decision = DeterministicReviewer().review(request(diff=""))

        self.assertEqual(decision.disposition, ReviewDisposition.REJECT)
        self.assertEqual(decision.findings, ("no_patch_diff",))

    def test_review_decision_validation_is_bounded(self) -> None:
        with self.assertRaisesRegex(ValueError, "summary"):
            ReviewDecision(ReviewDisposition.ACCEPT, "")

        with self.assertRaisesRegex(ValueError, "findings"):
            ReviewDecision(ReviewDisposition.ACCEPT, "ok", ("",))


if __name__ == "__main__":
    unittest.main()
