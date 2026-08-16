"""Pinned real-issue benchmark manifest and evaluator-backed four-way runner."""

from __future__ import annotations

from dataclasses import dataclass
import json
from math import isfinite
from pathlib import Path
import re
from typing import Any, Callable, Protocol


_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,79}$")
_RUN_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{2,79}$")
_INSTANCE_ID = re.compile(r"^[A-Za-z0-9._-]+__[A-Za-z0-9._-]+-\d+$")
_REPOSITORY = re.compile(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$")
_COMMIT = re.compile(r"^[0-9A-Fa-f]{7,40}$")
_CONFIGURATION_IDS = ("B0", "A1", "A2", "A3")
_KINDS = frozenset(
    {
        "single_shot_base",
        "simple_agent",
        "retrieval_agent",
        "agent_plus_review",
    }
)
_AVAILABILITY = frozenset({"implemented", "planned"})
_PATCH_STATUSES = frozenset({"produced", "no_patch"})
_EVALUATION_STATUSES = frozenset({"resolved", "unresolved", "environment_error"})
_FAILURE_CATEGORIES = (
    "ENVIRONMENT",
    "LOCALIZATION",
    "COMPREHENSION",
    "EDIT_INVALID",
    "FIX_INCOMPLETE",
    "REGRESSION",
    "VERIFICATION",
    "LOOP_CONTROL",
    "REVIEW_HARM",
    "UNKNOWN",
)


class RealBenchmarkError(ValueError):
    """Raised when the real-benchmark contract is violated."""


@dataclass(frozen=True, slots=True)
class RealBenchmarkConfiguration:
    configuration_id: str
    label: str
    change: str
    kind: str
    availability: str


@dataclass(frozen=True, slots=True)
class RealBenchmarkInstance:
    instance_id: str
    repository: str
    base_commit: str


@dataclass(frozen=True, slots=True)
class RealBenchmarkManifest:
    subset_id: str
    dataset_name: str
    dataset_split: str
    dataset_revision: str
    selection_seed: int
    max_per_repository: int
    compatibility_filters: tuple[str, ...]
    fairness_controls: tuple[str, ...]
    configurations: tuple[RealBenchmarkConfiguration, ...]
    instances: tuple[RealBenchmarkInstance, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "subset_id": self.subset_id,
            "dataset": {
                "name": self.dataset_name,
                "split": self.dataset_split,
                "revision": self.dataset_revision,
            },
            "selection": {
                "seed": self.selection_seed,
                "max_per_repository": self.max_per_repository,
                "compatibility_filters": list(self.compatibility_filters),
            },
            "fairness_controls": list(self.fairness_controls),
            "configurations": [
                {
                    "id": configuration.configuration_id,
                    "label": configuration.label,
                    "change": configuration.change,
                    "kind": configuration.kind,
                    "availability": configuration.availability,
                }
                for configuration in self.configurations
            ],
            "instances": [
                {
                    "instance_id": instance.instance_id,
                    "repository": instance.repository,
                    "base_commit": instance.base_commit,
                }
                for instance in self.instances
            ],
        }


@dataclass(frozen=True, slots=True)
class RealBenchmarkIssue:
    instance_id: str
    repository: str
    base_commit: str
    problem_statement: str


@dataclass(frozen=True, slots=True)
class PatchAttempt:
    instance_id: str
    model_name_or_path: str
    patch: str
    status: str
    failure_category: str | None
    reason: str | None
    tokens_used: int = 0
    tool_calls: int = 0
    wall_seconds: float = 0.0
    termination_reason: str | None = None
    invalid_actions: int = 0
    tests_executed: int = 0

    @property
    def valid_patch(self) -> bool:
        return bool(self.patch) and self.patch.lstrip().startswith("diff --git ")

    def to_dict(self) -> dict[str, Any]:
        return {
            "instance_id": self.instance_id,
            "model_name_or_path": self.model_name_or_path,
            "patch": self.patch,
            "status": self.status,
            "failure_category": self.failure_category,
            "reason": self.reason,
            "tokens_used": self.tokens_used,
            "tool_calls": self.tool_calls,
            "wall_seconds": self.wall_seconds,
            "termination_reason": self.termination_reason,
            "invalid_actions": self.invalid_actions,
            "tests_executed": self.tests_executed,
            "valid_patch": self.valid_patch,
        }


@dataclass(frozen=True, slots=True)
class PredictionRecord:
    instance_id: str
    model_name_or_path: str
    model_patch: str

    def to_dict(self) -> dict[str, str]:
        return {
            "instance_id": self.instance_id,
            "model_name_or_path": self.model_name_or_path,
            "model_patch": self.model_patch,
        }


@dataclass(frozen=True, slots=True)
class PreparedConfigurationRun:
    configuration_id: str
    label: str
    change: str
    kind: str
    availability: str
    status: str
    reason: str | None
    predictions_path: Path | None
    attempts_path: Path | None
    attempts: tuple[PatchAttempt, ...]

    @property
    def registered(self) -> int:
        return len(self.attempts)

    @property
    def attempted(self) -> int:
        return sum(attempt.status == "produced" for attempt in self.attempts)

    @property
    def valid_patches(self) -> int:
        return sum(attempt.valid_patch for attempt in self.attempts)

    @property
    def total_tokens_used(self) -> int:
        return sum(attempt.tokens_used for attempt in self.attempts)

    @property
    def total_tool_calls(self) -> int:
        return sum(attempt.tool_calls for attempt in self.attempts)

    @property
    def total_wall_seconds(self) -> float:
        return round(sum(attempt.wall_seconds for attempt in self.attempts), 6)

    def to_dict(self) -> dict[str, Any]:
        return {
            "configuration_id": self.configuration_id,
            "label": self.label,
            "change": self.change,
            "kind": self.kind,
            "availability": self.availability,
            "status": self.status,
            "reason": self.reason,
            "predictions_path": None if self.predictions_path is None else str(self.predictions_path),
            "attempts_path": None if self.attempts_path is None else str(self.attempts_path),
            "registered": self.registered,
            "attempted": self.attempted,
            "valid_patches": self.valid_patches,
            "total_tokens_used": self.total_tokens_used,
            "total_tool_calls": self.total_tool_calls,
            "total_wall_seconds": self.total_wall_seconds,
        }


@dataclass(frozen=True, slots=True)
class PreparedRealBenchmarkRun:
    run_id: str
    subset_id: str
    run_directory: Path
    fairness_controls: tuple[str, ...]
    configurations: tuple[PreparedConfigurationRun, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "subset_id": self.subset_id,
            "run_directory": str(self.run_directory),
            "fairness_controls": list(self.fairness_controls),
            "configurations": [configuration.to_dict() for configuration in self.configurations],
        }


@dataclass(frozen=True, slots=True)
class EvaluationInstanceResult:
    instance_id: str
    resolved: bool
    status: str
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "instance_id": self.instance_id,
            "resolved": self.resolved,
            "status": self.status,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class RealBenchmarkCaseResult:
    instance_id: str
    repository: str
    patch_status: str
    valid_patch: bool
    resolved: bool
    evaluation_status: str
    primary_failure_category: str | None
    attempt_reason: str | None
    evaluation_reason: str | None
    tokens_used: int
    tool_calls: int
    wall_seconds: float
    termination_reason: str | None
    invalid_actions: int
    tests_executed: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "instance_id": self.instance_id,
            "repository": self.repository,
            "patch_status": self.patch_status,
            "valid_patch": self.valid_patch,
            "resolved": self.resolved,
            "evaluation_status": self.evaluation_status,
            "primary_failure_category": self.primary_failure_category,
            "attempt_reason": self.attempt_reason,
            "evaluation_reason": self.evaluation_reason,
            "tokens_used": self.tokens_used,
            "tool_calls": self.tool_calls,
            "wall_seconds": self.wall_seconds,
            "termination_reason": self.termination_reason,
            "invalid_actions": self.invalid_actions,
            "tests_executed": self.tests_executed,
        }


