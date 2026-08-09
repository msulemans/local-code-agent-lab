from pathlib import Path
import sys
import unittest


SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from check_model_bakeoff_contract import validate_contract  # noqa: E402
from run_model_compatibility import candidate_run_error  # noqa: E402


class ModelBakeoffContractTests(unittest.TestCase):
    def test_registered_contract_is_complete_and_offline(self) -> None:
        manifest, prompts = validate_contract()

        self.assertEqual(manifest["status"], "no_candidate_passed_compatibility_review_required")
        self.assertEqual(len(manifest["candidates"]), 2)
        self.assertEqual(len(prompts), 20)
        self.assertEqual(len(manifest["candidates"][0]["local_artifact_sha256"]), 64)
        self.assertEqual(len(manifest["candidates"][1]["local_artifact_sha256"]), 64)

    def test_smallest_candidate_is_first_and_second_is_conditional(self) -> None:
        manifest, _ = validate_contract()
        first, second = manifest["candidates"]

        self.assertLess(first["published_artifact_size_gb_decimal"], second["published_artifact_size_gb_decimal"])
        self.assertEqual(first["status"], "downloaded_verified_failed_quality")
        self.assertEqual(first["compatibility_runs"][0]["primary_reason"], "swap_growth_limit")
        self.assertEqual(first["compatibility_runs"][1]["schema_valid_tool_calls"], "0/12")
        self.assertEqual(second["status"], "downloaded_verified_failed_stability")
        self.assertEqual(second["local_blob_count"], 4)
        self.assertTrue(second["descriptor_size_anomaly"]["hash_matches"])
        self.assertEqual(second["compatibility_runs"][0]["primary_reason"], "swap_growth_limit")
        self.assertEqual(manifest["acquisition_policy"]["mode"], "sequential_smallest_first")

    def test_incomplete_candidate_allows_only_a_new_run_id(self) -> None:
        candidate = {
            "status": "downloaded_verified_run_incomplete",
            "compatibility_runs": [{"run_id": "m004c-qwen25-7b-v1"}],
        }

        self.assertIsNone(candidate_run_error(candidate, "m004c-qwen25-7b-v2"))
        self.assertEqual(
            candidate_run_error(candidate, "m004c-qwen25-7b-v1"),
            "run ID is already registered: m004c-qwen25-7b-v1",
        )

    def test_unverified_candidate_cannot_run(self) -> None:
        candidate = {"status": "conditional_not_downloaded", "compatibility_runs": []}

        self.assertEqual(
            candidate_run_error(candidate, "new-run"),
            "candidate must be downloaded, verified, and eligible to run",
        )


if __name__ == "__main__":
    unittest.main()
