#!/usr/bin/env python3
"""Validate the separately frozen Milestone 004D candidate extension."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
EXTENSION = ROOT / "configs/model_candidate_extension_v1.json"


def load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain one JSON object")
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def validate_extension() -> dict[str, Any]:
    extension = load_object(EXTENSION)
    parent_path = ROOT / extension["parent_experiment"]["manifest"]
    parent = load_object(parent_path)

    if extension.get("schema_version") != 1:
        raise ValueError("extension schema_version must equal 1")
    if extension.get("experiment_id") != "model-compatibility-extension-v1":
        raise ValueError("unexpected extension experiment ID")
    parent_contract = extension["parent_experiment"]
    if parent.get("experiment_id") != parent_contract.get("experiment_id"):
        raise ValueError("parent experiment ID mismatch")
    if parent.get("status") != parent_contract.get("required_status"):
        raise ValueError("parent experiment has not reached the required terminal status")

    for field in (
        "sampling",
        "context_probes_tokens",
        "context_probe_repetitions",
        "context_probe_token_tolerance_fraction",
        "prompt_pack",
        "tool_schemas",
        "system_prompt",
        "gates",
    ):
        if extension.get(field) != parent.get(field):
            raise ValueError(f"extension changed frozen field: {field}")

    source_hashes = extension.get("frozen_source_sha256")
    if not isinstance(source_hashes, dict) or len(source_hashes) != 4:
        raise ValueError("exactly four frozen source hashes are required")
    for relative_path, expected_hash in source_hashes.items():
        if sha256_file(ROOT / relative_path) != expected_hash:
            raise ValueError(f"frozen source hash mismatch: {relative_path}")

    candidates = extension.get("candidates")
    if not isinstance(candidates, list) or len(candidates) != 1:
        raise ValueError("extension must register exactly one candidate")
    candidate = candidates[0]
    expected = {
        "order": 1,
        "upstream_repository": "Qwen/Qwen3.5-9B",
        "upstream_revision": "cc5442c03a5c0bff0bd4c6888d9a40029c637733",
        "upstream_license": "Apache-2.0",
        "ollama_tag": "qwen3.5:9b-q4_K_M",
        "ollama_manifest_digest_prefix": "6488c96fa5fa",
        "quantization": "Q4_K_M",
        "planned_run_id": "m004d-qwen35-9b-v1",
        "status": "downloaded_verified_not_run",
    }
    for key, value in expected.items():
        if candidate.get(key) != value:
            raise ValueError(f"candidate field mismatch: {key}")
    local_hash = candidate.get("local_artifact_sha256")
    if not isinstance(local_hash, str) or len(local_hash) != 64:
        raise ValueError("verified extension candidate requires a full local hash")
    if not local_hash.startswith(candidate["ollama_manifest_digest_prefix"]):
        raise ValueError("local manifest hash does not match the registered prefix")
    blobs = candidate.get("local_blob_sha256")
    if not isinstance(blobs, list) or len(blobs) != candidate.get("local_blob_count"):
        raise ValueError("verified extension candidate must record every blob hash")
    if candidate.get("descriptor_sizes_match") is not True:
        raise ValueError("extension candidate descriptor sizes must be recorded as matching")
    if extension["acquisition_policy"].get("approval_required_before_download") is not True:
        raise ValueError("download must require learner approval")
    return extension


def main() -> int:
    extension = validate_extension()
    candidate = extension["candidates"][0]
    print(f"PASS {extension['experiment_id']}")
    print(f"candidate={candidate['ollama_tag']} status={candidate['status']}")
    print("frozen_sources=4 unchanged_gates=true downloads=1 verified=true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