@dataclass(frozen=True, slots=True)
class RealBenchmarkConfigurationResult:
    configuration_id: str
    label: str
    change: str
    kind: str
    availability: str
    status: str
    reason: str | None
    registered: int | None
    attempted: int | None
    valid_patches: int | None
    resolved: int | None
    total_tokens_used: int | None
    total_tool_calls: int | None
    total_wall_seconds: float | None
    predictions_path: Path | None
    cases: tuple[RealBenchmarkCaseResult, ...]

    @property
    def measured(self) -> bool:
        return self.status == "measured"

    @property
    def failure_counts(self) -> tuple[tuple[str, int], ...]:
        counts = {
            category: sum(case.primary_failure_category == category for case in self.cases)
            for category in _FAILURE_CATEGORIES
        }
        return tuple((category, count) for category, count in counts.items() if count)

    def to_dict(self) -> dict[str, Any]:
        return {
            "configuration_id": self.configuration_id,
            "label": self.label,
            "change": self.change,
            "kind": self.kind,
            "availability": self.availability,
            "status": self.status,
            "reason": self.reason,
            "registered": self.registered,
            "attempted": self.attempted,
            "valid_patches": self.valid_patches,
            "resolved": self.resolved,
            "total_tokens_used": self.total_tokens_used,
            "total_tool_calls": self.total_tool_calls,
            "total_wall_seconds": self.total_wall_seconds,
            "predictions_path": None if self.predictions_path is None else str(self.predictions_path),
            "failure_counts": [
                {"category": category, "count": count}
                for category, count in self.failure_counts
            ],
            "cases": [case.to_dict() for case in self.cases],
        }


