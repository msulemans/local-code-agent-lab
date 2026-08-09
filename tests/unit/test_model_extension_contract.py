from pathlib import Path
import sys
import unittest


SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from check_model_extension_contract import validate_extension  # noqa: E402


class ModelExtensionContractTests(unittest.TestCase):
    def test_extension_is_separate_frozen_and_verified(self) -> None:
        extension = validate_extension()
        candidate = extension["candidates"][0]

        self.assertEqual(extension["parent_experiment"]["experiment_id"], "model-compatibility-v1")
        self.assertEqual(candidate["ollama_tag"], "qwen3.5:9b-q4_K_M")
        self.assertEqual(candidate["planned_run_id"], "m004d-qwen35-9b-v1")
        self.assertEqual(candidate["status"], "downloaded_verified_not_run")
        self.assertEqual(len(candidate["local_artifact_sha256"]), 64)
        self.assertEqual(candidate["local_blob_count"], 4)
        self.assertTrue(candidate["descriptor_sizes_match"])


if __name__ == "__main__":
    unittest.main()
