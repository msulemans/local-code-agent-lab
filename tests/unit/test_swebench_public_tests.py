from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from localcode.patches import apply_patch
from localcode.swebench_public_tests import SwebenchPublicTestRunner
from localcode.tools import ToolError, ToolResult
from localcode.workspace import create_workspace


FIXTURE = Path("tests/fixtures/micro_repos/parser_none").resolve()
VALID_PATCH = """diff --git a/src/tiny_parser.py b/src/tiny_parser.py
--- a/src/tiny_parser.py
+++ b/src/tiny_parser.py
@@ -1,2 +1,4 @@
 def parse_value(text: str | None) -> str:
+    if text is None:
+        return ""
     return text.strip()
"""


class SwebenchPublicTestRunnerTests(unittest.TestCase):
    def test_candidate_patch_runs_without_evaluator_or_hidden_test_material(self) -> None:
        captured = {}

        def fake_execute(
            root, command, environment, timeout, max_output, command_name, terminate_on_limit
        ):
            captured["command"] = command
            captured["terminate_on_limit"] = terminate_on_limit
            return ToolResult(
                content="3 passed",
                metadata=(("command", command_name), ("exit_code", 0), ("timed_out", False)),
            )

        with tempfile.TemporaryDirectory() as temporary:
            workspace = create_workspace(FIXTURE, Path(temporary) / "workspace")
            apply_patch(workspace.root, VALID_PATCH)
            runner = SwebenchPublicTestRunner(
                instance_id="psf__requests-2931",
                repository="psf/requests",
                version="2.9",
                public_test_command="pytest -rA",
                docker_executable="/usr/bin/true",
            )
            with (
                patch("localcode.swebench_public_tests._require_image"),
                patch("localcode.swebench_public_tests._execute_bounded", side_effect=fake_execute),
            ):
                result = runner.run(workspace, "repository-tests")

        command_text = " ".join(captured["command"])
        self.assertIn("--network none", command_text)
        self.assertIn("readonly", command_text)
        self.assertIn("git apply --check /localcode/candidate.patch", command_text)
        self.assertIn("pytest -rA", command_text)
        self.assertNotIn("test_patch", command_text)
        self.assertNotIn("FAIL_TO_PASS", command_text)
        self.assertFalse(captured["terminate_on_limit"])
        self.assertEqual(result.metadata_dict()["environment"], "swebench-instance-image")
        self.assertFalse(result.metadata_dict()["hidden_tests"])

    def test_unknown_command_and_invalid_limits_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = create_workspace(FIXTURE, Path(temporary) / "workspace")
            runner = SwebenchPublicTestRunner(
                instance_id="psf__requests-2931",
                repository="psf/requests",
                version="2.9",
                public_test_command="pytest -rA",
                docker_executable="/usr/bin/true",
            )
            with self.assertRaisesRegex(ToolError, "unknown test command"):
                runner.run(workspace, "python-unittest")
            with self.assertRaises(ToolError):
                runner.run(workspace, "repository-tests", timeout_seconds=0)


if __name__ == "__main__":
    unittest.main()
