from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

from localcode.patches import apply_patch
from localcode.test_runner import TestCommand, TestRunner
from localcode.tools import ToolError
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


class TestRunnerTests(unittest.TestCase):
    def run_or_skip(self, runner: TestRunner, workspace, command_name: str, **limits):
        try:
            return runner.run(workspace, command_name, **limits)
        except ToolError as exc:
            if exc.code == "sandbox_unavailable":
                self.skipTest(str(exc))
            raise

    def test_registered_fixture_tests_fail_before_and_pass_after_patch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            before = create_workspace(FIXTURE, Path(temporary) / "before")
            after = create_workspace(FIXTURE, Path(temporary) / "after")

            failing = self.run_or_skip(TestRunner(), before, "python-unittest")
            apply_patch(after.root, VALID_PATCH)
            passing = self.run_or_skip(TestRunner(), after, "python-unittest")

        self.assertNotEqual(failing.metadata_dict()["exit_code"], 0)
        self.assertIn("FAILED", failing.content)
        self.assertEqual(passing.metadata_dict()["exit_code"], 0)
        self.assertIn("OK", passing.content)
        self.assertTrue(passing.metadata_dict()["sandboxed"])

    def test_unknown_command_and_invalid_limits_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = create_workspace(FIXTURE, Path(temporary) / "workspace")
            runner = TestRunner()
            with self.assertRaisesRegex(ToolError, "unknown test command"):
                runner.run(workspace, "terminal")
            with self.assertRaises(ToolError):
                runner.run(workspace, "python-unittest", timeout_seconds=0)
            with self.assertRaises(ToolError):
                runner.run(workspace, "python-unittest", max_output_bytes=100_000)

    def test_output_and_time_limits_kill_the_process_group(self) -> None:
        executable = str(Path(sys.executable).resolve())
        commands = {
            "large": TestCommand("large", (executable, "-c", "print('x' * 10000)")),
            "slow": TestCommand("slow", (executable, "-c", "import time; time.sleep(5)")),
        }
        with tempfile.TemporaryDirectory() as temporary:
            workspace = create_workspace(FIXTURE, Path(temporary) / "workspace")
            runner = TestRunner(commands)
            large = self.run_or_skip(runner, workspace, "large", max_output_bytes=100)
            slow = self.run_or_skip(runner, workspace, "slow", timeout_seconds=1)

        self.assertTrue(large.truncated)
        self.assertTrue(large.metadata_dict()["output_limit_hit"])
        self.assertTrue(slow.metadata_dict()["timed_out"])

    def test_sandbox_denies_reads_outside_the_workspace(self) -> None:
        executable = str(Path(sys.executable).resolve())
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            secret = root / "outside-secret.txt"
            secret.write_text("do-not-read", encoding="utf-8")
            workspace = create_workspace(FIXTURE, root / "workspace")
            command = TestCommand(
                "escape-read",
                (executable, "-c", f"from pathlib import Path; print(Path({str(secret)!r}).read_text())"),
            )

            result = self.run_or_skip(TestRunner({"escape-read": command}), workspace, "escape-read")

        self.assertNotEqual(result.metadata_dict()["exit_code"], 0)
        self.assertNotIn("do-not-read", result.content)

    def test_sandbox_denies_network_workspace_writes_and_child_processes(self) -> None:
        executable = str(Path(sys.executable).resolve())
        commands = {
            "network": TestCommand(
                "network",
                (
                    executable,
                    "-c",
                    "import socket; s=socket.socket(); s.bind(('127.0.0.1', 0)); print('network-open')",
                ),
            ),
            "write": TestCommand(
                "write",
                (
                    executable,
                    "-c",
                    "from pathlib import Path; Path('src/tiny_parser.py').write_text('owned')",
                ),
            ),
            "spawn": TestCommand(
                "spawn",
                (
                    executable,
                    "-c",
                    "import subprocess; subprocess.run(['/bin/echo', 'spawned'], check=True)",
                ),
            ),
        }
        with tempfile.TemporaryDirectory() as temporary:
            workspace = create_workspace(FIXTURE, Path(temporary) / "workspace")
            original = (workspace.root / "src/tiny_parser.py").read_text(encoding="utf-8")
            runner = TestRunner(commands)
            results = {
                name: self.run_or_skip(runner, workspace, name)
                for name in commands
            }
            after = (workspace.root / "src/tiny_parser.py").read_text(encoding="utf-8")

        for name, result in results.items():
            with self.subTest(name=name):
                self.assertNotEqual(result.metadata_dict()["exit_code"], 0)
        self.assertNotIn("network-open", results["network"].content)
        self.assertNotIn("spawned\n", results["spawn"].content)
        self.assertEqual(after, original)


if __name__ == "__main__":
    unittest.main()
