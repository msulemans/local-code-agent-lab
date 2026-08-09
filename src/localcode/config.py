"""Strict, standard-library configuration loading for LocalCode."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path, PurePath
from typing import Any, Mapping


class ConfigError(ValueError):
    """Raised when a LocalCode configuration violates its schema."""


_CONFIG_KEYS = frozenset(
    {
        "schema_version",
        "project_name",
        "event_schema_version",
        "runs_directory",
        "fixture_root",
    }
)


def _positive_integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ConfigError(f"{field} must be a positive integer")
    return value


def _non_empty_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{field} must be a non-empty string")
    return value


def _relative_path(value: object, field: str) -> str:
    path = _non_empty_string(value, field)
    pure_path = PurePath(path)
    if pure_path.is_absolute() or ".." in pure_path.parts:
        raise ConfigError(f"{field} must be a repository-relative path")
    return path


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    """Validated repository-level settings, independent of any model backend."""

    schema_version: int
    project_name: str
    event_schema_version: int
    runs_directory: str
    fixture_root: str

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> "RuntimeConfig":
        keys = set(values)
        missing = _CONFIG_KEYS - keys
        unknown = keys - _CONFIG_KEYS
        if missing:
            raise ConfigError(f"missing configuration fields: {sorted(missing)}")
        if unknown:
            raise ConfigError(f"unknown configuration fields: {sorted(unknown)}")

        schema_version = _positive_integer(values["schema_version"], "schema_version")
        if schema_version != 1:
            raise ConfigError(f"unsupported configuration schema_version: {schema_version}")

        return cls(
            schema_version=schema_version,
            project_name=_non_empty_string(values["project_name"], "project_name"),
            event_schema_version=_positive_integer(
                values["event_schema_version"], "event_schema_version"
            ),
            runs_directory=_relative_path(values["runs_directory"], "runs_directory"),
            fixture_root=_relative_path(values["fixture_root"], "fixture_root"),
        )


def load_config(path: str | Path) -> RuntimeConfig:
    """Load and validate a UTF-8 JSON configuration file."""

    config_path = Path(path)
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"could not read configuration: {config_path}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"configuration is not valid JSON: {config_path}") from exc

    if not isinstance(raw, dict):
        raise ConfigError("configuration root must be a JSON object")
    return RuntimeConfig.from_mapping(raw)
