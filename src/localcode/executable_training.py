"""Deterministic SWE-smith normalization for executable-aligned repair training."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
import hashlib
import json
from pathlib import PurePosixPath
import re
from typing import Any, Iterable

from .training_data import (
    TrainingDataError,
    TrainingDataPolicy,
    TrainingExample,
    TrainingTask,
    assigned_split,
    validate_training_corpus,
)


_RAW_FIELDS = {
    "instance_id",
    "patch",
    "FAIL_TO_PASS",
    "PASS_TO_PASS",
    "image_name",
    "repo",
    "problem_statement",
}
_REPO = re.compile(
    r"^swesmith/([A-Za-z0-9_.-]+)__([A-Za-z0-9_.-]+)\.([0-9a-f]{8})$"
)
_DIFF = re.compile(r"^diff --git a/([^\s]+) b/([^\s]+)$")
_INDEX = re.compile(r"^index ([0-9a-f]+)\.\.([0-9a-f]+)(.*)$")
_HUNK = re.compile(r"^@@ -([^ ]+) \+([^ ]+) @@(.*)$")


@dataclass(frozen=True, slots=True)
class ExecutableSource:
    source_id: str
    dataset_revision: str
    artifact_bytes: int
    artifact_sha256: str
    maximum_examples: int
    maximum_examples_per_repository: int
    allowed_repository_licenses: tuple[tuple[str, str], ...]
    maximum_problem_chars: int
    maximum_patch_chars: int
    maximum_failing_tests: int

    @classmethod
    def from_document(cls, document: object) -> "ExecutableSource":
        if not isinstance(document, dict) or document.get("schema_version") != 1:
            raise TrainingDataError("source_manifest", "source manifest must use schema v1")
        sources = document.get("sources")
        if not isinstance(sources, list) or len(sources) != 1 or not isinstance(sources[0], dict):
            raise TrainingDataError("source_manifest", "M016b requires exactly one source")
        source = sources[0]
        required = {
            "source_id", "provider", "dataset", "dataset_revision", "dataset_license",
            "artifact_path", "artifact_url", "artifact_bytes", "artifact_sha256", "language",
            "maximum_examples", "maximum_examples_per_repository",
            "allowed_repository_licenses", "quality_requirements",
        }
        if set(source) != required:
            raise TrainingDataError("source_manifest", "M016b source fields must match exactly")
        if source["provider"] != "huggingface" or source["dataset"] != "SWE-bench/SWE-smith-py":
            raise TrainingDataError("source_manifest", "unexpected M016b source identity")
        if source["dataset_license"] != "MIT" or source["language"] != "Python":
            raise TrainingDataError("source_manifest", "unexpected source license or language")
        licenses = source["allowed_repository_licenses"]
        if not isinstance(licenses, dict) or not licenses:
            raise TrainingDataError("source_manifest", "reviewed repository licenses are required")
        quality = source["quality_requirements"]
        expected_quality = {
            "requires_fail_to_pass", "single_file_only", "python_file_only",
            "maximum_problem_chars", "maximum_patch_chars", "maximum_failing_tests",
        }
        if not isinstance(quality, dict) or set(quality) != expected_quality:
            raise TrainingDataError("source_manifest", "quality requirements must match exactly")
        if not all(quality[name] is True for name in (
            "requires_fail_to_pass", "single_file_only", "python_file_only"
        )):
            raise TrainingDataError("source_manifest", "all executable quality gates are required")
        return cls(
            source_id=_safe_text(source["source_id"], "source_id"),
            dataset_revision=_hex(source["dataset_revision"], "dataset_revision", 40),
            artifact_bytes=_positive_int(source["artifact_bytes"], "artifact_bytes"),
            artifact_sha256=_hex(source["artifact_sha256"], "artifact_sha256", 64),
            maximum_examples=_positive_int(source["maximum_examples"], "maximum_examples"),
            maximum_examples_per_repository=_positive_int(
                source["maximum_examples_per_repository"], "maximum_examples_per_repository"
            ),
            allowed_repository_licenses=tuple(sorted(
                (_repository(name), _safe_text(license_name, "repository license"))
                for name, license_name in licenses.items()
            )),
            maximum_problem_chars=_positive_int(quality["maximum_problem_chars"], "maximum_problem_chars"),
            maximum_patch_chars=_positive_int(quality["maximum_patch_chars"], "maximum_patch_chars"),
            maximum_failing_tests=_positive_int(quality["maximum_failing_tests"], "maximum_failing_tests"),
        )

    def license_map(self) -> dict[str, str]:
        return dict(self.allowed_repository_licenses)


@dataclass(frozen=True, slots=True)
class ExecutableBuildSummary:
    raw_records: int
    candidate_records: int
    selected_records: int
    split_counts: tuple[tuple[str, int], ...]
    repository_counts: tuple[tuple[str, int], ...]
    rejection_counts: tuple[tuple[str, int], ...]
    corpus_sha256: str

    def to_dict(self) -> dict[str, object]:
        return {
            "raw_records": self.raw_records,
            "candidate_records": self.candidate_records,
            "selected_records": self.selected_records,
            "split_counts": dict(self.split_counts),
            "repository_counts": dict(self.repository_counts),
            "rejection_counts": dict(self.rejection_counts),
            "corpus_sha256": self.corpus_sha256,
        }


def build_executable_corpus(
    rows: Iterable[dict[str, Any]],
    *,
    source: ExecutableSource,
    policy: TrainingDataPolicy,
    project_root: str,
) -> tuple[tuple[TrainingExample, ...], ExecutableBuildSummary]:
    """Normalize, diversity-cap, and validate one pinned SWE-smith shard."""

    rejected: Counter[str] = Counter()
    candidates: list[tuple[str, TrainingExample]] = []
    raw_records = 0
    for raw_records, row in enumerate(rows, 1):
        try:
            example = _normalize(row, source=source, policy=policy)
        except TrainingDataError as exc:
            rejected[exc.code] += 1
            continue
        rank = hashlib.sha256(example.example_id.encode("utf-8")).hexdigest()
        candidates.append((rank, example))

    per_repository: Counter[str] = Counter()
    selected: list[TrainingExample] = []
    for _, example in sorted(candidates, key=lambda item: (item[0], item[1].example_id)):
        if per_repository[example.source_repository] >= source.maximum_examples_per_repository:
            rejected["repository_cap"] += 1
            continue
        if len(selected) >= source.maximum_examples:
            rejected["selection_limit"] += 1
            continue
        selected.append(example)
        per_repository[example.source_repository] += 1

    corpus = validate_training_corpus(selected, policy, project_root=project_root)
    return tuple(sorted(selected, key=lambda item: item.example_id)), ExecutableBuildSummary(
        raw_records=raw_records,
        candidate_records=len(candidates),
        selected_records=len(selected),
        split_counts=corpus.split_counts,
        repository_counts=tuple(sorted(per_repository.items())),
        rejection_counts=tuple(sorted(rejected.items())),
        corpus_sha256=corpus.corpus_sha256,
    )


def reverse_mutation_patch(patch: str) -> tuple[str, tuple[str, ...], str]:
    """Return the gold repair diff and a non-leaking excerpt of the broken postimage."""

    if not isinstance(patch, str) or not patch.endswith("\n"):
        raise TrainingDataError("patch_format", "mutation patch must be newline-terminated text")
    forbidden = ("new file mode", "deleted file mode", "rename from", "rename to", "Binary files")
    if any(marker in patch for marker in forbidden) or " /dev/null" in patch:
        raise TrainingDataError("patch_operation", "only text modifications are supported")
    if "\\ No newline at end of file" in patch:
        raise TrainingDataError("patch_operation", "no-newline patches are excluded")
    lines = patch.splitlines()
    headers = [line for line in lines if line.startswith("diff --git ")]
    if len(headers) != 1:
        raise TrainingDataError("path_count", "exactly one changed file is required")
    match = _DIFF.fullmatch(headers[0])
    if match is None or match.group(1) != match.group(2):
        raise TrainingDataError("patch_path", "patch must modify one stable path")
    path = _path(match.group(1))
    if not path.endswith(".py"):
        raise TrainingDataError("path_language", "changed file must be Python")

    repaired: list[str] = []
    broken: list[str] = [f"File: {path}"]
    in_hunk = False
    index_position = 0
    while index_position < len(lines):
        line = lines[index_position]
        if line.startswith("diff --git "):
            repaired.append(line)
        elif (index := _INDEX.fullmatch(line)) is not None:
            repaired.append(f"index {index.group(2)}..{index.group(1)}{index.group(3)}")
        elif line.startswith("--- "):
            repaired.append(f"--- a/{path}")
        elif line.startswith("+++ "):
            repaired.append(f"+++ b/{path}")
        elif (hunk := _HUNK.fullmatch(line)) is not None:
            in_hunk = True
            repaired.append(f"@@ -{hunk.group(2)} +{hunk.group(1)} @@{hunk.group(3)}")
            broken.append(f"@@ postimage {hunk.group(2)} @@{hunk.group(3)}")
        elif in_hunk and line.startswith(("+", "-")):
            changed: list[str] = []
            while index_position < len(lines) and lines[index_position].startswith(("+", "-")):
                changed.append(lines[index_position])
                index_position += 1
            # A forward mutation replaces original correct lines (-) with
            # broken lines (+). Its repair must delete the broken postimage
            # first, then restore the original lines.
            for changed_line in changed:
                if changed_line.startswith("+"):
                    repaired.append("-" + changed_line[1:])
                    broken.append("! " + changed_line[1:])
            for changed_line in changed:
                if changed_line.startswith("-"):
                    repaired.append("+" + changed_line[1:])
            continue
        else:
            repaired.append(line)
            if in_hunk and (line.startswith(" ") or line == ""):
                broken.append("  " + line[1:] if line.startswith(" ") else "")
        index_position += 1
    if not in_hunk:
        raise TrainingDataError("patch_format", "patch must contain a unified diff hunk")
    return "\n".join(repaired) + "\n", (path,), "\n".join(broken).strip() + "\n"


def _normalize(
    row: object,
    *,
    source: ExecutableSource,
    policy: TrainingDataPolicy,
) -> TrainingExample:
    if not isinstance(row, dict) or set(row) != _RAW_FIELDS:
        raise TrainingDataError("raw_shape", "SWE-smith row fields do not match")
    instance_id = _safe_text(row["instance_id"], "instance_id")
    repo_value = _safe_text(row["repo"], "repo")
    repo_match = _REPO.fullmatch(repo_value)
    if repo_match is None:
        raise TrainingDataError("repository", "SWE-smith repository identity is invalid")
    repository = f"{repo_match.group(1)}/{repo_match.group(2)}"
    license_name = source.license_map().get(repository)
    if license_name is None:
        raise TrainingDataError("license", "repository license is not in the reviewed allowlist")
    revision = repo_match.group(3)
    problem = _safe_text(row["problem_statement"], "problem_statement").strip()
    if len(problem) > source.maximum_problem_chars:
        raise TrainingDataError("problem_size", "problem statement exceeds the source limit")
    patch = _safe_text(row["patch"], "patch")
    if len(patch) > source.maximum_patch_chars:
        raise TrainingDataError("patch_size", "patch exceeds the source limit")
    failing = row["FAIL_TO_PASS"]
    if not isinstance(failing, list) or not failing or len(failing) > source.maximum_failing_tests:
        raise TrainingDataError("test_evidence", "FAIL_TO_PASS must be non-empty and bounded")
    if any(not isinstance(test, str) or not test.strip() for test in failing):
        raise TrainingDataError("test_evidence", "FAIL_TO_PASS entries must be non-empty text")
    if not isinstance(row["PASS_TO_PASS"], list):
        raise TrainingDataError("test_evidence", "PASS_TO_PASS must be a list")

    repair, paths, broken_excerpt = reverse_mutation_patch(patch)
    tests = "\n".join(f"- {test}" for test in failing)
    input_text = f"Failing tests:\n{tests}\n\nBroken repository excerpts:\n{broken_excerpt}"
    if len(input_text) > policy.max_input_chars:
        raise TrainingDataError("input_size", "rendered model input exceeds policy")
    identity = hashlib.sha256(f"{source.source_id}\0{instance_id}".encode()).hexdigest()
    lineage = hashlib.sha256(f"{repository}\0{revision}\0{paths[0]}".encode()).hexdigest()
    lineage_id = f"smith-lineage-{lineage[:32]}"
    return TrainingExample.from_dict({
        "schema_version": 1,
        "example_id": f"smith-{identity[:32]}",
        "task_type": TrainingTask.ISSUE_TO_DIFF.value,
        "lineage_id": lineage_id,
        "split": assigned_split(lineage_id, policy).value,
        "source_id": f"smith-source-{identity[:32]}",
        "source_repository": repository,
        "source_revision": revision,
        "source_license": license_name,
        "license_reviewed": True,
        "instruction": problem,
        "input_text": input_text,
        "target_text": repair,
        "changed_paths": list(paths),
        "test_command": "SWE-smith FAIL_TO_PASS: " + " | ".join(failing),
        "test_exit_code": 1,
    })


def _path(value: str) -> str:
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or str(path) in {"", "."}:
        raise TrainingDataError("patch_path", "patch path must stay repository-relative")
    return str(path)


def _repository(value: object) -> str:
    text = _safe_text(value, "repository")
    if text.count("/") != 1:
        raise TrainingDataError("source_manifest", "repository must be owner/name")
    return text


def _safe_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TrainingDataError(field, f"{field} must be non-empty text")
    return value


def _hex(value: object, field: str, length: int) -> str:
    if not isinstance(value, str) or re.fullmatch(f"[0-9a-f]{{{length}}}", value) is None:
        raise TrainingDataError("source_manifest", f"{field} must be {length} lowercase hex characters")
    return value


def _positive_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise TrainingDataError("source_manifest", f"{field} must be a positive integer")
    return value
