from __future__ import annotations

import json
from pathlib import Path
import unittest

from localcode.training_run import (
    ValidationMetric,
    diagnostic_passed,
    parse_overfit_validation_metrics,
    parse_train_metrics,
    parse_validation_metric,
    select_validation_checkpoint,
)


ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "benchmarks/training/m016_lora_v1.json"


class TrainingRunTests(unittest.TestCase):
    def test_m016_config_freezes_data_diagnostic_full_run_and_promotion(self) -> None:
        document = json.loads(CONFIG.read_text(encoding="utf-8"))
        self.assertEqual(document["schema_version"], 1)
        self.assertEqual(document["untouched_baseline"]["solved"], 4)
        self.assertEqual(document["data"]["sealed_examples_loaded"], 0)
        self.assertEqual(document["diagnostic"]["train_prefix_examples"], 8)
        self.assertEqual(document["full_training"]["iterations"], 1600)
        self.assertEqual(document["full_training"]["checkpoint_iterations"], list(range(200, 1601, 200)))
        self.assertEqual(document["promotion_gate"]["must_exceed"], 4)
        self.assertIn("Do not load", document["sealed_split_policy"])

    def test_training_metrics_drive_overfit_gate(self) -> None:
        output = (
            "Iter 1: Val loss 0.208, Val took 2.0s\n"
            "Iter 5: Train loss 1.000, Learning Rate 1e-4, It/sec 1, "
            "Tokens/sec 100.0, Trained Tokens 500, Peak mem 4.000 GB\n"
            "Iter 20: Train loss 0.700, Learning Rate 1e-4, It/sec 1, "
            "Tokens/sec 110.0, Trained Tokens 2000, Peak mem 4.200 GB\n"
            "Iter 40: Val loss 0.010, Val took 2.0s\n"
            "Iter 40: Train loss 1.200, Learning Rate 1e-4, It/sec 1, "
            "Tokens/sec 110.0, Trained Tokens 4000, Peak mem 4.200 GB\n"
        )
        metrics = parse_train_metrics(output)
        validation = parse_overfit_validation_metrics(output)
        self.assertEqual([metric.iteration for metric in metrics], [5, 20, 40])
        self.assertEqual([metric.iteration for metric in validation], [1, 40])
        self.assertTrue(diagnostic_passed(metrics, validation, required_relative_improvement=0.1, maximum_peak_memory_gb=24))
        self.assertFalse(diagnostic_passed(metrics, validation, required_relative_improvement=0.4, maximum_peak_memory_gb=24))

    def test_checkpoint_selection_uses_lowest_validation_loss_then_earliest(self) -> None:
        parsed = parse_validation_metric(600, "Test loss 0.812, Test ppl 2.252.")
        self.assertEqual(parsed, ValidationMetric(600, 0.812, 2.252))
        selected = select_validation_checkpoint(
            [ValidationMetric(400, 0.7, 2.0), ValidationMetric(200, 0.7, 2.0), parsed]
        )
        self.assertEqual(selected.iteration, 200)
        with self.assertRaisesRegex(ValueError, "unique"):
            select_validation_checkpoint([parsed, parsed])


if __name__ == "__main__":
    unittest.main()
