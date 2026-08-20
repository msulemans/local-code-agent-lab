from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "benchmarks/training/m015_baseline_v1.json"


class M015TrainingContractTests(unittest.TestCase):
    def test_model_environment_data_and_probe_are_frozen(self) -> None:
        document = json.loads(CONFIG.read_text(encoding="utf-8"))
        self.assertEqual(document["schema_version"], 1)
        self.assertEqual(document["model"]["model_id"], "Qwen/Qwen2.5-Coder-1.5B-Instruct")
        self.assertEqual(document["model"]["revision"], "cc932d8a05bf5a3dcd700f50584714d17fc4d03a")
        self.assertEqual(document["environment"]["mlx_lm"], "0.31.3")
        self.assertEqual(document["data"]["train_examples"], 1594)
        self.assertEqual(document["data"]["validation_examples"], 211)
        self.assertEqual(document["data"]["sealed_examples_exported"], 0)
        self.assertEqual(document["probe"]["max_sequence_length"], 1024)
        self.assertEqual(document["probe"]["iterations"], 2)
        self.assertTrue(document["probe"]["mask_prompt"])
        self.assertIn("do not read or export the sealed-test split", document["stop_rules"])

    def test_environment_lock_contains_exact_direct_versions(self) -> None:
        lock = (ROOT / "environment/mlx-training-requirements.lock").read_text(encoding="utf-8")
        self.assertIn("mlx==0.32.1\n", lock)
        self.assertIn("mlx-lm==0.31.3\n", lock)
        self.assertIn("transformers==5.15.1\n", lock)


if __name__ == "__main__":
    unittest.main()
