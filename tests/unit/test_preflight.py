from __future__ import annotations

import unittest

from localcode.preflight import SmokePreflightError, validate_smoke_baseline


ZERO_SWAP = "vm.swapusage: total = 0.00M  used = 0.00M  free = 0.00M  (encrypted)"
HEALTHY_MEMORY = """The system has 34359738368 bytes.
System-wide memory free percentage: 91%
"""


class SmokePreflightTests(unittest.TestCase):
    def test_clean_unloaded_baseline_is_accepted(self) -> None:
        baseline = validate_smoke_baseline(
            swapusage_output=ZERO_SWAP,
            memory_pressure_output=HEALTHY_MEMORY,
            running_models=[],
        )

        self.assertEqual(baseline.swap_used_bytes, 0)
        self.assertEqual(baseline.memory_free_percent, 91)
        self.assertEqual(baseline.loaded_models, ())

    def test_retained_swap_blocks_the_smoke_run(self) -> None:
        with self.assertRaises(SmokePreflightError) as captured:
            validate_smoke_baseline(
                swapusage_output=(
                    "vm.swapusage: total = 3072.00M  used = 2213.88M "
                    " free = 858.12M  (encrypted)"
                ),
                memory_pressure_output=HEALTHY_MEMORY,
                running_models=[],
            )

        self.assertEqual(captured.exception.code, "retained_swap")

    def test_loaded_model_blocks_the_smoke_run(self) -> None:
        with self.assertRaises(SmokePreflightError) as captured:
            validate_smoke_baseline(
                swapusage_output=ZERO_SWAP,
                memory_pressure_output=HEALTHY_MEMORY,
                running_models=[{"name": "qwen3.5:9b-q4_K_M"}],
            )

        self.assertEqual(captured.exception.code, "model_already_loaded")

    def test_unparseable_host_outputs_are_rejected(self) -> None:
        cases = (
            ("unknown", HEALTHY_MEMORY, "invalid_swapusage"),
            (ZERO_SWAP, "unknown", "invalid_memory_pressure"),
        )
        for swap_output, memory_output, expected_code in cases:
            with self.subTest(expected_code=expected_code):
                with self.assertRaises(SmokePreflightError) as captured:
                    validate_smoke_baseline(
                        swapusage_output=swap_output,
                        memory_pressure_output=memory_output,
                        running_models=[],
                    )
                self.assertEqual(captured.exception.code, expected_code)

    def test_invalid_ollama_process_shape_is_rejected(self) -> None:
        with self.assertRaises(SmokePreflightError) as captured:
            validate_smoke_baseline(
                swapusage_output=ZERO_SWAP,
                memory_pressure_output=HEALTHY_MEMORY,
                running_models=[{"size": 123}],
            )

        self.assertEqual(captured.exception.code, "invalid_ollama_ps")


if __name__ == "__main__":
    unittest.main()
