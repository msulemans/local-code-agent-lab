#!/usr/bin/env python3
"""Download the exact Milestone 015 base checkpoint and record local hashes."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

from huggingface_hub import snapshot_download


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "benchmarks/training/m015_baseline_v1.json"
DESTINATION = ROOT / "models/qwen25-coder-1.5b-instruct-m015"
LOCAL_MANIFEST = ROOT / "models/m015-local-model.json"


def main() -> int:
    if Path(sys.prefix).resolve() != (ROOT / ".venv-mlx").resolve():
        raise SystemExit("model download must run with .venv-mlx/bin/python")
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    model = config["model"]
    snapshot = Path(
        snapshot_download(
            repo_id=model["model_id"],
            revision=model["revision"],
            local_dir=DESTINATION,
        )
    )
    files = []
    for path in sorted(item for item in snapshot.rglob("*") if item.is_file()):
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        files.append(
            {
                "path": path.relative_to(snapshot).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": digest.hexdigest(),
            }
        )
    manifest = {
        "schema_version": 1,
        "model_id": model["model_id"],
        "resolved_revision": model["revision"],
        "snapshot_path": str(snapshot.resolve()),
        "total_bytes": sum(item["bytes"] for item in files),
        "files": files,
    }
    LOCAL_MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({**manifest, "files": len(files)}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
