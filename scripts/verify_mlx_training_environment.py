#!/usr/bin/env python3
"""Verify the pinned environment and execute one real MLX Metal calculation."""

from __future__ import annotations

import importlib.metadata as metadata
import json
from pathlib import Path
import sys

import mlx.core as mx


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    if Path(sys.prefix).resolve() != (ROOT / ".venv-mlx").resolve():
        raise SystemExit("environment check must run with .venv-mlx/bin/python")
    expected = {"mlx": "0.32.1", "mlx-lm": "0.31.3"}
    observed = {name: metadata.version(name) for name in expected}
    if observed != expected:
        raise SystemExit(f"environment version mismatch: {observed!r}")
    matrix = mx.arange(16, dtype=mx.float32).reshape(4, 4)
    result = matrix @ matrix.T
    mx.eval(result)
    observed_sum = float(mx.sum(result).item())
    if observed_sum != 3680.0:
        raise SystemExit(f"unexpected MLX result: {observed_sum}")
    print(
        json.dumps(
            {
                "status": "mlx_environment_ready",
                "versions": observed,
                "matrix_sum": observed_sum,
                "peak_memory_bytes": mx.get_peak_memory(),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
