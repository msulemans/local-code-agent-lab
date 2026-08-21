from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]


class M018ContractTests(unittest.TestCase):
    def test_m018_freezes_pinned_loop_treatment_and_result(self) -> None:
        document = json.loads(
            (ROOT / "benchmarks/training/m018_qwen7b_agent_loop_v1.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(document["schema_version"], 1)
        self.assertEqual(document["action_representation"], "typed_tools_edit_file_retry")
        self.assertEqual(document["selected_context_treatment"], "retrieval")
        self.assertEqual(document["result"]["registered"], 6)
        self.assertEqual(document["result"]["solved"], 3)
        self.assertEqual(document["result"]["sealed_examples_loaded"], 0)
        self.assertEqual(document["matched_comparison"]["simple"]["solved"], 0)
        self.assertEqual(document["matched_comparison"]["retrieval"]["solved"], 3)
        self.assertEqual(
            document["next_gate"],
            "measure_bounded_retry_and_review_on_separate_registered_tasks",
        )


if __name__ == "__main__":
    unittest.main()
