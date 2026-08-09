from pathlib import Path
import unittest


class RepositoryContractTests(unittest.TestCase):
    def test_fixture_repository_is_present_but_not_imported(self) -> None:
        fixture = Path("tests/fixtures/micro_repos/parser_none")

        self.assertTrue((fixture / "ISSUE.md").is_file())
        self.assertTrue((fixture / "src/tiny_parser.py").is_file())
        self.assertTrue((fixture / "tests/test_tiny_parser.py").is_file())

    def test_one_turn_controller_exists_without_later_loop_modules(self) -> None:
        source = Path("src/localcode")
        required = {"actions.py", "controller.py", "registry.py"}
        forbidden = {"workspace.py", "models", "tui.py", "agent_loop.py"}

        self.assertTrue((source / "tools").is_dir())
        names = {path.name for path in source.iterdir()}
        self.assertTrue(required.issubset(names))
        self.assertTrue(forbidden.isdisjoint(names))


if __name__ == "__main__":
    unittest.main()
