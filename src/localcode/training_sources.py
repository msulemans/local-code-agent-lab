"""Pinned source acquisition and normalization for repair training data."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

from .training_data import (
    TrainingDataError,
    TrainingDataPolicy,
    TrainingExample,
    TrainingTask,
    assigned_split,
    validate_training_corpus,
)


_SOURCE_DOCUMENT_FIELDS = {"schema_version", "sources"}
_SOURCE_FIELDS = {
    "source_id",
    "provider",
    "dataset",
    "dataset_revision",
    "dataset_license",
    "artifact_path",
    "artifact_url",
    "artifact_bytes",
    "artifact_sha256",
    "language",
    "reviewed_sample_licenses",
    "maximum_examples",
}
_RAW_FIELDS = {
    "commit",
    "old_file",
    "new_file",
    "old_contents",
    "new_contents",
    "subject",
    "message",
    "lang",
    "license",
    "repos",
}


@dataclass(frozen=True, slots=True)
class RepairSource:
    source_id: str
    provider: str
    dataset: str
    dataset_revision: str
    dataset_license: str
    artifact_path: str
    artifact_url: str
    artifact_bytes: int
    artifact_sha256: str
    language: str
    reviewed_sample_licenses: tuple[str, ...]
    maximum_examples: int

    @classmethod
    def from_dict(cls, document: object) -> "RepairSource":
        if not isinstance(document, dict) or set(document) != _SOURCE_FIELDS:
            raise TrainingDataError("source_shape", "source fields must match schema v1")
        source_id = _safe_token(document["source_id"], "source_id")
        provider = _safe_token(document["provider"], "provider")
        dataset = document["dataset"]
        if not isinstance(dataset, str) or dataset.count("/") != 1:
            raise TrainingDataError("source_dataset", "dataset must be owner/name")
        revision = _hex(document["dataset_revision"], "dataset_revision", exact=40)
        artifact_path = _relative_path(document["artifact_path"], "artifact_path")
        artifact_url = document["artifact_url"]
        if not isinstance(artifact_url, str):
            raise TrainingDataError("artifact_url", "artifact_url must be HTTPS text")
        parsed = urlparse(artifact_url)
        if parsed.scheme != "https" or parsed.hostname != "huggingface.co":
            raise TrainingDataError("artifact_url", "artifact_url must use HTTPS on huggingface.co")
        if revision not in parsed.path or artifact_path not in parsed.path:
            raise TrainingDataError("artifact_url", "artifact_url must contain the pinned revision and path")
        licenses = document["reviewed_sample_licenses"]
        if not isinstance(licenses, list) or not licenses:
            raise TrainingDataError("source_licenses", "reviewed_sample_licenses must be non-empty")
        reviewed = tuple(_safe_token(item, "sample_license") for item in licenses)
        if tuple(sorted(set(reviewed))) != reviewed:
            raise TrainingDataError("source_licenses", "reviewed sample licenses must be unique and sorted")
        return cls(
            source_id=source_id,
            provider=provider,
            dataset=dataset,
            dataset_revision=revision,
            dataset_license=_text(document["dataset_license"], "dataset_license", 1, 100),
            artifact_path=artifact_path,
            artifact_url=artifact_url,
            artifact_bytes=_integer(document["artifact_bytes"], "artifact_bytes", 1, 10**10),
            artifact_sha256=_hex(document["artifact_sha256"], "artifact_sha256", exact=64),
            language=_text(document["language"], "language", 1, 100),
            reviewed_sample_licenses=reviewed,
            maximum_examples=_integer(document["maximum_examples"], "maximum_examples", 1, 100_000),
        )


def load_sources(path: str | Path) -> tuple[RepairSource, ...]:
    source = Path(path)
    try:
        document = _load_json(source.read_text(encoding="utf-8"))
    except OSError as exc:
        raise TrainingDataError("source_manifest_read", f"could not read {source}") from exc
    if not isinstance(document, dict) or set(document) != _SOURCE_DOCUMENT_FIELDS:
        raise TrainingDataError("source_manifest_shape", "source manifest fields must match schema v1")
    if document["schema_version"] != 1 or not isinstance(document["sources"], list):
        raise TrainingDataError("source_manifest_shape", "source manifest schema_version must be 1")
    sources = tuple(RepairSource.from_dict(item) for item in document["sources"])
    if not sources or len({item.source_id for item in sources}) != len(sources):
        raise TrainingDataError("source_manifest_shape", "sources must be non-empty with unique IDs")
    return sources


@dataclass(frozen=True, slots=True)
class SourceBuildSummary:
    source_id: str
    raw_records: int
    candidate_records: int
    selected_records: int
    rejection_counts: tuple[tuple[str, int], ...]
    source_sha256: str
    corpus_sha256: str

    def to_dict(self) -> dict[str, object]:
        return {
            "source_id": self.source_id,
            "raw_records": self.raw_records,
            "candidate_records": self.candidate_records,
            "selected_records": self.selected_records,
            "rejection_counts": dict(self.rejection_counts),
            "source_sha256": self.source_sha256,
            "corpus_sha256": self.corpus_sha256,
        }


def verify_artifact(path: str | Path, source: RepairSource) -> str:
    artifact = Path(path)
    try:
        observed_size = artifact.stat().st_size
    except OSError as exc:
        raise TrainingDataError("source_read", f"could not inspect {artifact}") from exc
    if observed_size != source.artifact_bytes:
        raise TrainingDataError(
            "source_size",
            f"source size mismatch: expected {source.artifact_bytes}, observed {observed_size}",
        )
    digest = hashlib.sha256()
    try:
        with artifact.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        raise TrainingDataError("source_read", f"could not hash {artifact}") from exc
    observed_hash = digest.hexdigest()
    if observed_hash != source.artifact_sha256:
        raise TrainingDataError("source_checksum", "source SHA-256 does not match manifest")
    return observed_hash


def build_commitpackft_corpus(
    lines: Iterable[str],
    *,
    source: RepairSource,
    policy: TrainingDataPolicy,
    project_root: str | Path,
) -> tuple[tuple[TrainingExample, ...], SourceBuildSummary]:
    """Normalize a pinned shard and select stable lowest-hash examples."""

    rejected: Counter[str] = Counter()
    raw_records = 0
    candidate_records = 0
    candidates: list[tuple[int, str, TrainingExample]] = []
    seen_example_ids: set[str] = set()
    for raw_records, line in enumerate(lines, 1):
        try:
            document = _load_json(line)
            example = _normalize_commitpackft(document, source=source, policy=policy)
        except TrainingDataError as exc:
            rejected[exc.code] += 1
            continue
        if example.example_id in seen_example_ids:
            rejected["duplicate_source_record"] += 1
            continue
        seen_example_ids.add(example.example_id)
        candidate_records += 1
        rank_hex = hashlib.sha256(example.example_id.encode("utf-8")).hexdigest()
        rank = int(rank_hex, 16)
        candidates.append((rank, example.example_id, example))

    chosen: list[TrainingExample] = []
    seen_inputs: set[str] = set()
    seen_targets: set[str] = set()
    for _, _, example in sorted(candidates):
        input_hash = hashlib.sha256(example.input_text.encode("utf-8")).hexdigest()
        target_hash = hashlib.sha256(example.target_text.encode("utf-8")).hexdigest()
        if input_hash in seen_inputs or target_hash in seen_targets:
            rejected["content_duplicate"] += 1
            continue
        if len(chosen) >= source.maximum_examples:
            rejected["selection_limit"] += 1
            continue
        seen_inputs.add(input_hash)
        seen_targets.add(target_hash)
        chosen.append(example)

    examples = tuple(sorted(chosen, key=lambda item: item.example_id))
    corpus = validate_training_corpus(examples, policy, project_root=project_root)
    summary = SourceBuildSummary(
        source_id=source.source_id,
        raw_records=raw_records,
        candidate_records=candidate_records,
        selected_records=len(examples),
        rejection_counts=tuple(sorted(rejected.items())),
        source_sha256=source.artifact_sha256,
        corpus_sha256=corpus.corpus_sha256,
    )
    return examples, summary


def _normalize_commitpackft(
    document: object,
    *,
    source: RepairSource,
    policy: TrainingDataPolicy,
) -> TrainingExample:
    if not isinstance(document, dict) or set(document) != _RAW_FIELDS:
        raise TrainingDataError("raw_shape", "raw CommitPackFT fields do not match")
    if document["lang"] != source.language:
        raise TrainingDataError("language", "record language does not match source")
    license_name = document["license"]
    if license_name not in source.reviewed_sample_licenses:
        raise TrainingDataError("license", "record license is not in the reviewed allowlist")
    repositories = document["repos"]
    if not isinstance(repositories, str):
        raise TrainingDataError("repository", "record repository must be text")
    unique_repositories = sorted(set(repositories.split(",")))
    if len(unique_repositories) != 1:
        raise TrainingDataError("ambiguous_repository", "record must identify exactly one repository")
    repository = unique_repositories[0]
    if repository.count("/") != 1:
        raise TrainingDataError("repository", "record repository must be owner/name")
    commit = _hex(document["commit"], "commit", exact=40)
    old_path = _relative_path(document["old_file"], "old_file")
    new_path = _relative_path(document["new_file"], "new_file")
    if old_path != new_path:
        raise TrainingDataError("rename", "renames are excluded from schema v1")
    if not old_path.endswith(".py"):
        raise TrainingDataError("path_language", "Python source must end with .py")
    old_contents = _text(document["old_contents"], "old_contents", 1, policy.max_input_chars)
    new_contents = _text(document["new_contents"], "new_contents", 1, policy.max_target_chars)
    if old_contents == new_contents:
        raise TrainingDataError("no_change", "before and after contents must differ")
    subject = _text(document["subject"], "subject", 3, 500).strip()
    identity = hashlib.sha256(
        f"{repository}\0{commit}\0{old_path}".encode("utf-8")
    ).hexdigest()
    lineage_identity = f"{repository}\0{commit}".encode("utf-8")
    lineage_id = f"cpft-{hashlib.sha256(lineage_identity).hexdigest()[:32]}"
    return TrainingExample.from_dict(
        {
            "schema_version": 1,
            "example_id": f"cpft-{identity[:32]}",
            "task_type": TrainingTask.BROKEN_TO_CORRECTED.value,
            "lineage_id": lineage_id,
            "split": assigned_split(lineage_id, policy).value,
            "source_id": f"cpft-{identity[:32]}",
            "source_repository": repository,
            "source_revision": commit,
            "source_license": license_name,
            "license_reviewed": True,
            "instruction": subject,
            "input_text": old_contents,
            "target_text": new_contents,
            "changed_paths": [old_path],
            "test_command": None,
            "test_exit_code": None,
        }
    )


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
        raise TrainingDataError("invalid_json", "invalid JSON record") from exc


def _safe_token(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or any(
        character not in "abcdefghijklmnopqrstuvwxyz0123456789._-" for character in value
    ):
        raise TrainingDataError(field, f"{field} must be lowercase safe text")
    return value


def _hex(value: object, field: str, *, exact: int) -> str:
    if not isinstance(value, str) or len(value) != exact or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise TrainingDataError(field, f"{field} must be {exact} lowercase hex characters")
    return value


def _relative_path(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or value.startswith("/") or "\\" in value:
        raise TrainingDataError("unsafe_path", f"{field} must be a POSIX relative path")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise TrainingDataError("unsafe_path", f"{field} contains an unsafe segment")
    return value


def _text(value: object, field: str, minimum: int, maximum: int) -> str:
    if not isinstance(value, str) or not minimum <= len(value) <= maximum or "\x00" in value:
        raise TrainingDataError(field, f"{field} must contain {minimum}-{maximum} characters")
    return value


def _integer(value: object, field: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise TrainingDataError(field, f"{field} must be an integer from {minimum} to {maximum}")
    return value
