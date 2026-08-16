from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from localcode.micro_suite import load_micro_suite
from localcode.retrieval import (
    build_repository_map,
    evaluate_relevant_file_recall,
    select_retrieval_evidence,
)


ROOT = Path("tests/fixtures/micro_repos/parser_none")
MANIFEST = Path("benchmarks/micro_agent/suite_v1.json")
SCHEMAS = Path("benchmarks/micro_agent/tool_schemas.json")


class RetrievalTests(unittest.TestCase):
    def test_repository_map_classifies_files_and_symbols_deterministically(self) -> None:
        first = build_repository_map(ROOT)
        second = build_repository_map(ROOT)

        self.assertEqual(first, second)
        files = first.by_path()
        self.assertEqual(tuple(files), ("ISSUE.md", "src/tiny_parser.py", "tests/test_tiny_parser.py"))
        self.assertEqual(files["src/tiny_parser.py"].kind, "source")
        self.assertEqual(files["tests/test_tiny_parser.py"].kind, "test")
        self.assertEqual(files["src/tiny_parser.py"].symbols, ("parse_value",))

    def test_retrieval_pack_excludes_issue_and_recalls_parser_source(self) -> None:
        issue = (ROOT / "ISSUE.md").read_text(encoding="utf-8")

        pack = select_retrieval_evidence(ROOT, issue, max_files=2, max_total_chars=2_000)
        recall = evaluate_relevant_file_recall(pack, ("src/tiny_parser.py",))

        self.assertNotIn("ISSUE.md", pack.selected_paths)
        self.assertIn("src/tiny_parser.py", pack.selected_paths)
        self.assertEqual(recall.numerator, 1)
        self.assertEqual(recall.denominator, 1)
        self.assertEqual(recall.recall, 1.0)
        self.assertIn("parse_value", pack.to_context())

    def test_retrieval_respects_repository_policy_and_bounds(self) -> None:
        with tempfile.TemporaryDirectory(prefix="localcode-retrieval-") as temporary:
            root = Path(temporary)
            (root / "src").mkdir()
            (root / "tests").mkdir()
            (root / "src/app.py").write_text("def load_config():\n    return 1\n", encoding="utf-8")
            (root / "tests/test_app.py").write_text(
                "from src.app import load_config\n\ndef test_load_config():\n    assert load_config() == 1\n",
                encoding="utf-8",
            )
            (root / ".env").write_text("SECRET=1\n", encoding="utf-8")

            pack = select_retrieval_evidence(
                root,
                "load_config should return the configured value",
                max_files=2,
                max_total_chars=512,
            )

        self.assertNotIn(".env", pack.repository_map.by_path())
        self.assertEqual(set(pack.selected_paths), {"src/app.py", "tests/test_app.py"})
        self.assertLessEqual(len(pack.to_context()), 2_000)

    def test_symbol_definition_and_named_test_beat_frequent_usage(self) -> None:
        with tempfile.TemporaryDirectory(prefix="localcode-retrieval-symbol-") as temporary:
            root = Path(temporary)
            (root / "src/flask").mkdir(parents=True)
            (root / "tests").mkdir()
            (root / "src/flask/app.py").write_text(
                "\n".join(f"blueprint_{index} = Blueprint('name')" for index in range(80)) + "\n",
                encoding="utf-8",
            )
            (root / "src/flask/blueprints.py").write_text(
                "class BlueprintSetupState:\n"
                "    def register_blueprint(self, blueprint):\n"
                "        return blueprint.name\n"
                + "\n".join(f"setup_{index} = BlueprintSetupState" for index in range(50))
                + "\n\nclass Blueprint:\n"
                "    def __init__(self, name):\n"
                "        self.name = name\n",
                encoding="utf-8",
            )
            (root / "tests/test_blueprints.py").write_text(
                "def test_empty_blueprint_name():\n"
                "    assert Blueprint('')\n",
                encoding="utf-8",
            )

            pack = select_retrieval_evidence(
                root,
                "Require a non-empty name for Blueprints",
                max_files=3,
                max_total_chars=3_000,
            )

        self.assertEqual(pack.selected_paths[0], "src/flask/blueprints.py")
        self.assertIn("tests/test_blueprints.py", pack.selected_paths)
        self.assertIn("symbol", pack.excerpts[0].reason)
        self.assertIn("class Blueprint:", pack.excerpts[0].content)

    def test_registered_micro_suite_relevant_file_recall_under_fixed_budget(self) -> None:
        suite = load_micro_suite(MANIFEST, SCHEMAS, Path("."))
        recalled = 0
        expected = 0
        per_case = {}

        for case in suite.cases:
            issue = (case.fixture / case.issue_file).read_text(encoding="utf-8")
            pack = select_retrieval_evidence(
                case.fixture,
                issue,
                max_files=3,
                max_total_chars=3_000,
            )
            recall = evaluate_relevant_file_recall(pack, case.expected_changed_paths)
            per_case[case.case_id] = recall.recall
            recalled += recall.numerator
            expected += recall.denominator

        self.assertEqual(expected, 9)
        self.assertEqual(recalled, expected, per_case)


if __name__ == "__main__":
    unittest.main()
