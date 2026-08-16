from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
import unittest

from localcode.patches import apply_patch
from localcode.tools import ToolError, git_diff
from localcode.workspace import create_workspace, edit_file, write_file


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


class WorkspaceAndPatchTests(unittest.TestCase):
    def test_workspace_is_a_clean_git_copy_without_generated_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = create_workspace(FIXTURE, Path(temporary) / "workspace")

            self.assertNotEqual(workspace.root, FIXTURE)
            self.assertTrue((workspace.root / ".git").is_dir())
            self.assertFalse(any(path.name == "__pycache__" for path in workspace.root.rglob("*")))
            self.assertEqual(workspace.copied_files, 3)
            self.assertEqual(len(workspace.baseline_commit), 40)
            status = subprocess.run(
                ["git", "-C", str(workspace.root), "status", "--porcelain"],
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertEqual(status.stdout, "")

    def test_workspace_refuses_existing_destination_limits_and_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            existing = root / "existing"
            existing.mkdir()
            with self.assertRaisesRegex(ToolError, "already exists"):
                create_workspace(FIXTURE, existing)
            with self.assertRaisesRegex(ToolError, "exceeds 1 files"):
                create_workspace(FIXTURE, root / "limited", max_files=1)

        with tempfile.TemporaryDirectory() as source_temp, tempfile.TemporaryDirectory() as target_temp:
            source = Path(source_temp)
            (source / "file.py").write_text("value = 1\n", encoding="utf-8")
            (source / "link.py").symlink_to(source / "file.py")
            with self.assertRaisesRegex(ToolError, "symlink"):
                create_workspace(source, Path(target_temp) / "workspace")

            workspace = create_workspace(
                source,
                Path(target_temp) / "skipping-workspace",
                skip_symlinks=True,
            )
            self.assertTrue((workspace.root / "file.py").is_file())
            self.assertFalse((workspace.root / "link.py").exists())
            self.assertEqual(workspace.copied_files, 1)

    def test_valid_patch_changes_only_disposable_workspace_and_produces_diff(self) -> None:
        source_before = (FIXTURE / "src/tiny_parser.py").read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as temporary:
            workspace = create_workspace(FIXTURE, Path(temporary) / "workspace")

            result = apply_patch(workspace.root, VALID_PATCH)
            diff = git_diff(workspace.root)

            self.assertEqual(result.metadata_dict()["file_count"], 1)
            self.assertIn("if text is None", diff.content)
            self.assertIn("return \"\"", diff.content)
        self.assertEqual((FIXTURE / "src/tiny_parser.py").read_text(encoding="utf-8"), source_before)

    def test_escape_creation_rename_and_binary_markers_are_rejected(self) -> None:
        unsafe_patches = (
            VALID_PATCH.replace("src/tiny_parser.py", "../outside.py"),
            VALID_PATCH.replace("--- a/src/tiny_parser.py", "new file mode 100644\n--- /dev/null"),
            VALID_PATCH.replace(
                "diff --git a/src/tiny_parser.py b/src/tiny_parser.py",
                "diff --git a/src/tiny_parser.py b/src/renamed.py",
            ),
            "diff --git a/src/tiny_parser.py b/src/tiny_parser.py\nGIT binary patch\n",
        )
        for patch in unsafe_patches:
            with self.subTest(patch=patch[:80]), tempfile.TemporaryDirectory() as temporary:
                workspace = create_workspace(FIXTURE, Path(temporary) / "workspace")
                with self.assertRaises(ToolError):
                    apply_patch(workspace.root, patch)
                self.assertEqual(git_diff(workspace.root).content, "")

    def test_malformed_oversized_staged_and_untracked_workspaces_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = create_workspace(FIXTURE, Path(temporary) / "workspace")
            with self.assertRaises(ToolError):
                apply_patch(workspace.root, "not a patch")
            with self.assertRaisesRegex(ToolError, "exceeds 10 bytes"):
                apply_patch(workspace.root, VALID_PATCH, max_bytes=10)

            (workspace.root / "untracked.py").write_text("value = 1\n", encoding="utf-8")
            with self.assertRaisesRegex(ToolError, "untracked"):
                apply_patch(workspace.root, VALID_PATCH)

        with tempfile.TemporaryDirectory() as temporary:
            workspace = create_workspace(FIXTURE, Path(temporary) / "workspace")
            target = workspace.root / "src/tiny_parser.py"
            target.write_text(target.read_text(encoding="utf-8") + "# staged\n", encoding="utf-8")
            subprocess.run(
                ["git", "-C", str(workspace.root), "add", "src/tiny_parser.py"],
                check=True,
            )
            with self.assertRaisesRegex(ToolError, "staged"):
                apply_patch(workspace.root, VALID_PATCH)

    def test_second_patch_can_revise_existing_unstaged_changes(self) -> None:
        revision = """diff --git a/src/tiny_parser.py b/src/tiny_parser.py
--- a/src/tiny_parser.py
+++ b/src/tiny_parser.py
@@ -1,4 +1,4 @@
 def parse_value(text: str | None) -> str:
     if text is None:
         return ""
-    return text.strip()
+    return text.strip(" ")
"""
        with tempfile.TemporaryDirectory() as temporary:
            workspace = create_workspace(FIXTURE, Path(temporary) / "workspace")
            apply_patch(workspace.root, VALID_PATCH)

            result = apply_patch(workspace.root, revision)

            self.assertEqual(result.metadata_dict()["file_count"], 1)
            self.assertIn('return text.strip(" ")', git_diff(workspace.root).content)

    def test_write_file_replaces_existing_tracked_file_and_shows_in_diff(self) -> None:
        fixed = "def parse_value(text: str | None) -> str:\n    if text is None:\n        return \"\"\n    return text.strip()\n"
        with tempfile.TemporaryDirectory() as temporary:
            workspace = create_workspace(FIXTURE, Path(temporary) / "workspace")

            result = write_file(workspace.root, "src/tiny_parser.py", fixed)

            self.assertEqual(result.metadata_dict()["path"], "src/tiny_parser.py")
            self.assertEqual(
                (workspace.root / "src/tiny_parser.py").read_text(encoding="utf-8"),
                fixed,
            )
            diff = git_diff(workspace.root).content
            self.assertIn("diff --git a/src/tiny_parser.py", diff)
            self.assertIn('+    if text is None:', diff)

    def test_write_file_rejects_missing_untracked_and_oversized_targets(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = create_workspace(FIXTURE, Path(temporary) / "workspace")
            with self.assertRaisesRegex(ToolError, "path does not exist"):
                write_file(workspace.root, "src/nope.py", "x")
            with self.assertRaisesRegex(ToolError, "refuses a file Git does not track"):
                (workspace.root / "src").mkdir(parents=True, exist_ok=True)
                (workspace.root / "src/new_file.py").write_text("x", encoding="utf-8")
                write_file(workspace.root, "src/new_file.py", "x")
            with self.assertRaisesRegex(ToolError, "content exceeds"):
                write_file(workspace.root, "src/tiny_parser.py", "x" * 10, max_bytes=5)

    def test_edit_file_replaces_one_unique_snippet_without_line_numbers(self) -> None:
        old_snippet = "    return text.strip()"
        new_snippet = "    if text is None:\n        return \"\"\n    return text.strip()"
        with tempfile.TemporaryDirectory() as temporary:
            workspace = create_workspace(FIXTURE, Path(temporary) / "workspace")

            result = edit_file(workspace.root, "src/tiny_parser.py", old_snippet, new_snippet)

            self.assertEqual(result.metadata_dict()["path"], "src/tiny_parser.py")
            self.assertIn(
                "if text is None",
                (workspace.root / "src/tiny_parser.py").read_text(encoding="utf-8"),
            )
            self.assertIn("diff --git a/src/tiny_parser.py", git_diff(workspace.root).content)

    def test_edit_file_requires_a_unique_match_and_tracked_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = create_workspace(FIXTURE, Path(temporary) / "workspace")
            with self.assertRaisesRegex(ToolError, "must match exactly once"):
                edit_file(workspace.root, "src/tiny_parser.py", "text", "x")
            with self.assertRaisesRegex(ToolError, "must match exactly once"):
                edit_file(workspace.root, "src/tiny_parser.py", "does not exist", "x")
            with self.assertRaisesRegex(ToolError, "refuses a file Git does not track"):
                (workspace.root / "src").mkdir(parents=True, exist_ok=True)
                (workspace.root / "src/new_file.py").write_text("x", encoding="utf-8")
                edit_file(workspace.root, "src/new_file.py", "x", "y")

    def test_edit_file_tolerates_wrong_indentation_and_reindents(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = create_workspace(FIXTURE, Path(temporary) / "workspace")
            target = workspace.root / "src/tiny_parser.py"
            target.write_text(
                "class Mixin(object):\n"
                "    @staticmethod\n"
                "    def _encode(data):\n"
                "        if isinstance(data, bytes):\n"
                "            return data\n",
                encoding="utf-8",
            )

            result = edit_file(
                workspace.root,
                "src/tiny_parser.py",
                "    if isinstance(data, bytes):\n        return data",
                "    if isinstance(data, bytes):\n"
                "        return data\n"
                "    return to_native_string(data)",
            )
            after = target.read_text(encoding="utf-8")

        # A multi-line snippet with misremembered indentation (4/8 instead of
        # 8/12) must match tolerantly and re-indent the replacement (m056).
        self.assertEqual(result.metadata_dict()["match"], "indent_tolerant")
        self.assertEqual(
            after,
            "class Mixin(object):\n"
            "    @staticmethod\n"
            "    def _encode(data):\n"
            "        if isinstance(data, bytes):\n"
            "            return data\n"
            "        return to_native_string(data)\n",
        )

    def test_edit_file_indent_tolerant_match_must_stay_unique(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = create_workspace(FIXTURE, Path(temporary) / "workspace")
            (workspace.root / "src/tiny_parser.py").write_text(
                "def one():\n    value = parse()\n\ndef two():\n        value = parse()\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ToolError, "must match exactly once"):
                edit_file(workspace.root, "src/tiny_parser.py", "value = parse()", "value = None")


if __name__ == "__main__":
    unittest.main()