@dataclass(frozen=True, slots=True)
class RealBenchmarkComparison:
    previous_configuration_id: str
    next_configuration_id: str
    status: str
    reason: str | None
    gained: tuple[str, ...]
    lost: tuple[str, ...]
    resolved_both: tuple[str, ...]
    failed_both: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "previous_configuration_id": self.previous_configuration_id,
            "next_configuration_id": self.next_configuration_id,
            "status": self.status,
            "reason": self.reason,
            "gained": list(self.gained),
            "lost": list(self.lost),
            "resolved_both": list(self.resolved_both),
            "failed_both": list(self.failed_both),
        }


@dataclass(frozen=True, slots=True)
class RealBenchmarkRun:
    run_id: str
    subset_id: str
    run_directory: Path
    dataset_name: str
    dataset_split: str
    dataset_revision: str
    fairness_controls: tuple[str, ...]
    configurations: tuple[RealBenchmarkConfigurationResult, ...]
    adjacent_comparisons: tuple[RealBenchmarkComparison, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "subset_id": self.subset_id,
            "run_directory": str(self.run_directory),
            "dataset_name": self.dataset_name,
            "dataset_split": self.dataset_split,
            "dataset_revision": self.dataset_revision,
            "fairness_controls": list(self.fairness_controls),
            "configurations": [configuration.to_dict() for configuration in self.configurations],
            "adjacent_comparisons": [
                comparison.to_dict() for comparison in self.adjacent_comparisons
            ],
        }


class RealIssueResolver(Protocol):
    def resolve(self, instance: RealBenchmarkInstance) -> RealBenchmarkIssue:
        """Resolve one pinned manifest entry into a real issue statement."""


class PatchProducer(Protocol):
    def produce(
        self,
        configuration: RealBenchmarkConfiguration,
        issue: RealBenchmarkIssue,
    ) -> PatchAttempt:
        """Produce one patch attempt for one issue under one frozen configuration."""


class Evaluator(Protocol):
    def evaluate(
        self,
        manifest: RealBenchmarkManifest,
        configuration: RealBenchmarkConfiguration,
        predictions_path: Path,
        output_directory: Path,
    ) -> tuple[EvaluationInstanceResult, ...]:
        """Evaluate one configuration's predictions against the external harness."""


