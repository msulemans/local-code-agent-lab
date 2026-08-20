from __future__ import annotations

from pathlib import Path
import unittest

from localcode.patch_baseline import (
    build_patch_messages,
    build_edit_messages,
    evaluate_patch_prediction,
    extract_unified_diff,
)
from localcode.tools import ToolResult
from localcode.training_baseline import ExecutableBaselineError, load_executable_suite


ROOT = Path(__file__).resolve().parents[2]
SUITE = load_executable_suite(ROOT / "benchmarks/training/m015_executable_dev_v1.json", ROOT)


class PassingRunner:
    def run(self, workspace, command_name):
        return ToolResult("OK", metadata=(("exit_code", 0),))


class PatchBaselineTests(unittest.TestCase):
    def test_prompt_contains_failure_and_broken_file_but_not_test_source(self) -> None:
        case = SUITE.cases[0]
        failure = ToolResult("TypeError: None has no strip", metadata=(("exit_code", 1),))
        messages = build_patch_messages(case, failure)
        user = messages[1]["content"]
        self.assertIn(case.issue.rstrip(), user)
        self.assertIn(case.broken_source, user)
        self.assertIn("TypeError", user)
        self.assertNotIn((case.fixture / case.test_path).read_text(), user)

        edit_messages = build_edit_messages(case, failure)
        self.assertIn(case.issue.rstrip(), edit_messages[1]["content"])
        self.assertIn(case.broken_source, edit_messages[1]["content"])
        self.assertIn("<corrected_file>", edit_messages[0]["content"])

    def test_strict_diff_format_rejects_markdown_and_multiple_files(self) -> None:
        with self.assertRaisesRegex(ExecutableBaselineError, "only one unified diff"):
            extract_unified_diff("```diff\ndiff --git a/a.py b/a.py\n```", max_bytes=1000)
        patch = (
            "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-a\n+b\n"
            "diff --git a/b.py b/b.py\n--- a/b.py\n+++ b/b.py\n@@ -1 +1 @@\n-a\n+b\n"
        )
        with self.assertRaisesRegex(ExecutableBaselineError, "exactly one"):
            extract_unified_diff(patch, max_bytes=1000)

    def test_valid_patch_changes_disposable_copy_and_preserves_fixture(self) -> None:
        case = SUITE.cases[0]
        patch = (
            "diff --git a/src/tiny_parser.py b/src/tiny_parser.py\n"
            "--- a/src/tiny_parser.py\n+++ b/src/tiny_parser.py\n"
            "@@ -1,2 +1,2 @@\n def parse_value(text: str | None) -> str:\n"
            "-    return text.strip()\n+    return (text or \"\").strip()\n"
        )
        result = evaluate_patch_prediction(
            case, patch, max_prediction_bytes=16384, test_runner=PassingRunner()
        )
        self.assertTrue(result.solved)
        self.assertTrue(result.changed)
        self.assertTrue(result.source_unchanged)


if __name__ == "__main__":
    unittest.main()
