from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
import unittest

from localcode.tools import ToolError, git_diff, list_files, read_file, search_code
from localcode.tools.files import MAX_FILE_BYTES


class RepositoryToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        (self.root / "src").mkdir()
        (self.root / "tests").mkdir()
        (self.root / "src/parser.py").write_text(
            "def parse(text):\n    return text.strip()\n",
            encoding="utf-8",
        )
        (self.root / "tests/test_parser.py").write_text(
            "def test_parse():\n    assert parse(' x ') == 'x'\n",
            encoding="utf-8",
        )
        (self.root / ".env").write_text("TOKEN=do-not-read\n", encoding="utf-8")
        (self.root / "secret.pem").write_text("PRIVATE\n", encoding="utf-8")
        (self.root / ".git").mkdir()
        (self.root / ".git/config").write_text("hidden\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_list_files_is_sorted_and_excludes_sensitive_paths(self) -> None:
        result = list_files(self.root)

        self.assertEqual(result.content.splitlines(), ["src/parser.py", "tests/test_parser.py"])
        self.assertFalse(result.truncated)

    def test_list_files_reports_truncation_at_result_limit(self) -> None:
        result = list_files(self.root, max_results=1)

        self.assertEqual(len(result.content.splitlines()), 1)
        self.assertTrue(result.truncated)

    def test_list_files_depth_limit_prunes_deeper_content(self) -> None:
        nested = self.root / "src/deep/deeper"
        nested.mkdir(parents=True)
        (nested / "hidden.py").write_text("hidden = True\n", encoding="utf-8")

        result = list_files(self.root, max_depth=1)

        self.assertNotIn("hidden.py", result.content)

    def test_read_file_returns_bounded_line_numbered_excerpt(self) -> None:
        result = read_file(self.root, "src/parser.py", start_line=2, max_lines=1)

        self.assertEqual(result.content, "     2 |     return text.strip()")
        self.assertFalse(result.truncated)
        self.assertEqual(result.metadata_dict()["file"], "src/parser.py")

    def test_absolute_and_parent_paths_are_rejected(self) -> None:
        with self.assertRaisesRegex(ToolError, "stay within") as absolute:
            read_file(self.root, str(self.root / "src/parser.py"))
        with self.assertRaisesRegex(ToolError, "stay within") as parent:
            read_file(self.root, "../outside.py")

        self.assertEqual(absolute.exception.code, "path_escape")
        self.assertEqual(parent.exception.code, "path_escape")

    def test_symlink_is_rejected_even_when_it_points_outside(self) -> None:
        outside = self.root.parent / f"{self.root.name}-outside.txt"
        outside.write_text("outside secret\n", encoding="utf-8")
        try:
            (self.root / "src/link.py").symlink_to(outside)

            with self.assertRaises(ToolError) as raised:
                read_file(self.root, "src/link.py")

            self.assertEqual(raised.exception.code, "symlink_rejected")
        finally:
            outside.unlink(missing_ok=True)

    def test_secret_like_files_are_rejected(self) -> None:
        for path in (".env", "secret.pem", ".git/config"):
            with self.subTest(path=path), self.assertRaises(ToolError) as raised:
                read_file(self.root, path)
            self.assertEqual(raised.exception.code, "excluded_path")

    def test_binary_and_oversized_files_are_rejected(self) -> None:
        (self.root / "src/data.bin").write_bytes(b"abc\x00def")
        (self.root / "src/large.py").write_bytes(b"x" * (MAX_FILE_BYTES + 1))

        with self.assertRaises(ToolError) as binary:
            read_file(self.root, "src/data.bin")
        with self.assertRaises(ToolError) as large:
            read_file(self.root, "src/large.py")

        self.assertEqual(binary.exception.code, "binary_file")
        self.assertEqual(large.exception.code, "file_too_large")

    def test_search_supports_literal_regex_glob_and_case_controls(self) -> None:
        literal = search_code(self.root, "text.strip", glob="*.py")
        regex = search_code(self.root, r"ASSERT PARSE", regex=True, case_sensitive=False)

        self.assertIn("src/parser.py:2", literal.content)
        self.assertIn("tests/test_parser.py:2", regex.content)

    def test_search_rejects_invalid_regex_and_never_returns_secret_content(self) -> None:
        with self.assertRaises(ToolError) as invalid:
            search_code(self.root, "(", regex=True)
        secret_search = search_code(self.root, "do-not-read")

        self.assertEqual(invalid.exception.code, "invalid_regex")
        self.assertEqual(secret_search.content, "")

    def test_search_result_limit_is_explicit(self) -> None:
        (self.root / "src/many.py").write_text("needle\nneedle\n", encoding="utf-8")

        result = search_code(self.root, "needle", max_results=1)

        self.assertEqual(len(result.content.splitlines()), 1)
        self.assertTrue(result.truncated)

    def test_search_excludes_vendored_third_party_code(self) -> None:
        vendored = self.root / "src/vendor"
        vendored.mkdir(parents=True)
        (vendored / "third.py").write_text("needle = True\n", encoding="utf-8")
        (self.root / "src/parser.py").write_text(
            "def parse(text):\n    return text.strip()\nneedle = True\n",
            encoding="utf-8",
        )

        result = search_code(self.root, "needle")

        # Vendored third-party code is never the fix site and must not
        # misdirect the agent (D-044; requests/packages/urllib3 in m042).
        self.assertNotIn("src/vendor/third.py", result.content)
        self.assertIn("src/parser.py", result.content)


class GitDiffToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self._git("init", "-q")
        (self.root / "visible.py").write_text("value = 1\n", encoding="utf-8")
        (self.root / ".env").write_text("TOKEN=old-secret\n", encoding="utf-8")
        self._git("add", "visible.py", ".env")
        self._git(
            "-c",
            "user.name=LocalCode Test",
            "-c",
            "user.email=localcode@example.invalid",
            "commit",
            "-qm",
            "fixture baseline",
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def _git(self, *arguments: str) -> None:
        subprocess.run(
            ["git", "-C", str(self.root), *arguments],
            check=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def test_git_diff_filters_secret_paths(self) -> None:
        (self.root / "visible.py").write_text("value = 2\n", encoding="utf-8")
        (self.root / ".env").write_text("TOKEN=new-secret\n", encoding="utf-8")

        result = git_diff(self.root)

        self.assertIn("value = 2", result.content)
        self.assertNotIn("new-secret", result.content)
        self.assertNotIn(".env", result.content)
        self.assertEqual(result.metadata_dict()["excluded_file_count"], 1)

    def test_git_diff_is_bounded_and_reports_truncation(self) -> None:
        (self.root / "visible.py").write_text("\n".join(f"value_{n} = {n}" for n in range(50)), encoding="utf-8")

        result = git_diff(self.root, max_bytes=80)

        self.assertLessEqual(len(result.content.encode("utf-8")), 80)
        self.assertTrue(result.truncated)

    def test_git_diff_rejects_repository_root_mismatch(self) -> None:
        nested = self.root / "nested"
        nested.mkdir()

        with self.assertRaises(ToolError) as raised:
            git_diff(nested)

        self.assertEqual(raised.exception.code, "git_root_mismatch")

    def test_git_diff_reports_non_repository_as_typed_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory, self.assertRaises(ToolError) as raised:
            git_diff(directory)

        self.assertEqual(raised.exception.code, "git_error")


if __name__ == "__main__":
    unittest.main()