def load_real_benchmark_manifest(manifest_path: str | Path) -> RealBenchmarkManifest:
    """Load the pinned 20-instance real benchmark manifest."""

    manifest_file = Path(manifest_path)
    try:
        document = json.loads(manifest_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RealBenchmarkError(f"cannot load real benchmark manifest: {manifest_file}") from exc
    expected_fields = {
        "schema_version",
        "subset_id",
        "dataset",
        "selection",
        "fairness_controls",
        "configurations",
        "instances",
    }
    if not isinstance(document, dict) or set(document) != expected_fields:
        raise RealBenchmarkError("real benchmark manifest has unexpected top-level fields")
    if document["schema_version"] != 1:
        raise RealBenchmarkError("real benchmark manifest schema_version must equal 1")

    subset_id = _safe_id(document["subset_id"], "subset_id")
    dataset = _load_dataset(document["dataset"])
    selection = _load_selection(document["selection"])
    fairness_controls = _load_string_list(
        document["fairness_controls"],
        field_name="fairness_controls",
        minimum=4,
        maximum=16,
    )

    raw_configurations = document["configurations"]
    if not isinstance(raw_configurations, list) or len(raw_configurations) != len(_CONFIGURATION_IDS):
        raise RealBenchmarkError("real benchmark must register exactly four configurations")
    configurations = tuple(_load_configuration(raw) for raw in raw_configurations)
    observed_ids = tuple(configuration.configuration_id for configuration in configurations)
    if observed_ids != _CONFIGURATION_IDS:
        raise RealBenchmarkError(
            f"real benchmark configuration order must be {_CONFIGURATION_IDS}; observed {observed_ids}"
        )

    raw_instances = document["instances"]
    if not isinstance(raw_instances, list) or len(raw_instances) != 20:
        raise RealBenchmarkError("real benchmark must pin exactly 20 instances")
    instances = tuple(_load_instance(raw) for raw in raw_instances)
    if len({instance.instance_id for instance in instances}) != len(instances):
        raise RealBenchmarkError("real benchmark instance IDs must be unique")
    repository_counts: dict[str, int] = {}
    for instance in instances:
        repository_counts[instance.repository] = repository_counts.get(instance.repository, 0) + 1
    if any(count > selection["max_per_repository"] for count in repository_counts.values()):
        raise RealBenchmarkError("real benchmark manifest violates the per-repository cap")

    return RealBenchmarkManifest(
        subset_id=subset_id,
        dataset_name=dataset["name"],
        dataset_split=dataset["split"],
        dataset_revision=dataset["revision"],
        selection_seed=selection["seed"],
        max_per_repository=selection["max_per_repository"],
        compatibility_filters=selection["compatibility_filters"],
        fairness_controls=fairness_controls,
        configurations=configurations,
        instances=instances,
    )


def prepare_real_benchmark_run(
    manifest: RealBenchmarkManifest,
    *,
    run_id: str,
    runs_root: str | Path,
    issue_resolver: RealIssueResolver,
    patch_producer: PatchProducer,
    progress_observer: Callable[[str], None] | None = None,
) -> PreparedRealBenchmarkRun:
    """Resolve issues, generate prediction JSONL files, and persist immutable evidence."""

    safe_run_id = _safe_run_id(run_id)
    root = Path(runs_root)
    run_directory = root / "real-benchmark" / safe_run_id
    try:
        run_directory.mkdir(parents=True)
    except FileExistsError as exc:
        raise RealBenchmarkError(f"real benchmark run directory already exists: {run_directory}") from exc
    except OSError as exc:
        raise RealBenchmarkError(f"could not create real benchmark run directory: {run_directory}") from exc

    resolved_issues = tuple(_resolve_issue(instance, issue_resolver) for instance in manifest.instances)
    _write_json(run_directory / "manifest_snapshot.json", manifest.to_dict())

    try:
        configuration_runs = tuple(
            _prepare_configuration(
                manifest=manifest,
                configuration=configuration,
                issues=resolved_issues,
                patch_producer=patch_producer,
                output_directory=run_directory / configuration.configuration_id,
                progress_observer=progress_observer,
            )
            for configuration in manifest.configurations
        )
    finally:
        finish = getattr(patch_producer, "finish", None)
        if callable(finish):
            finish()

    prepared = PreparedRealBenchmarkRun(
        run_id=safe_run_id,
        subset_id=manifest.subset_id,
        run_directory=run_directory,
        fairness_controls=manifest.fairness_controls,
        configurations=configuration_runs,
    )
    _write_json(run_directory / "prepared_run.json", prepared.to_dict())
    return prepared


def run_real_benchmark(
    manifest: RealBenchmarkManifest,
    *,
    run_id: str,
    runs_root: str | Path,
    issue_resolver: RealIssueResolver,
    patch_producer: PatchProducer,
    evaluator: Evaluator,
    progress_observer: Callable[[str], None] | None = None,
) -> RealBenchmarkRun:
    """Prepare predictions and then evaluate each configuration through an external harness."""

    prepared = prepare_real_benchmark_run(
        manifest,
        run_id=run_id,
        runs_root=runs_root,
        issue_resolver=issue_resolver,
        patch_producer=patch_producer,
        progress_observer=progress_observer,
    )
    configurations = tuple(
        _evaluate_configuration(manifest, prepared_configuration, evaluator)
        for prepared_configuration in prepared.configurations
    )
    comparisons = tuple(
        _compare_configurations(previous, current)
        for previous, current in zip(configurations, configurations[1:])
    )
    result = RealBenchmarkRun(
        run_id=prepared.run_id,
        subset_id=manifest.subset_id,
        run_directory=prepared.run_directory,
        dataset_name=manifest.dataset_name,
        dataset_split=manifest.dataset_split,
        dataset_revision=manifest.dataset_revision,
        fairness_controls=manifest.fairness_controls,
        configurations=configurations,
        adjacent_comparisons=comparisons,
    )
    _write_json(prepared.run_directory / "run_summary.json", result.to_dict())
    return result


def _prepare_configuration(
    *,
    manifest: RealBenchmarkManifest,
    configuration: RealBenchmarkConfiguration,
    issues: tuple[RealBenchmarkIssue, ...],
    patch_producer: PatchProducer,
    output_directory: Path,
    progress_observer: Callable[[str], None] | None = None,
) -> PreparedConfigurationRun:
    if configuration.availability != "implemented":
        return PreparedConfigurationRun(
            configuration_id=configuration.configuration_id,
            label=configuration.label,
            change=configuration.change,
            kind=configuration.kind,
            availability=configuration.availability,
            status="unavailable",
            reason="configuration is registered but not implemented yet",
            predictions_path=None,
            attempts_path=None,
            attempts=(),
        )

    output_directory.mkdir(parents=True, exist_ok=True)
    attempts: list[PatchAttempt] = []
    predictions: list[PredictionRecord] = []
    for instance, issue in zip(manifest.instances, issues):
        try:
            produced_attempt = patch_producer.produce(configuration, issue)
        except Exception as exc:  # preserve one failed real task without losing the run
            produced_attempt = PatchAttempt(
                instance_id=instance.instance_id,
                model_name_or_path=f"localcode/{configuration.configuration_id.lower()}-producer",
                patch="",
                status="no_patch",
                failure_category="ENVIRONMENT",
                reason=f"patch producer error: {str(exc)[:440]}",
            )
        attempt = _validate_attempt(produced_attempt, instance=instance)
        attempts.append(attempt)
        if progress_observer is not None:
            progress_observer(
                f"{configuration.configuration_id} {instance.instance_id} "
                f"status={attempt.status} "
                f"wall={round(attempt.wall_seconds, 1)}s "
                f"reason={attempt.reason if attempt.reason else 'ok'}"
            )
        predictions.append(
            PredictionRecord(
                instance_id=instance.instance_id,
                model_name_or_path=attempt.model_name_or_path,
                model_patch=attempt.patch if attempt.status == "produced" else "",
            )
        )

    predictions_path = output_directory / "predictions.jsonl"
    attempts_path = output_directory / "attempts.jsonl"
    _write_jsonl(predictions_path, tuple(record.to_dict() for record in predictions))
    _write_jsonl(attempts_path, tuple(attempt.to_dict() for attempt in attempts))

    configuration_run = PreparedConfigurationRun(
        configuration_id=configuration.configuration_id,
        label=configuration.label,
        change=configuration.change,
        kind=configuration.kind,
        availability=configuration.availability,
        status="prepared",
        reason=None,
        predictions_path=predictions_path,
        attempts_path=attempts_path,
        attempts=tuple(attempts),
    )
    _write_json(output_directory / "prepared_summary.json", configuration_run.to_dict())
    return configuration_run


def _evaluate_configuration(
    manifest: RealBenchmarkManifest,
    prepared: PreparedConfigurationRun,
    evaluator: Evaluator,
) -> RealBenchmarkConfigurationResult:
    if prepared.status != "prepared" or prepared.predictions_path is None:
        return RealBenchmarkConfigurationResult(
            configuration_id=prepared.configuration_id,
            label=prepared.label,
            change=prepared.change,
            kind=prepared.kind,
            availability=prepared.availability,
            status="unavailable",
            reason=prepared.reason,
            registered=None,
            attempted=None,
            valid_patches=None,
            resolved=None,
            total_tokens_used=None,
            total_tool_calls=None,
            total_wall_seconds=None,
            predictions_path=prepared.predictions_path,
            cases=(),
        )

    configuration = RealBenchmarkConfiguration(
        configuration_id=prepared.configuration_id,
        label=prepared.label,
        change=prepared.change,
        kind=prepared.kind,
        availability=prepared.availability,
    )
    try:
        evaluation = tuple(
            _validate_evaluation_result(result)
            for result in evaluator.evaluate(
                manifest,
                configuration,
                prepared.predictions_path,
                prepared.predictions_path.parent,
            )
        )
    except RealBenchmarkError as exc:
        # An unavailable external harness (e.g. Docker not running) must not
        # destroy a completed producer run. Preserve every attempt and mark
        # each case as an environment error so the evidence survives.
        return _environment_error_configuration(manifest, prepared, str(exc))
    by_id = {result.instance_id: result for result in evaluation}
    expected_ids = tuple(instance.instance_id for instance in manifest.instances)
    if tuple(sorted(by_id)) != tuple(sorted(expected_ids)):
        raise RealBenchmarkError(
            f"evaluator results for {prepared.configuration_id} do not match the pinned subset"
        )
    cases = tuple(
        _case_result(instance, attempt, by_id[instance.instance_id])
        for instance, attempt in zip(manifest.instances, prepared.attempts)
    )
    result = RealBenchmarkConfigurationResult(
        configuration_id=prepared.configuration_id,
        label=prepared.label,
        change=prepared.change,
        kind=prepared.kind,
        availability=prepared.availability,
        status="measured",
        reason=None,
        registered=prepared.registered,
        attempted=prepared.attempted,
        valid_patches=prepared.valid_patches,
        resolved=sum(case.resolved for case in cases),
        total_tokens_used=prepared.total_tokens_used,
        total_tool_calls=prepared.total_tool_calls,
        total_wall_seconds=prepared.total_wall_seconds,
        predictions_path=prepared.predictions_path,
        cases=cases,
    )
    _write_json(prepared.predictions_path.parent / "measured_summary.json", result.to_dict())
    return result


def _environment_error_configuration(
    manifest: RealBenchmarkManifest,
    prepared: PreparedConfigurationRun,
    evaluator_error: str,
) -> RealBenchmarkConfigurationResult:
    """Record a whole configuration as environment errors when the evaluator is unavailable."""

    detail = evaluator_error.strip()[:400]
    cases = tuple(
        _case_result(
            instance,
            attempt,
            EvaluationInstanceResult(
                instance_id=instance.instance_id,
                resolved=False,
                status="environment_error",
                reason=f"evaluator unavailable: {detail}",
            ),
        )
        for instance, attempt in zip(manifest.instances, prepared.attempts)
    )
    return RealBenchmarkConfigurationResult(
        configuration_id=prepared.configuration_id,
        label=prepared.label,
        change=prepared.change,
        kind=prepared.kind,
        availability=prepared.availability,
        status="measured",
        reason=f"evaluation failed; recorded as environment errors: {detail}",
        registered=prepared.registered,
        attempted=prepared.attempted,
        valid_patches=prepared.valid_patches,
        resolved=0,
        total_tokens_used=prepared.total_tokens_used,
        total_tool_calls=prepared.total_tool_calls,
        total_wall_seconds=prepared.total_wall_seconds,
        predictions_path=prepared.predictions_path,
        cases=cases,
    )


def _case_result(
    instance: RealBenchmarkInstance,
    attempt: PatchAttempt,
    evaluation: EvaluationInstanceResult,
) -> RealBenchmarkCaseResult:
    primary_failure = _primary_failure_category(attempt, evaluation)
    return RealBenchmarkCaseResult(
        instance_id=instance.instance_id,
        repository=instance.repository,
        patch_status=attempt.status,
        valid_patch=attempt.valid_patch,
        resolved=evaluation.resolved,
        evaluation_status=evaluation.status,
        primary_failure_category=primary_failure,
        attempt_reason=attempt.reason,
        evaluation_reason=evaluation.reason,
        tokens_used=attempt.tokens_used,
        tool_calls=attempt.tool_calls,
        wall_seconds=attempt.wall_seconds,
        termination_reason=attempt.termination_reason,
        invalid_actions=attempt.invalid_actions,
        tests_executed=attempt.tests_executed,
    )


def _compare_configurations(
    previous: RealBenchmarkConfigurationResult,
    current: RealBenchmarkConfigurationResult,
) -> RealBenchmarkComparison:
    if not previous.measured or not current.measured:
        return RealBenchmarkComparison(
            previous_configuration_id=previous.configuration_id,
            next_configuration_id=current.configuration_id,
            status="unavailable",
            reason="one or both configurations are not measured",
            gained=(),
            lost=(),
            resolved_both=(),
            failed_both=(),
        )
    previous_cases = {case.instance_id: case.resolved for case in previous.cases}
    current_cases = {case.instance_id: case.resolved for case in current.cases}
    if tuple(sorted(previous_cases)) != tuple(sorted(current_cases)):
        return RealBenchmarkComparison(
            previous_configuration_id=previous.configuration_id,
            next_configuration_id=current.configuration_id,
            status="unavailable",
            reason="configuration case sets do not match",
            gained=(),
            lost=(),
            resolved_both=(),
            failed_both=(),
        )
    gained: list[str] = []
    lost: list[str] = []
    resolved_both: list[str] = []
    failed_both: list[str] = []
    for instance_id in sorted(previous_cases):
        before = previous_cases[instance_id]
        after = current_cases[instance_id]
        if not before and after:
            gained.append(instance_id)
        elif before and not after:
            lost.append(instance_id)
        elif before and after:
            resolved_both.append(instance_id)
        else:
            failed_both.append(instance_id)
    return RealBenchmarkComparison(
        previous_configuration_id=previous.configuration_id,
        next_configuration_id=current.configuration_id,
        status="measured",
        reason=None,
        gained=tuple(gained),
        lost=tuple(lost),
        resolved_both=tuple(resolved_both),
        failed_both=tuple(failed_both),
    )


def _resolve_issue(
    instance: RealBenchmarkInstance,
    issue_resolver: RealIssueResolver,
) -> RealBenchmarkIssue:
    issue = issue_resolver.resolve(instance)
    if not isinstance(issue, RealBenchmarkIssue):
        raise RealBenchmarkError("issue resolver must return RealBenchmarkIssue values")
    if issue.instance_id != instance.instance_id:
        raise RealBenchmarkError("resolved issue instance ID does not match the manifest")
    if issue.repository != instance.repository:
        raise RealBenchmarkError("resolved issue repository does not match the manifest")
    if issue.base_commit.lower() != instance.base_commit.lower():
        raise RealBenchmarkError("resolved issue base commit does not match the manifest")
    if (
        not isinstance(issue.problem_statement, str)
        or not issue.problem_statement.strip()
        or len(issue.problem_statement) > 200_000
    ):
        raise RealBenchmarkError("resolved issue problem statement is invalid")
    return issue


def _validate_attempt(
    attempt: PatchAttempt,
    *,
    instance: RealBenchmarkInstance,
) -> PatchAttempt:
    if not isinstance(attempt, PatchAttempt):
        raise RealBenchmarkError("patch producer must return PatchAttempt values")
    if attempt.instance_id != instance.instance_id:
        raise RealBenchmarkError("patch attempt instance ID does not match the pinned subset")
    if (
        not isinstance(attempt.model_name_or_path, str)
        or not attempt.model_name_or_path
        or len(attempt.model_name_or_path) > 200
    ):
        raise RealBenchmarkError("patch attempt model_name_or_path is invalid")
    if attempt.status not in _PATCH_STATUSES:
        raise RealBenchmarkError(f"patch attempt status is invalid: {attempt.status!r}")
    if not isinstance(attempt.patch, str) or len(attempt.patch) > 2_000_000:
        raise RealBenchmarkError("patch attempt patch payload is invalid")
    if attempt.status == "no_patch" and attempt.patch:
        raise RealBenchmarkError("no_patch attempts must not carry a patch payload")
    if attempt.failure_category is not None and attempt.failure_category not in _FAILURE_CATEGORIES:
        raise RealBenchmarkError("patch attempt failure category is invalid")
    if attempt.reason is not None and (
        not isinstance(attempt.reason, str) or not attempt.reason or len(attempt.reason) > 500
    ):
        raise RealBenchmarkError("patch attempt reason is invalid")
    if (
        isinstance(attempt.tokens_used, bool)
        or not isinstance(attempt.tokens_used, int)
        or attempt.tokens_used < 0
    ):
        raise RealBenchmarkError("patch attempt tokens_used is invalid")
    if (
        isinstance(attempt.tool_calls, bool)
        or not isinstance(attempt.tool_calls, int)
        or attempt.tool_calls < 0
    ):
        raise RealBenchmarkError("patch attempt tool_calls is invalid")
    if (
        isinstance(attempt.wall_seconds, bool)
        or not isinstance(attempt.wall_seconds, (int, float))
        or not isfinite(float(attempt.wall_seconds))
        or float(attempt.wall_seconds) < 0
    ):
        raise RealBenchmarkError("patch attempt wall_seconds is invalid")
    if attempt.termination_reason is not None and (
        not isinstance(attempt.termination_reason, str)
        or not attempt.termination_reason
        or len(attempt.termination_reason) > 100
    ):
        raise RealBenchmarkError("patch attempt termination_reason is invalid")
    for name, value in (
        ("invalid_actions", attempt.invalid_actions),
        ("tests_executed", attempt.tests_executed),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise RealBenchmarkError(f"patch attempt {name} is invalid")
    return PatchAttempt(
        instance_id=attempt.instance_id,
        model_name_or_path=attempt.model_name_or_path,
        patch=attempt.patch,
        status=attempt.status,
        failure_category=attempt.failure_category,
        reason=attempt.reason,
        tokens_used=attempt.tokens_used,
        tool_calls=attempt.tool_calls,
        wall_seconds=round(float(attempt.wall_seconds), 6),
        termination_reason=attempt.termination_reason,
        invalid_actions=attempt.invalid_actions,
        tests_executed=attempt.tests_executed,
    )


def _validate_evaluation_result(result: EvaluationInstanceResult) -> EvaluationInstanceResult:
    if not isinstance(result, EvaluationInstanceResult):
        raise RealBenchmarkError("evaluator must return EvaluationInstanceResult values")
    if _INSTANCE_ID.fullmatch(result.instance_id) is None:
        raise RealBenchmarkError("evaluation instance ID is invalid")
    if result.status not in _EVALUATION_STATUSES:
        raise RealBenchmarkError(f"evaluation status is invalid: {result.status!r}")
    if result.status == "resolved" and not result.resolved:
        raise RealBenchmarkError("resolved evaluation status must set resolved=True")
    if result.status != "resolved" and result.resolved:
        raise RealBenchmarkError("only resolved evaluation status may set resolved=True")
    if result.reason is not None and (
        not isinstance(result.reason, str) or not result.reason or len(result.reason) > 500
    ):
        raise RealBenchmarkError("evaluation reason is invalid")
    return result


def _primary_failure_category(
    attempt: PatchAttempt,
    evaluation: EvaluationInstanceResult,
) -> str | None:
    if evaluation.resolved:
        return None
    if evaluation.status == "environment_error":
        return "ENVIRONMENT"
    if attempt.failure_category is not None:
        return attempt.failure_category
    if attempt.status == "no_patch":
        return "UNKNOWN"
    return "FIX_INCOMPLETE" if attempt.valid_patch else "EDIT_INVALID"


def _safe_id(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or _SAFE_ID.fullmatch(value) is None:
        raise RealBenchmarkError(f"{field_name} is invalid")
    return value


def _safe_run_id(value: Any) -> str:
    if not isinstance(value, str) or _RUN_ID.fullmatch(value) is None:
        raise RealBenchmarkError("run_id is invalid")
    return value


def _load_dataset(raw: Any) -> dict[str, str]:
    expected_fields = {"name", "split", "revision"}
    if not isinstance(raw, dict) or set(raw) != expected_fields:
        raise RealBenchmarkError("dataset fields are invalid")
    return {
        field: _bounded_text(raw[field], field, maximum=200)
        for field in ("name", "split", "revision")
    }


def _load_selection(raw: Any) -> dict[str, Any]:
    expected_fields = {"seed", "max_per_repository", "compatibility_filters"}
    if not isinstance(raw, dict) or set(raw) != expected_fields:
        raise RealBenchmarkError("selection fields are invalid")
    seed = _non_negative_integer(raw["seed"], "selection seed")
    max_per_repository = _non_negative_integer(raw["max_per_repository"], "max_per_repository")
    if not 1 <= max_per_repository <= 5:
        raise RealBenchmarkError("max_per_repository must stay between 1 and 5")
    filters = _load_string_list(
        raw["compatibility_filters"],
        field_name="compatibility_filters",
        minimum=1,
        maximum=10,
    )
    return {
        "seed": seed,
        "max_per_repository": max_per_repository,
        "compatibility_filters": filters,
    }


def _load_configuration(raw: Any) -> RealBenchmarkConfiguration:
    expected_fields = {"id", "label", "change", "kind", "availability"}
    if not isinstance(raw, dict) or set(raw) != expected_fields:
        raise RealBenchmarkError("real benchmark configuration fields are invalid")
    configuration_id = raw["id"]
    label = raw["label"]
    change = raw["change"]
    kind = raw["kind"]
    availability = raw["availability"]
    if not isinstance(configuration_id, str) or configuration_id not in _CONFIGURATION_IDS:
        raise RealBenchmarkError("real benchmark configuration ID is invalid")
    for field_name, value in (("label", label), ("change", change)):
        if not isinstance(value, str) or not value or len(value) > 200:
            raise RealBenchmarkError(f"real benchmark configuration {field_name} is invalid")
    if kind not in _KINDS:
        raise RealBenchmarkError(f"real benchmark configuration kind is invalid: {kind!r}")
    if availability not in _AVAILABILITY:
        raise RealBenchmarkError(
            f"real benchmark configuration availability is invalid: {availability!r}"
        )
    return RealBenchmarkConfiguration(
        configuration_id=configuration_id,
        label=label,
        change=change,
        kind=kind,
        availability=availability,
    )


def _load_instance(raw: Any) -> RealBenchmarkInstance:
    expected_fields = {"instance_id", "repository", "base_commit"}
    if not isinstance(raw, dict) or set(raw) != expected_fields:
        raise RealBenchmarkError("real benchmark instance fields are invalid")
    instance_id = raw["instance_id"]
    repository = raw["repository"]
    base_commit = raw["base_commit"]
    if not isinstance(instance_id, str) or _INSTANCE_ID.fullmatch(instance_id) is None:
        raise RealBenchmarkError("real benchmark instance_id is invalid")
    if not isinstance(repository, str) or _REPOSITORY.fullmatch(repository) is None:
        raise RealBenchmarkError("real benchmark repository is invalid")
    if not isinstance(base_commit, str) or _COMMIT.fullmatch(base_commit) is None:
        raise RealBenchmarkError("real benchmark base_commit is invalid")
    return RealBenchmarkInstance(
        instance_id=instance_id,
        repository=repository,
        base_commit=base_commit.lower(),
    )


def _load_string_list(
    raw: Any,
    *,
    field_name: str,
    minimum: int,
    maximum: int,
) -> tuple[str, ...]:
    if not isinstance(raw, list) or not minimum <= len(raw) <= maximum:
        raise RealBenchmarkError(f"{field_name} must be a bounded non-empty string list")
    values = []
    for value in raw:
        if not isinstance(value, str) or not value or len(value) > 200:
            raise RealBenchmarkError(f"{field_name} contains an invalid value")
        values.append(value)
    return tuple(values)


def _bounded_text(value: Any, field_name: str, *, maximum: int) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise RealBenchmarkError(f"{field_name} is invalid")
    return value


def _non_negative_integer(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise RealBenchmarkError(f"{field_name} must be a non-negative integer")
    return value


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: tuple[dict[str, Any], ...]) -> None:
    path.write_text(
        "".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
    )
