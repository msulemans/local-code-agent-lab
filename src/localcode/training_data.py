"""Versioned, leakage-safe contracts for LocalCode repair training data."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from enum import Enum
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any, Iterable


_SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{2,127}$")
_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_REVISION = re.compile(r"^[0-9a-f]{7,64}$")
_DIFF_HEADER = re.compile(r"^diff --git a/([^\s]+) b/([^\s]+)$")
_POLICY_FIELDS = {
    "schema_version",
    "dataset_id",
    "split_seed",
    "split_buckets",
    "task_types",
    "evaluation_manifests",
    "max_input_chars",
    "max_target_chars",
    "max_changed_paths",
}
_EXAMPLE_FIELDS = {
    "schema_version",
    "example_id",
    "task_type",
    "lineage_id",
    "split",
    "source_id",
    "source_repository",
    "source_revision",
    "source_license",
    "license_reviewed",
    "instruction",
    "input_text",
    "target_text",
    "changed_paths",
    "test_command",
    "test_exit_code",
}


class TrainingDataError(ValueError):
    """A typed training-data contract or leakage violation."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class TrainingTask(str, Enum):
    ISSUE_TO_DIFF = "issue_to_diff"
    BROKEN_TO_CORRECTED = "broken_to_corrected"
    TEST_FAILURE_TO_PATCH = "test_failure_to_patch"
    FUNCTION_TO_IMPLEMENTATION = "function_to_implementation"


class TrainingSplit(str, Enum):
    TRAIN = "train"
    VALIDATION = "validation"
    SEALED_TEST = "sealed_test"


@dataclass(frozen=True, slots=True)
class TrainingDataPolicy:
    schema_version: int
    dataset_id: str
    split_seed: int
    split_buckets: tuple[tuple[TrainingSplit, int], ...]
    task_types: tuple[TrainingTask, ...]
    evaluation_manifests: tuple[str, ...]
    max_input_chars: int
    max_target_chars: int
    max_changed_paths: int

    @classmethod
    def from_path(cls, path: str | Path) -> "TrainingDataPolicy":
        source = Path(path)
        try:
            document = _load_json(source.read_text(encoding="utf-8"))
        except OSError as exc:
            raise TrainingDataError("manifest_read", f"could not read {source}") from exc
        return cls.from_dict(document)

    @classmethod
    def from_dict(cls, document: object) -> "TrainingDataPolicy":
        if not isinstance(document, dict) or set(document) != _POLICY_FIELDS:
            raise TrainingDataError("manifest_shape", "training manifest fields must match schema v1")
        if document["schema_version"] != 1:
            raise TrainingDataError("schema_version", "training manifest schema_version must be 1")
        dataset_id = _safe_id(document["dataset_id"], "dataset_id")
        split_seed = _bounded_int(document["split_seed"], "split_seed", 0, 2**63 - 1)

        buckets = document["split_buckets"]
        expected_splits = {split.value for split in TrainingSplit}
        if not isinstance(buckets, dict) or set(buckets) != expected_splits:
            raise TrainingDataError("split_buckets", "split_buckets must define train, validation, and sealed_test")
        parsed_buckets = tuple(
            (split, _bounded_int(buckets[split.value], split.value, 1, 9_998))
            for split in TrainingSplit
        )
        if sum(size for _, size in parsed_buckets) != 10_000:
            raise TrainingDataError("split_buckets", "split bucket counts must total 10000")

        raw_tasks = document["task_types"]
        if not isinstance(raw_tasks, list) or len(raw_tasks) != len(TrainingTask):
            raise TrainingDataError("task_types", "manifest must register every training task exactly once")
        try:
            tasks = tuple(TrainingTask(value) for value in raw_tasks)
        except (TypeError, ValueError) as exc:
            raise TrainingDataError("task_types", "manifest contains an unknown training task") from exc
        if len(set(tasks)) != len(tasks) or set(tasks) != set(TrainingTask):
            raise TrainingDataError("task_types", "manifest must register every training task exactly once")

        raw_manifests = document["evaluation_manifests"]
        if not isinstance(raw_manifests, list) or not raw_manifests:
            raise TrainingDataError("evaluation_manifests", "at least one evaluation manifest is required")
        evaluation_manifests = tuple(
            _relative_path(value, "evaluation manifest") for value in raw_manifests
        )
        return cls(
            schema_version=1,
            dataset_id=dataset_id,
            split_seed=split_seed,
            split_buckets=parsed_buckets,
            task_types=tasks,
            evaluation_manifests=evaluation_manifests,
            max_input_chars=_bounded_int(document["max_input_chars"], "max_input_chars", 1, 1_000_000),
            max_target_chars=_bounded_int(document["max_target_chars"], "max_target_chars", 1, 1_000_000),
            max_changed_paths=_bounded_int(document["max_changed_paths"], "max_changed_paths", 1, 100),
        )

    def bucket_map(self) -> dict[TrainingSplit, int]:
        return dict(self.split_buckets)


