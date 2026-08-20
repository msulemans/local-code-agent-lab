from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from localcode.tools import ToolResult
from localcode.training_baseline import (
    ExecutableBaselineError,
    build_case_messages,
    evaluate_prediction,
    extract_corrected_file,
    load_executable_suite,
)


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "benchmarks/training/m015_executable_dev_v1.json"


class PassingRunner:
    def run(self, workspace, command_name: str) -> ToolResult:
        self.content = (workspace.root / "src/tiny_parser.py").read_text(encoding="utf-8")
        return ToolResult(
            content="1 test passed",
            metadata=(("command", command_name), ("exit_code", 0), ("sandboxed", True)),
        )


class ExecutableBaselineTests(unittest.TestCase):
    def test_pinned_development_suite_loads_without_sealed_examples(self) -> None:
        suite = load_executable_suite(MANIFEST, ROOT)

        self.assertEqual(suite.suite_id, "m015-executable-dev-v1")
        self.assertEqual(len(suite.cases), 6)
        self.assertEqual(suite.temperature, 0)
        self.assertIn("must not load", suite.sealed_split_policy)

    def test_prompt_contains_issue_and_broken_file_but_not_test_source(self) -> None:
        case = load_executable_suite(MANIFEST, ROOT).cases[0]
        messages = build_case_messages(case)
        rendered = json.dumps(messages)
        test_source = (case.fixture / case.test_path).read_text(encoding="utf-8")

        self.assertIn("Calling `parse_value(None)`", rendered)
        self.assertIn("return text.strip()", rendered)
        self.assertNotIn(test_source, rendered)
        self.assertNotIn("assertEqual", rendered)

    def test_prediction_envelope_is_strict_and_bounded(self) -> None:
        self.assertEqual(
            extract_corrected_file("<corrected_file>\nx = 1\n</corrected_file>", max_bytes=100),
            "x = 1\n",
        )
        with self.assertRaisesRegex(ExecutableBaselineError, "exactly one"):
            extract_corrected_file("```python\nx = 1\n```", max_bytes=100)
        with self.assertRaisesRegex(ExecutableBaselineError, "byte limit"):
            extract_corrected_file("<corrected_file>abcdef</corrected_file>", max_bytes=3)

    def test_valid_prediction_runs_in_copy_and_leaves_fixture_unchanged(self) -> None:
        case = load_executable_suite(MANIFEST, ROOT).cases[0]
        original = (case.fixture / case.source_path).read_text(encoding="utf-8")
        runner = PassingRunner()

        result = evaluate_prediction(
            case,
            "<corrected_file>\ndef parse_value(text: str | None) -> str:\n"
            "    return \"\" if text is None else text.strip()\n</corrected_file>",
            max_prediction_bytes=1024,
            test_runner=runner,
        )

        self.assertTrue(result.solved)
        self.assertEqual(result.test_exit_code, 0)
        self.assertIn("text is None", runner.content)
        self.assertEqual((case.fixture / case.source_path).read_text(encoding="utf-8"), original)
        self.assertTrue(result.source_unchanged)

    def test_invalid_prediction_never_reaches_test_runner(self) -> None:
        case = load_executable_suite(MANIFEST, ROOT).cases[0]
        result = evaluate_prediction(
            case,
            "Here is the corrected code",
            max_prediction_bytes=1024,
            test_runner=PassingRunner(),
        )

        self.assertEqual(result.status, "invalid_prediction")
        self.assertEqual(result.error_code, "invalid_format")
        self.assertIsNone(result.test_exit_code)

    def test_tampered_fixture_pin_is_rejected(self) -> None:
        document = json.loads(MANIFEST.read_text(encoding="utf-8"))
        document["cases"][0]["source_sha256"] = "0" * 64
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "manifest.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(ExecutableBaselineError, "does not match"):
                load_executable_suite(path, ROOT)


if __name__ == "__main__":
    unittest.main()
