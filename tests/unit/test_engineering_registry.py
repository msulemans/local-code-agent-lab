from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from localcode.actions import ActionValidationError
from localcode.decisions import DecisionValidator
from localcode.engineering_registry import (
    EngineeringToolRegistry,
    ProductionReviewRegistry,
    ToolSubsetRegistry,
)
from localcode.tools import ToolError, ToolResult
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
    def test_tool_subset_registry_exposes_and_enforces_exact_surface(self) -> None:
        validator = DecisionValidator.from_path(SCHEMAS)
        with tempfile.TemporaryDirectory() as temporary:
            workspace = create_workspace(FIXTURE, Path(temporary) / "workspace")
            registry = ToolSubsetRegistry(EngineeringToolRegistry(workspace), {"apply_patch"})

            self.assertEqual(registry.tool_names, ("apply_patch",))
            action = validator.validate(decision("read_file", {"path": "src/tiny_parser.py"}))
            with self.assertRaisesRegex(ValueError, "outside the tool subset"):
                registry.execute(action)

    def test_exact_eight_tool_surface_applies_patch_tests_and_reads_diff(self) -> None:
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
            ("apply_patch", "edit_file", "git_diff", "list_files", "read_file", "run_tests", "search_code", "write_file"),
        )
        self.assertIn("src/tiny_parser.py", patch_result.content)
        self.assertEqual(test_result.metadata_dict()["exit_code"], 0)
        self.assertIn("if text is None", diff_result.content)
        self.assertEqual(len(fake_tests.calls), 1)

    def test_test_command_enum_is_enforced_before_registry_execution(self) -> None:
        validator = DecisionValidator.from_path(SCHEMAS)

        with self.assertRaises(ActionValidationError):
            validator.validate(decision("run_tests", {"command_name": "terminal"}))

        with self.assertRaises(ActionValidationError):
            validator.validate(
                decision(
                    "run_tests",
                    {"command_name": "python-unittest", "max_output_bytes": 1_048_576},
                )
            )

    def test_review_registry_keeps_tests_readable_but_rejects_test_edits(self) -> None:
        validator = DecisionValidator.from_path(SCHEMAS)
        with tempfile.TemporaryDirectory() as temporary:
            workspace = create_workspace(FIXTURE, Path(temporary) / "workspace")
            registry = ProductionReviewRegistry(EngineeringToolRegistry(workspace, FakeTestRunner()))

            read = registry.execute(
                validator.validate(decision("read_file", {"path": "tests/test_tiny_parser.py"}))
            )
            with self.assertRaisesRegex(ToolError, "must repair production code"):
                registry.execute(
                    validator.validate(
                        decision(
                            "edit_file",
                            {
                                "path": "tests/test_tiny_parser.py",
                                "old_string": "assert",
                                "new_string": "assert True or",
                            },
                        )
                    )
                )
            with self.assertRaisesRegex(ToolError, "may not modify test files"):
                registry.execute(
                    validator.validate(
                        decision(
                            "apply_patch",
                            {
                                "patch": "diff --git a/tests/test_tiny_parser.py b/tests/test_tiny_parser.py\n"
                            },
                        )
                    )
                )

        self.assertIn("test_absent_text_is_empty", read.content)

        with self.assertRaises(ActionValidationError):
            validator.validate(
                decision(
                    "edit_file",
                    {
                        "path": "src/tiny_parser.py",
                        "old_string": "return text.strip()",
                        "new_string": "return text",
                        "max_bytes": 200,
                    },
                )
            )


if __name__ == "__main__":
    unittest.main()
