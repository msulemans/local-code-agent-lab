#!/usr/bin/env python3
"""Inspect and verify one locally downloaded Ollama library artifact."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
from typing import Any


MODEL_PART = re.compile(r"^[A-Za-z0-9._-]+$")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_artifact(model: str, storage_root: Path) -> dict[str, Any]:
    if model.count(":") != 1:
        raise ValueError("model must use the exact library name:tag form")
    name, tag = model.split(":", 1)
    if not MODEL_PART.fullmatch(name) or not MODEL_PART.fullmatch(tag):
        raise ValueError("model name and tag may contain only letters, digits, dot, underscore, and hyphen")

    root = storage_root.expanduser().resolve(strict=True)
    manifest_path = root / "manifests" / "registry.ollama.ai" / "library" / name / tag
    try:
        manifest_bytes = manifest_path.read_bytes()
    except FileNotFoundError as error:
        raise ValueError(f"manifest not found; model is not downloaded: {model}") from error
    try:
        manifest = json.loads(manifest_bytes)
    except json.JSONDecodeError as error:
        raise ValueError(f"manifest is invalid JSON: {error.msg}") from error
    if not isinstance(manifest, dict) or manifest.get("schemaVersion") != 2:
        raise ValueError("unsupported Ollama manifest schema")

    descriptors = [manifest.get("config"), *manifest.get("layers", [])]
    if any(not isinstance(descriptor, dict) for descriptor in descriptors):
        raise ValueError("manifest descriptors must be objects")

    blobs: list[dict[str, Any]] = []
    total_blob_bytes = 0
    size_mismatches: list[dict[str, Any]] = []
    for descriptor in descriptors:
        digest = descriptor.get("digest")
        expected_size = descriptor.get("size")
        if not isinstance(digest, str) or not digest.startswith("sha256:"):
            raise ValueError("every descriptor must contain a SHA-256 digest")
        expected_sha256 = digest.removeprefix("sha256:")
        if len(expected_sha256) != 64 or not all(character in "0123456789abcdef" for character in expected_sha256):
            raise ValueError(f"invalid SHA-256 digest: {digest}")
        if isinstance(expected_size, bool) or not isinstance(expected_size, int) or expected_size < 0:
            raise ValueError(f"invalid blob size for {digest}")

        blob_path = root / "blobs" / f"sha256-{expected_sha256}"
        try:
            actual_size = blob_path.stat().st_size
        except FileNotFoundError as error:
            raise ValueError(f"referenced blob is missing: {digest}") from error
        actual_sha256 = sha256_file(blob_path)
        if actual_sha256 != expected_sha256:
            raise ValueError(f"blob hash mismatch: {digest}")

        size_matches_manifest = actual_size == expected_size
        if not size_matches_manifest:
            size_mismatches.append(
                {
                    "sha256": actual_sha256,
                    "manifest_bytes": expected_size,
                    "actual_bytes": actual_size,
                }
            )

        blobs.append(
            {
                "media_type": descriptor.get("mediaType"),
                "sha256": actual_sha256,
                "bytes": actual_size,
                "manifest_bytes": expected_size,
                "size_matches_manifest": size_matches_manifest,
            }
        )
        total_blob_bytes += actual_size

    return {
        "schema_version": 1,
        "model": model,
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "manifest_bytes": len(manifest_bytes),
        "blob_count": len(blobs),
        "total_blob_bytes": total_blob_bytes,
        "descriptor_sizes_match": not size_mismatches,
        "size_mismatches": size_mismatches,
        "blobs": blobs,
        "hashes_verified": True,
        "verified": True,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model", help="exact Ollama library name:tag")
    parser.add_argument(
        "--storage-root",
        type=Path,
        default=Path.home() / ".ollama" / "models",
        help="Ollama models directory (default: ~/.ollama/models)",
    )
    return parser.parse_args()


def main() -> int:
    arguments = parse_args()
    try:
        result = inspect_artifact(arguments.model, arguments.storage_root)
    except (OSError, ValueError) as error:
        print(f"ERROR: {error}")
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
