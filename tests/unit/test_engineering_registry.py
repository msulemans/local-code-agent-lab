from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from localcode.actions import ActionValidationError
from localcode.decisions import DecisionValidator
from localcode.engineering_registry import EngineeringToolRegistry
from localcode.tools import ToolResult
from localcode.workspace import create_workspace


FIXTURE = Path("tests/fixtures/micro_repos/parser_none").resolve()
SCHEMAS = Path("benchmarks/micro_agent/tool_schemas.json")
PATCH = """diff --git a/src/tiny_parser.py b/src/tiny_parser.py
--- a/src/tiny_parser.py
+++ b/src/tiny_parser.py
@@ -1,2 +1,4 @@
 def parse_value(text: str | None) -> str:
+    if text is None:
+        return ""
     return text.strip()
"""


def decision(tool: str, arguments: dict[str, object]) -> str:
    return json.dumps(
        {
            "protocol_version": "1",
            "thought_summary": "Use the registered engineering capability.",
            "decision": {"kind": "tool", "tool": tool, "arguments": arguments},
        }
    )


class FakeTestRunner:
    def __init__(self) -> None:
        self.calls = []

    def run(self, workspace, **arguments) -> ToolResult:
        self.calls.append((workspace, arguments))
        return ToolResult(
            content="OK",
            metadata=(
                ("command", arguments["command_name"]),
                ("exit_code", 0),
                ("sandboxed", True),
            ),
        )


class EngineeringRegistryTests(unittest.TestCase):
    def test_exact_six_tool_surface_applies_patch_tests_and_reads_diff(self) -> None:
        validator = DecisionValidator.from_path(SCHEMAS)
        fake_tests = FakeTestRunner()
        with tempfile.TemporaryDirectory() as temporary:
            workspace = create_workspace(FIXTURE, Path(temporary) / "workspace")
            registry = EngineeringToolRegistry(workspace, fake_tests)

            patch_result = registry.execute(validator.validate(decision("apply_patch", {"patch": PATCH})))
            test_result = registry.execute(
                validator.validate(decision("run_tests", {"command_name": "python-unittest"}))
            )
            diff_result = registry.execute(validator.validate(decision("git_diff", {})))

        self.assertEqual(
            registry.tool_names,
            ("apply_patch", "git_diff", "list_files", "read_file", "run_tests", "search_code"),
        )
        self.assertIn("src/tiny_parser.py", patch_result.content)
        self.assertEqual(test_result.metadata_dict()["exit_code"], 0)
        self.assertIn("if text is None", diff_result.content)
        self.assertEqual(len(fake_tests.calls), 1)

    def test_test_command_enum_is_enforced_before_registry_execution(self) -> None:
        validator = DecisionValidator.from_path(SCHEMAS)

        with self.assertRaises(ActionValidationError):
            validator.validate(decision("run_tests", {"command_name": "terminal"}))


if __name__ == "__main__":
    unittest.main()