@dataclass(frozen=True, slots=True)
class TrainingExample:
    schema_version: int
    example_id: str
    task_type: TrainingTask
    lineage_id: str
    split: TrainingSplit
    source_id: str
    source_repository: str
    source_revision: str
    source_license: str
    license_reviewed: bool
    instruction: str
    input_text: str
    target_text: str
    changed_paths: tuple[str, ...]
    test_command: str | None
    test_exit_code: int | None

    @classmethod
    def from_json(cls, text: str) -> "TrainingExample":
        return cls.from_dict(_load_json(text))

    @classmethod
    def from_dict(cls, document: object) -> "TrainingExample":
        if not isinstance(document, dict) or set(document) != _EXAMPLE_FIELDS:
            raise TrainingDataError("example_shape", "training example fields must match schema v1")
        if document["schema_version"] != 1:
            raise TrainingDataError("schema_version", "training example schema_version must be 1")
        try:
            task_type = TrainingTask(document["task_type"])
            split = TrainingSplit(document["split"])
        except (TypeError, ValueError) as exc:
            raise TrainingDataError("example_enum", "training example has an unknown task or split") from exc
        repository = document["source_repository"]
        if not isinstance(repository, str) or _REPOSITORY.fullmatch(repository) is None:
            raise TrainingDataError("source_repository", "source_repository must be owner/repository")
        revision = document["source_revision"]
        if not isinstance(revision, str) or _REVISION.fullmatch(revision) is None:
            raise TrainingDataError("source_revision", "source_revision must be a 7-64 character lowercase hex revision")
        license_reviewed = document["license_reviewed"]
        if not isinstance(license_reviewed, bool):
            raise TrainingDataError("license_reviewed", "license_reviewed must be boolean")
        paths = document["changed_paths"]
        if not isinstance(paths, list) or not paths:
            raise TrainingDataError("changed_paths", "changed_paths must be a non-empty list")
        changed_paths = tuple(_relative_path(value, "changed path") for value in paths)
        if len(set(changed_paths)) != len(changed_paths) or tuple(sorted(changed_paths)) != changed_paths:
            raise TrainingDataError("changed_paths", "changed_paths must be unique and sorted")

        test_command = document["test_command"]
        test_exit_code = document["test_exit_code"]
        if (test_command is None) != (test_exit_code is None):
            raise TrainingDataError("test_evidence", "test_command and test_exit_code must appear together")
        if test_command is not None and (not isinstance(test_command, str) or not test_command.strip()):
            raise TrainingDataError("test_evidence", "test_command must be non-empty text")
        if test_exit_code is not None and (isinstance(test_exit_code, bool) or not isinstance(test_exit_code, int)):
            raise TrainingDataError("test_evidence", "test_exit_code must be an integer")
        if task_type is TrainingTask.TEST_FAILURE_TO_PATCH and (
            test_exit_code is None or test_exit_code == 0
        ):
            raise TrainingDataError("test_evidence", "test_failure_to_patch requires a failing test exit code")

        return cls(
            schema_version=1,
            example_id=_safe_id(document["example_id"], "example_id"),
            task_type=task_type,
            lineage_id=_safe_id(document["lineage_id"], "lineage_id"),
            split=split,
            source_id=_safe_id(document["source_id"], "source_id"),
            source_repository=repository,
            source_revision=revision,
            source_license=_text(document["source_license"], "source_license", 1, 200),
            license_reviewed=license_reviewed,
            instruction=_text(document["instruction"], "instruction", 1, 4_000),
            input_text=_text(document["input_text"], "input_text", 1, 1_000_000),
            target_text=_text(document["target_text"], "target_text", 1, 1_000_000),
            changed_paths=changed_paths,
            test_command=test_command,
            test_exit_code=test_exit_code,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "example_id": self.example_id,
            "task_type": self.task_type.value,
            "lineage_id": self.lineage_id,
            "split": self.split.value,
            "source_id": self.source_id,
            "source_repository": self.source_repository,
            "source_revision": self.source_revision,
            "source_license": self.source_license,
            "license_reviewed": self.license_reviewed,
            "instruction": self.instruction,
            "input_text": self.input_text,
            "target_text": self.target_text,
            "changed_paths": list(self.changed_paths),
            "test_command": self.test_command,
            "test_exit_code": self.test_exit_code,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    def content_sha256(self) -> str:
        return hashlib.sha256(self.to_json().encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class TrainingCorpusSummary:
    dataset_id: str
    examples: int
    split_counts: tuple[tuple[str, int], ...]
    task_counts: tuple[tuple[str, int], ...]
    corpus_sha256: str
    evaluation_ids_denied: int
    evaluation_revisions_denied: int

    def to_dict(self) -> dict[str, object]:
        return {
            "dataset_id": self.dataset_id,
            "examples": self.examples,
            "split_counts": dict(self.split_counts),
            "task_counts": dict(self.task_counts),
            "corpus_sha256": self.corpus_sha256,
            "evaluation_ids_denied": self.evaluation_ids_denied,
            "evaluation_revisions_denied": self.evaluation_revisions_denied,
        }


def assigned_split(lineage_id: str, policy: TrainingDataPolicy) -> TrainingSplit:
    """Assign every related example to one deterministic 10,000-bucket split."""

    lineage = _safe_id(lineage_id, "lineage_id")
    digest = hashlib.sha256(f"{policy.split_seed}\0{lineage}".encode("utf-8")).digest()
    bucket = int.from_bytes(digest[:8], "big") % 10_000
    boundary = 0
    for split, size in policy.split_buckets:
        boundary += size
        if bucket < boundary:
            return split
    raise AssertionError("validated split buckets did not cover the hash range")


def load_training_jsonl(path: str | Path) -> tuple[TrainingExample, ...]:
    source = Path(path)
    try:
        lines = source.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise TrainingDataError("corpus_read", f"could not read {source}") from exc
    examples = []
    for number, line in enumerate(lines, 1):
        if not line.strip():
            raise TrainingDataError("blank_record", f"blank JSONL record at line {number}")
        try:
            examples.append(TrainingExample.from_json(line))
        except TrainingDataError as exc:
            raise TrainingDataError(exc.code, f"line {number}: {exc}") from exc
    return tuple(examples)


def evaluation_denylist_counts(
    policy: TrainingDataPolicy,
    *,
    project_root: str | Path,
) -> tuple[int, int]:
    """Verify registered evaluation manifests and return denied ID/revision counts."""

    denied_ids, denied_revisions = _evaluation_denylist(policy, Path(project_root))
    return len(denied_ids), len(denied_revisions)


def validate_training_corpus(
    examples: Iterable[TrainingExample],
    policy: TrainingDataPolicy,
    *,
    project_root: str | Path,
) -> TrainingCorpusSummary:
    """Validate provenance, deterministic splits, exact overlap, and eval leakage."""

    records = tuple(examples)
    if not records:
        raise TrainingDataError("empty_corpus", "training corpus must contain at least one example")
    denied_ids, denied_revisions = _evaluation_denylist(policy, Path(project_root))
    seen_ids: set[str] = set()
    lineage_splits: dict[str, TrainingSplit] = {}
    content_splits: dict[tuple[str, str], TrainingSplit] = {}
    split_counts: Counter[str] = Counter()
    task_counts: Counter[str] = Counter()

    for example in records:
        if example.example_id in seen_ids:
            raise TrainingDataError("duplicate_example", f"duplicate example_id: {example.example_id}")
        seen_ids.add(example.example_id)
        if example.task_type not in policy.task_types:
            raise TrainingDataError("task_policy", f"task is not registered: {example.task_type.value}")
        if not example.license_reviewed:
            raise TrainingDataError("license_unreviewed", f"license is not reviewed: {example.example_id}")
        if len(example.input_text) > policy.max_input_chars:
            raise TrainingDataError("input_too_large", f"input exceeds policy: {example.example_id}")
        if len(example.target_text) > policy.max_target_chars:
            raise TrainingDataError("target_too_large", f"target exceeds policy: {example.example_id}")
        if len(example.changed_paths) > policy.max_changed_paths:
            raise TrainingDataError("path_limit", f"changed paths exceed policy: {example.example_id}")
        expected_split = assigned_split(example.lineage_id, policy)
        if example.split is not expected_split:
            raise TrainingDataError(
                "split_mismatch",
                f"{example.example_id} must be in {expected_split.value}, not {example.split.value}",
            )
        earlier = lineage_splits.setdefault(example.lineage_id, example.split)
        if earlier is not example.split:
            raise TrainingDataError("lineage_overlap", f"lineage crosses splits: {example.lineage_id}")
        if example.source_id in denied_ids or example.lineage_id in denied_ids:
            raise TrainingDataError("evaluation_leakage", f"evaluation ID appears in corpus: {example.example_id}")
        if example.source_revision in denied_revisions:
            raise TrainingDataError("evaluation_leakage", f"evaluation revision appears in corpus: {example.example_id}")

        for kind, value in (("input", example.input_text), ("target", example.target_text)):
            digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
            key = (kind, digest)
            previous = content_splits.setdefault(key, example.split)
            if previous is not example.split:
                raise TrainingDataError("content_overlap", f"exact {kind} content crosses splits")

        if example.task_type in {TrainingTask.ISSUE_TO_DIFF, TrainingTask.TEST_FAILURE_TO_PATCH}:
            diff_paths = _diff_paths(example.target_text)
            if diff_paths != example.changed_paths:
                raise TrainingDataError("diff_paths", f"diff paths do not match changed_paths: {example.example_id}")
        split_counts[example.split.value] += 1
        task_counts[example.task_type.value] += 1

    canonical = "".join(record.to_json() + "\n" for record in sorted(records, key=lambda item: item.example_id))
    return TrainingCorpusSummary(
        dataset_id=policy.dataset_id,
        examples=len(records),
        split_counts=tuple(sorted(split_counts.items())),
        task_counts=tuple(sorted(task_counts.items())),
        corpus_sha256=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        evaluation_ids_denied=len(denied_ids),
        evaluation_revisions_denied=len(denied_revisions),
    )


def _evaluation_denylist(policy: TrainingDataPolicy, project_root: Path) -> tuple[set[str], set[str]]:
    ids: set[str] = set()
    revisions: set[str] = set()
    for relative in policy.evaluation_manifests:
        path = project_root / relative
        try:
            document = _load_json(path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise TrainingDataError("evaluation_manifest", f"could not read {path}") from exc
        instances = document.get("instances") if isinstance(document, dict) else None
        if not isinstance(instances, list):
            raise TrainingDataError("evaluation_manifest", f"missing instances list: {path}")
        for instance in instances:
            if not isinstance(instance, dict):
                raise TrainingDataError("evaluation_manifest", f"invalid instance in {path}")
            instance_id = instance.get("instance_id")
            revision = instance.get("base_commit")
            if not isinstance(instance_id, str) or not isinstance(revision, str):
                raise TrainingDataError("evaluation_manifest", f"invalid instance fields in {path}")
            ids.add(instance_id)
            revisions.add(revision)
    return ids, revisions


def _diff_paths(patch: str) -> tuple[str, ...]:
    paths: list[str] = []
    for line in patch.splitlines():
        if not line.startswith("diff --git "):
            continue
        match = _DIFF_HEADER.fullmatch(line)
        if match is None or match.group(1) != match.group(2):
            raise TrainingDataError("invalid_diff", "target diff must modify the same repository-relative path")
        paths.append(_relative_path(match.group(1), "diff path"))
    if not paths or len(set(paths)) != len(paths):
        raise TrainingDataError("invalid_diff", "target diff must contain unique file sections")
    return tuple(sorted(paths))


def _load_json(text: str) -> Any:
    def pairs(values: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in values:
            if key in result:
                raise TrainingDataError("duplicate_field", f"duplicate JSON field: {key}")
            result[key] = value
        return result

    try:
        return json.loads(text, object_pairs_hook=pairs)
    except json.JSONDecodeError as exc:
        raise TrainingDataError("invalid_json", "invalid JSON") from exc


def _safe_id(value: object, field: str) -> str:
    if not isinstance(value, str) or _SAFE_ID.fullmatch(value) is None:
        raise TrainingDataError(field, f"{field} must be 3-128 lowercase safe characters")
    return value


def _relative_path(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise TrainingDataError("unsafe_path", f"{field} must be a non-empty POSIX relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise TrainingDataError("unsafe_path", f"{field} must stay relative without dot segments")
    return path.as_posix()


def _text(value: object, field: str, minimum: int, maximum: int) -> str:
    if not isinstance(value, str) or not minimum <= len(value) <= maximum or "\x00" in value:
        raise TrainingDataError(field, f"{field} must contain {minimum}-{maximum} characters without NUL")
    return value


def _bounded_int(value: object, field: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise TrainingDataError(field, f"{field} must be an integer from {minimum} to {maximum}")
    return value
