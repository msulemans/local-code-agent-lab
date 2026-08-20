"""Strict verification for a locally downloaded, revision-pinned model snapshot."""

from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath
from typing import Any


class ModelPinError(ValueError):
    """Raised when a local model does not match its frozen artifact contract."""


def verify_model_pin(document: dict[str, Any], *, project_root: str | Path) -> Path:
    if not isinstance(document, dict) or set(document) != {
        "model_id", "source_model_id", "revision", "snapshot_path",
        "quantization_bits", "total_pinned_bytes", "files",
    }:
        raise ModelPinError("model pin fields must match the versioned contract")
    if document["quantization_bits"] != 4:
        raise ModelPinError("M017 requires the frozen 4-bit model")
    revision = document["revision"]
    if not isinstance(revision, str) or len(revision) != 40 or any(character not in "0123456789abcdef" for character in revision):
        raise ModelPinError("model revision must be a full lowercase commit hash")
    relative_root = _relative(document["snapshot_path"])
    project = Path(project_root).resolve()
    candidate = project / relative_root
    if candidate.is_symlink():
        raise ModelPinError("model snapshot root must not be a symlink")
    root = candidate.resolve()
    if not root.is_relative_to(project) or not root.is_dir():
        raise ModelPinError(f"model snapshot is missing: {relative_root}")
    files = document["files"]
    if not isinstance(files, list) or not files:
        raise ModelPinError("model pin must contain files")
    seen: set[str] = set()
    total = 0
    for entry in files:
        if not isinstance(entry, dict) or set(entry) != {"path", "bytes", "sha256"}:
            raise ModelPinError("model file pin fields are invalid")
        relative = _relative(entry["path"])
        key = relative.as_posix()
        if key in seen:
            raise ModelPinError("model file pins must be unique")
        seen.add(key)
        path = root / relative
        expected_bytes = entry["bytes"]
        expected_hash = entry["sha256"]
        if not path.is_file() or path.is_symlink():
            raise ModelPinError(f"pinned model file is missing or unsafe: {key}")
        if isinstance(expected_bytes, bool) or not isinstance(expected_bytes, int) or expected_bytes < 0:
            raise ModelPinError("model file byte count is invalid")
        if path.stat().st_size != expected_bytes:
            raise ModelPinError(f"model file byte count mismatch: {key}")
        if not isinstance(expected_hash, str) or _sha(path) != expected_hash:
            raise ModelPinError(f"model file hash mismatch: {key}")
        total += expected_bytes
    if total != document["total_pinned_bytes"]:
        raise ModelPinError("model total pinned bytes mismatch")
    return root


def _relative(value: object) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ModelPinError("model paths must be non-empty POSIX relative paths")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ModelPinError("model paths must stay relative and canonical")
    return path


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
