from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from localcode.training_data import TrainingDataError, TrainingDataPolicy
from localcode.training_sources import (
    build_commitpackft_corpus,
    load_sources,
    verify_artifact,
)


ROOT = Path(__file__).resolve().parents[2]
POLICY = TrainingDataPolicy.from_path(ROOT / "benchmarks/training_data/manifest_v1.json")
SOURCE_MANIFEST = ROOT / "benchmarks/training_data/sources_v1.json"


def raw_record(**changes: object) -> dict[str, object]:
    record: dict[str, object] = {
        "commit": "a" * 40,
        "old_file": "src/parser.py",
        "new_file": "src/parser.py",
        "old_contents": "def parse(value):\n    return value.strip()\n",
        "new_contents": "def parse(value):\n    return (value or '').strip()\n",
        "subject": "Handle an absent parser value",
        "message": "Handle an absent parser value\n",
        "lang": "Python",
        "license": "mit",
        "repos": "example/parser",
    }
    record.update(changes)
    return record


class TrainingSourceTests(unittest.TestCase):
    def test_manifest_pins_source_revision_size_checksum_and_license_gate(self) -> None:
        source = load_sources(SOURCE_MANIFEST)[0]
        self.assertEqual(source.dataset_revision, "fc56fe33c030c6daa414c2b112c932b8eed085e6")
        self.assertEqual(source.artifact_bytes, 135858935)
        self.assertEqual(len(source.artifact_sha256), 64)
        self.assertNotIn("unknown", source.reviewed_sample_licenses)
        self.assertNotIn("agpl-3.0", source.reviewed_sample_licenses)

    def test_artifact_verification_requires_exact_bytes_and_sha256(self) -> None:
        source = load_sources(SOURCE_MANIFEST)[0]
        payload = b"pinned source\n"
        adjusted = source.__class__(
            **{
                **{field: getattr(source, field) for field in source.__dataclass_fields__},
                "artifact_bytes": len(payload),
                "artifact_sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
        with tempfile.TemporaryDirectory() as temporary:
            artifact = Path(temporary) / "data.jsonl"
            artifact.write_bytes(payload)
            self.assertEqual(verify_artifact(artifact, adjusted), adjusted.artifact_sha256)
            artifact.write_bytes(payload + b"x")
            with self.assertRaisesRegex(TrainingDataError, "size mismatch"):
                verify_artifact(artifact, adjusted)

    def test_normalizer_builds_canonical_example_and_rejection_report(self) -> None:
        source = load_sources(SOURCE_MANIFEST)[0]
        source = source.__class__(
            **{
                **{field: getattr(source, field) for field in source.__dataclass_fields__},
                "maximum_examples": 10,
            }
        )
        records = [
            raw_record(),
            raw_record(commit="b" * 40, repos="one/repo,two/repo"),
            raw_record(commit="c" * 40, license="unknown"),
            raw_record(commit="d" * 40, new_file="src/renamed.py"),
            raw_record(commit="e" * 40, lang="Java"),
            {"not": "the source schema"},
        ]
        examples, summary = build_commitpackft_corpus(
            (json.dumps(record) for record in records),
            source=source,
            policy=POLICY,
            project_root=ROOT,
        )
        self.assertEqual(len(examples), 1)
        self.assertEqual(examples[0].source_repository, "example/parser")
        self.assertEqual(examples[0].target_text, raw_record()["new_contents"])
        self.assertEqual(summary.raw_records, 6)
        self.assertEqual(summary.candidate_records, 1)
        self.assertEqual(
            dict(summary.rejection_counts),
            {"ambiguous_repository": 1, "language": 1, "license": 1, "raw_shape": 1, "rename": 1},
        )

    def test_selection_is_order_independent_and_bounded(self) -> None:
        source = load_sources(SOURCE_MANIFEST)[0]
        source = source.__class__(
            **{
                **{field: getattr(source, field) for field in source.__dataclass_fields__},
                "maximum_examples": 2,
            }
        )
        records = [
            json.dumps(
                raw_record(
                    commit=f"{index:040x}",
                    old_contents=f"value = {index}\n",
                    new_contents=f"value = {index + 1}\n",
                )
            )
            for index in range(1, 5)
        ]
        forward, first = build_commitpackft_corpus(
            records, source=source, policy=POLICY, project_root=ROOT
        )
        backward, second = build_commitpackft_corpus(
            reversed(records), source=source, policy=POLICY, project_root=ROOT
        )
        self.assertEqual(forward, backward)
        self.assertEqual(first.corpus_sha256, second.corpus_sha256)
        self.assertEqual(first.selected_records, 2)
        self.assertEqual(dict(first.rejection_counts)["selection_limit"], 2)


if __name__ == "__main__":
    unittest.main()
