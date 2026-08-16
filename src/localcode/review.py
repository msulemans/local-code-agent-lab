"""Bounded review decisions over existing LocalCode repair evidence."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol


class ReviewDisposition(str, Enum):
    ACCEPT = "accept"
    REVISE = "revise"
    REJECT = "reject"


@dataclass(frozen=True, slots=True)
class ReviewRequest:
    issue: str
    category: str
    diff: str
    final_answer: str | None
    test_exit_codes: tuple[int, ...]
    observation_error_codes: tuple[str, ...]
    changed_paths: tuple[str, ...]
    selected_paths: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReviewDecision:
    disposition: ReviewDisposition
    summary: str
    findings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.summary, str) or not self.summary.strip() or len(self.summary) > 500:
            raise ValueError("review summary must contain 1-500 characters")
        if (
            isinstance(self.findings, str)
            or not isinstance(self.findings, tuple)
            or len(self.findings) > 5
            or any(not isinstance(value, str) or not value.strip() or len(value) > 200 for value in self.findings)
        ):
            raise ValueError("review findings must be a bounded tuple of non-empty strings")


class ReviewBackend(Protocol):
    def review(self, request: ReviewRequest) -> ReviewDecision:
        """Return one bounded review decision over existing repair evidence."""


class DeterministicReviewer:
    """Conservative review policy for the deterministic micro-benchmark layer."""

    def review(self, request: ReviewRequest) -> ReviewDecision:
        if not request.diff.strip():
            return ReviewDecision(
                ReviewDisposition.REJECT,
                "Reject the answer because there is no patch diff to review.",
                ("no_patch_diff",),
            )
        if request.observation_error_codes:
            return ReviewDecision(
                ReviewDisposition.REVISE,
                "Request revision because the run recorded error observations.",
                tuple(f"error:{code}" for code in request.observation_error_codes[:3]),
            )
        if not request.test_exit_codes:
            return ReviewDecision(
                ReviewDisposition.REVISE,
                "Request revision because there is no test evidence for the patch.",
                ("missing_test_evidence",),
            )
        if request.test_exit_codes[-1] != 0:
            return ReviewDecision(
                ReviewDisposition.REVISE,
                "Request revision because the latest registered test command failed.",
                (f"latest_exit_code:{request.test_exit_codes[-1]}",),
            )
        if request.final_answer is None:
            return ReviewDecision(
                ReviewDisposition.REVISE,
                "Request revision because the patch has no accepted final answer yet.",
                ("missing_final_answer",),
            )
        return ReviewDecision(
            ReviewDisposition.ACCEPT,
            "Accept the answer because the patch diff and current passing tests are present.",
            (),
        )
