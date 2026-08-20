from __future__ import annotations

import json
from pathlib import Path
import unittest

from localcode.training_run import (
    ValidationMetric,
    available_checkpoint_iterations,
    diagnostic_passed,
    parse_overfit_validation_metrics,
    parse_train_metrics,
    parse_validation_metric,
    select_validation_checkpoint,
)


ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "benchmarks/training/m016_lora_v1.json"
RECOVERY_RESULT = ROOT / "benchmarks/training/m016_recovery_result_v1.json"


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

    def test_recovery_result_preserves_negative_verdict_and_sealed_boundary(self) -> None:
        document = json.loads(RECOVERY_RESULT.read_text(encoding="utf-8"))
        self.assertEqual(document["verdict"], "recovered_negative")
        self.assertFalse(document["original_1600_step_treatment_complete"])
        self.assertEqual(document["sealed_examples_loaded"], 0)
        self.assertEqual(document["selected_adapter"]["iteration"], 200)
        self.assertEqual(document["executable_evaluation"]["solved"], 1)
        self.assertFalse(document["executable_evaluation"]["improved_over_untouched"])
        self.assertGreater(
            document["untouched_baseline"]["executable_solved"],
            document["executable_evaluation"]["solved"],
        )

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

    def test_completed_checkpoint_discovery_is_ordered_and_strict(self) -> None:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "adapter_config.json").write_text("{}", encoding="utf-8")
            (directory / "0000400_adapters.safetensors").write_bytes(b"four")
            (directory / "0000200_adapters.safetensors").write_bytes(b"two")
            (directory / "adapters.safetensors").write_bytes(b"alias")
            self.assertEqual(
                available_checkpoint_iterations(directory, (200, 400, 600)),
                (200, 400),
            )
            (directory / "0000500_adapters.safetensors").write_bytes(b"stray")
            with self.assertRaisesRegex(ValueError, "unexpected"):
                available_checkpoint_iterations(directory, (200, 400, 600))


if __name__ == "__main__":
    unittest.main()
