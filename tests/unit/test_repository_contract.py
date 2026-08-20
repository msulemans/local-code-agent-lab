from pathlib import Path
import unittest


class RepositoryContractTests(unittest.TestCase):
    def test_fixture_repository_is_present_but_not_imported(self) -> None:
        fixture = Path("tests/fixtures/micro_repos/parser_none")

        self.assertTrue((fixture / "ISSUE.md").is_file())
        self.assertTrue((fixture / "src/tiny_parser.py").is_file())
        self.assertTrue((fixture / "tests/test_tiny_parser.py").is_file())

    def test_guarded_engineering_runtime_exists_without_model_modules(self) -> None:
        source = Path("src/localcode")
        required = {
            "actions.py",
            "context.py",
            "controller.py",
            "decisions.py",
            "demo_repair.py",
            "engineering_registry.py",
            "experiment.py",
            "loop.py",
            "patches.py",
            "real_benchmark.py",
            "real_benchmark_adapters.py",
            "registry.py",
            "review.py",
            "retrieval.py",
            "test_runner.py",
            "training_data.py",
            "training_baseline.py",
            "training_export.py",
            "training_run.py",
            "training_sources.py",
            "tui.py",
            "workspace.py",
        }
        forbidden = {"models"}

        self.assertTrue((source / "tools").is_dir())
        names = {path.name for path in source.iterdir()}
        self.assertTrue(required.issubset(names))
        self.assertTrue(forbidden.isdisjoint(names))


if __name__ == "__main__":
    unittest.main()
