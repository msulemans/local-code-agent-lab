from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from localcode.config import ConfigError, RuntimeConfig, load_config


VALID_CONFIG = {
    "schema_version": 1,
    "project_name": "localcode",
    "event_schema_version": 1,
    "runs_directory": "runs",
    "fixture_root": "tests/fixtures/micro_repos",
}


class RuntimeConfigTests(unittest.TestCase):
    def test_repository_config_loads(self) -> None:
        config = load_config("configs/runtime.json")

        self.assertEqual(config, RuntimeConfig.from_mapping(VALID_CONFIG))

    def test_unknown_field_is_rejected(self) -> None:
        values = dict(VALID_CONFIG, surprise=True)

        with self.assertRaisesRegex(ConfigError, "unknown configuration fields"):
            RuntimeConfig.from_mapping(values)

    def test_parent_path_is_rejected(self) -> None:
        values = dict(VALID_CONFIG, runs_directory="../outside")

        with self.assertRaisesRegex(ConfigError, "repository-relative"):
            RuntimeConfig.from_mapping(values)

    def test_invalid_json_is_wrapped_as_config_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "broken.json"
            path.write_text("{", encoding="utf-8")

            with self.assertRaisesRegex(ConfigError, "not valid JSON"):
                load_config(path)


if __name__ == "__main__":
    unittest.main()
