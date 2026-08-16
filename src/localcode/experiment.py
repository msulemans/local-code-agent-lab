"""Frozen experiment manifest and comparison runner for LocalCode treatments."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any, Callable

from .micro_suite import (
    MicroSuite,
    MicroSuiteRun,
    load_micro_suite,
    run_micro_suite,
    run_reviewed_micro_suite,
)


_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,79}$")
_CONFIGURATION_IDS = ("B0", "A1", "A2", "A3")
_KINDS = frozenset(
    {
        "single_shot_base",
        "micro_suite_loop",
        "agent_plus_review",
    }
)
_AVAILABILITY = frozenset({"implemented", "planned"})
_CONTEXT_MODES = frozenset({"simple", "retrieval"})

MicroSuiteLoader = Callable[[str | Path, str | Path, str | Path], MicroSuite]
MicroSuiteRunner = Callable[..., MicroSuiteRun]
ReviewedMicroSuiteRunner = Callable[..., MicroSuiteRun]


class ExperimentError(ValueError):
    """Raised when the experiment manifest or result contract is invalid."""


@dataclass(frozen=True, slots=True)
class ExperimentConfiguration:
    configuration_id: str
    label: str
    change: str
    kind: str
    availability: str
    context_mode: str | None = None


@dataclass(frozen=True, slots=True)
class ExperimentManifest:
    experiment_id: str
    suite_manifest: Path
    tool_schemas: Path
    fairness_controls: tuple[str, ...]
    configurations: tuple[ExperimentConfiguration, ...]
    repository_root: Path


@dataclass(frozen=True, slots=True)
class ExperimentCaseResult:
    case_id: str
    category: str
    success: bool
    termination_reason: str
    changed_paths: tuple[str, ...]
    test_exit_codes: tuple[int, ...]
    observation_error_codes: tuple[str, ...]
    source_unchanged: bool
    first_context_chars: int
    first_selected_paths: tuple[str, ...]
    review_disposition: str | None = None
    review_findings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ExperimentConfigurationResult:
    configuration_id: str
    label: str
    change: str
    kind: str
    availability: str
    context_mode: str | None
    status: str
    reason: str | None
    suite_id: str | None
    registered: int | None
    solved: int | None
    cases: tuple[ExperimentCaseResult, ...]

    @property
    def measured(self) -> bool:
        return self.status == "measured"


@dataclass(frozen=True, slots=True)
class ExperimentComparison:
    previous_configuration_id: str
    next_configuration_id: str
    status: str
    reason: str | None
    gained: tuple[str, ...]
    lost: tuple[str, ...]
    solved_both: tuple[str, ...]
    failed_both: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ExperimentRun:
    experiment_id: str
    suite_id: str
    fairness_controls: tuple[str, ...]
    configurations: tuple[ExperimentConfigurationResult, ...]
    adjacent_comparisons: tuple[ExperimentComparison, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "experiment_id": self.experiment_id,
            "suite_id": self.suite_id,
            "fairness_controls": list(self.fairness_controls),
            "configurations": [
                {
                    "configuration_id": configuration.configuration_id,
                    "label": configuration.label,
                    "change": configuration.change,
                    "kind": configuration.kind,
                    "availability": configuration.availability,
                    "context_mode": configuration.context_mode,
                    "status": configuration.status,
                    "reason": configuration.reason,
                    "suite_id": configuration.suite_id,
                    "registered": configuration.registered,
                    "solved": configuration.solved,
                    "cases": [
                        {
                            "case_id": case.case_id,
                            "category": case.category,
                            "success": case.success,
                            "termination_reason": case.termination_reason,
                            "changed_paths": list(case.changed_paths),
                            "test_exit_codes": list(case.test_exit_codes),
                            "observation_error_codes": list(case.observation_error_codes),
                            "source_unchanged": case.source_unchanged,
                            "first_context_chars": case.first_context_chars,
                            "first_selected_paths": list(case.first_selected_paths),
                            "review_disposition": case.review_disposition,
                            "review_findings": list(case.review_findings),
                        }
                        for case in configuration.cases
                    ],
                }
                for configuration in self.configurations
            ],
            "adjacent_comparisons": [
                {
                    "previous_configuration_id": comparison.previous_configuration_id,
                    "next_configuration_id": comparison.next_configuration_id,
                    "status": comparison.status,
                    "reason": comparison.reason,
                    "gained": list(comparison.gained),
                    "lost": list(comparison.lost),
                    "solved_both": list(comparison.solved_both),
                    "failed_both": list(comparison.failed_both),
                }
                for comparison in self.adjacent_comparisons
            ],
        }


def load_experiment_manifest(
    manifest_path: str | Path,
    repository_root: str | Path,
) -> ExperimentManifest:
    """Load the frozen experiment definition for the current benchmark layer."""

    manifest_file = Path(manifest_path)
    root = Path(repository_root).resolve(strict=True)
    try:
        document = json.loads(manifest_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ExperimentError(f"cannot load experiment manifest: {manifest_file}") from exc
    expected_fields = {
        "schema_version",
        "experiment_id",
        "suite_manifest",
        "tool_schemas",
        "fairness_controls",
        "configurations",
    }
    if not isinstance(document, dict) or set(document) != expected_fields:
        raise ExperimentError("experiment manifest has unexpected top-level fields")
    if document["schema_version"] != 1:
        raise ExperimentError("experiment manifest schema_version must equal 1")

    experiment_id = document["experiment_id"]
    if not isinstance(experiment_id, str) or _SAFE_ID.fullmatch(experiment_id) is None:
        raise ExperimentError("experiment ID is invalid")

    suite_manifest = _resolve_manifest_path(root, document["suite_manifest"], "suite_manifest")
    tool_schemas = _resolve_manifest_path(root, document["tool_schemas"], "tool_schemas")

    fairness_controls = document["fairness_controls"]
    if (
        not isinstance(fairness_controls, list)
        or len(fairness_controls) < 4
        or any(not isinstance(value, str) or not value for value in fairness_controls)
    ):
        raise ExperimentError("fairness_controls must be a bounded non-empty string list")

    raw_configurations = document["configurations"]
    if not isinstance(raw_configurations, list) or len(raw_configurations) != len(_CONFIGURATION_IDS):
        raise ExperimentError("experiment must register exactly four configurations")
    configurations = tuple(_load_configuration(raw) for raw in raw_configurations)
    observed_ids = tuple(configuration.configuration_id for configuration in configurations)
    if observed_ids != _CONFIGURATION_IDS:
        raise ExperimentError(
            f"experiment configuration order must be {_CONFIGURATION_IDS}; observed {observed_ids}"
        )
    return ExperimentManifest(
        experiment_id=experiment_id,
        suite_manifest=suite_manifest,
        tool_schemas=tool_schemas,
        fairness_controls=tuple(fairness_controls),
        configurations=configurations,
        repository_root=root,
    )


def run_experiment(
    manifest: ExperimentManifest,
    *,
    suite_loader: MicroSuiteLoader = load_micro_suite,
    suite_runner: MicroSuiteRunner = run_micro_suite,
    reviewed_suite_runner: ReviewedMicroSuiteRunner = run_reviewed_micro_suite,
) -> ExperimentRun:
    """Run every currently supported configuration against one frozen suite."""

    suite = suite_loader(
        manifest.suite_manifest,
        manifest.tool_schemas,
        manifest.repository_root,
    )
    configuration_results = tuple(
        _run_configuration(configuration, suite, suite_runner, reviewed_suite_runner)
        for configuration in manifest.configurations
    )
    comparisons = tuple(
        _compare_configurations(previous, current)
        for previous, current in zip(configuration_results, configuration_results[1:])
    )
    return ExperimentRun(
        experiment_id=manifest.experiment_id,
        suite_id=suite.suite_id,
        fairness_controls=manifest.fairness_controls,
        configurations=configuration_results,
        adjacent_comparisons=comparisons,
    )


def _run_configuration(
    configuration: ExperimentConfiguration,
    suite: MicroSuite,
    suite_runner: MicroSuiteRunner,
    reviewed_suite_runner: ReviewedMicroSuiteRunner,
) -> ExperimentConfigurationResult:
    if configuration.availability != "implemented":
        return _unavailable_configuration(
            configuration,
            reason="configuration is registered but not implemented yet",
        )
    if configuration.kind == "single_shot_base":
        suite_run = suite_runner(suite, context_mode="single_shot")
        return _configuration_result(configuration, suite_run)
    if configuration.kind == "agent_plus_review":
        suite_run = reviewed_suite_runner(suite)
        return _configuration_result(configuration, suite_run)
    if configuration.kind != "micro_suite_loop":
        return _unavailable_configuration(
            configuration,
            reason=f"runner for {configuration.kind!r} is not implemented yet",
        )
    if configuration.context_mode is None:
        raise ExperimentError(
            f"implemented configuration {configuration.configuration_id} must declare context_mode"
        )
    suite_run = suite_runner(suite, context_mode=configuration.context_mode)
    return _configuration_result(configuration, suite_run)


def _configuration_result(
    configuration: ExperimentConfiguration,
    suite_run: MicroSuiteRun,
) -> ExperimentConfigurationResult:
    cases = tuple(
        ExperimentCaseResult(
            case_id=case.case_id,
            category=case.category,
            success=case.success,
            termination_reason=case.termination_reason.value,
            changed_paths=case.changed_paths,
            test_exit_codes=case.test_exit_codes,
            observation_error_codes=case.observation_error_codes,
            source_unchanged=case.source_unchanged,
            first_context_chars=case.first_context_chars,
            first_selected_paths=case.first_selected_paths,
            review_disposition=case.review_disposition,
            review_findings=case.review_findings,
        )
        for case in suite_run.cases
    )
    return ExperimentConfigurationResult(
        configuration_id=configuration.configuration_id,
        label=configuration.label,
        change=configuration.change,
        kind=configuration.kind,
        availability=configuration.availability,
        context_mode=configuration.context_mode,
        status="measured",
        reason=None,
        suite_id=suite_run.suite_id,
        registered=suite_run.registered,
        solved=suite_run.solved,
        cases=cases,
    )


def _compare_configurations(
    previous: ExperimentConfigurationResult,
    current: ExperimentConfigurationResult,
) -> ExperimentComparison:
    if not previous.measured or not current.measured:
        return ExperimentComparison(
            previous_configuration_id=previous.configuration_id,
            next_configuration_id=current.configuration_id,
            status="unavailable",
            reason="one or both configurations are not implemented yet",
            gained=(),
            lost=(),
            solved_both=(),
            failed_both=(),
        )
    previous_cases = {case.case_id: case.success for case in previous.cases}
    current_cases = {case.case_id: case.success for case in current.cases}
    if tuple(sorted(previous_cases)) != tuple(sorted(current_cases)):
        return ExperimentComparison(
            previous_configuration_id=previous.configuration_id,
            next_configuration_id=current.configuration_id,
            status="unavailable",
            reason="configuration case sets do not match",
            gained=(),
            lost=(),
            solved_both=(),
            failed_both=(),
        )
    gained = []
    lost = []
    solved_both = []
    failed_both = []
    for case_id in sorted(previous_cases):
        before = previous_cases[case_id]
        after = current_cases[case_id]
        if not before and after:
            gained.append(case_id)
        elif before and not after:
            lost.append(case_id)
        elif before and after:
            solved_both.append(case_id)
        else:
            failed_both.append(case_id)
    return ExperimentComparison(
        previous_configuration_id=previous.configuration_id,
        next_configuration_id=current.configuration_id,
        status="measured",
        reason=None,
        gained=tuple(gained),
        lost=tuple(lost),
        solved_both=tuple(solved_both),
        failed_both=tuple(failed_both),
    )


def _unavailable_configuration(
    configuration: ExperimentConfiguration,
    *,
    reason: str,
) -> ExperimentConfigurationResult:
    return ExperimentConfigurationResult(
        configuration_id=configuration.configuration_id,
        label=configuration.label,
        change=configuration.change,
        kind=configuration.kind,
        availability=configuration.availability,
        context_mode=configuration.context_mode,
        status="unavailable",
        reason=reason,
        suite_id=None,
        registered=None,
        solved=None,
        cases=(),
    )


def _load_configuration(raw: Any) -> ExperimentConfiguration:
    expected_fields = {
        "id",
        "label",
        "change",
        "kind",
        "availability",
        "context_mode",
    }
    if not isinstance(raw, dict) or set(raw) != expected_fields:
        raise ExperimentError("experiment configuration fields are invalid")
    configuration_id = raw["id"]
    label = raw["label"]
    change = raw["change"]
    kind = raw["kind"]
    availability = raw["availability"]
    context_mode = raw["context_mode"]
    if not isinstance(configuration_id, str) or configuration_id not in _CONFIGURATION_IDS:
        raise ExperimentError("experiment configuration ID is invalid")
    for field_name, value in (("label", label), ("change", change)):
        if not isinstance(value, str) or not value or len(value) > 200:
            raise ExperimentError(f"experiment configuration {field_name} is invalid")
    if kind not in _KINDS:
        raise ExperimentError(f"experiment configuration kind is invalid: {kind!r}")
    if availability not in _AVAILABILITY:
        raise ExperimentError(f"experiment configuration availability is invalid: {availability!r}")
    if context_mode is not None and context_mode not in _CONTEXT_MODES:
        raise ExperimentError(f"experiment context_mode is invalid: {context_mode!r}")
    if kind == "micro_suite_loop" and context_mode is None:
        raise ExperimentError("micro_suite_loop configurations must declare context_mode")
    if kind != "micro_suite_loop" and context_mode is not None:
        raise ExperimentError("non-loop configurations must not declare context_mode")
    return ExperimentConfiguration(
        configuration_id=configuration_id,
        label=label,
        change=change,
        kind=kind,
        availability=availability,
        context_mode=context_mode,
    )


def _resolve_manifest_path(root: Path, value: Any, field_name: str) -> Path:
    relative = _safe_relative(value, field_name)
    destination = (root / Path(relative.as_posix())).resolve(strict=True)
    try:
        destination.relative_to(root)
    except ValueError as exc:
        raise ExperimentError(f"{field_name} escapes repository root") from exc
    if not destination.is_file():
        raise ExperimentError(f"{field_name} must point to a file")
    return destination


def _safe_relative(value: Any, field_name: str) -> PurePosixPath:
    if not isinstance(value, str) or not value:
        raise ExperimentError(f"{field_name} must be a non-empty relative path")
    relative = PurePosixPath(value)
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        raise ExperimentError(f"{field_name} must stay within the repository")
    return relative
