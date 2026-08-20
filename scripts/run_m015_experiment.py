#!/usr/bin/env python3
"""Run and record the untouched validation baseline or two-update LoRA probe."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "benchmarks/training/m015_baseline_v1.json"
MODEL_MANIFEST = ROOT / "models/m015-local-model.json"
MODEL_PATH = ROOT / "models/qwen25-coder-1.5b-instruct-m015"
TRAIN_DATA = ROOT / "data/processed/mlx-m015"
VALIDATION_EVAL = ROOT / "data/processed/mlx-m015-validation-eval"
RUN_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{2,79}$")
SWAP = re.compile(r"used = ([0-9.]+)M")
TEST_RESULT = re.compile(r"Test loss ([0-9.]+), Test ppl ([0-9.]+)\.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("baseline", "probe", "reload"), required=True)
    parser.add_argument("--run-id", required=True)
    arguments = parser.parse_args()
    if Path(sys.prefix).resolve() != (ROOT / ".venv-mlx").resolve():
        raise SystemExit("M015 experiment must run with .venv-mlx/bin/python")
    if RUN_ID.fullmatch(arguments.run_id) is None:
        raise SystemExit("run ID must contain 3-80 lowercase safe characters")
    run_directory = ROOT / "runs/training" / arguments.run_id
    try:
        run_directory.mkdir(parents=True)
    except FileExistsError as exc:
        raise SystemExit(f"run directory already exists: {run_directory}") from exc

    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    model_manifest = json.loads(MODEL_MANIFEST.read_text(encoding="utf-8"))
    if model_manifest["resolved_revision"] != config["model"]["revision"]:
        raise SystemExit("local model revision does not match M015 config")
    command = _command(arguments.mode, arguments.run_id, config)
    record = {
        "schema_version": 1,
        "run_id": arguments.run_id,
        "mode": arguments.mode,
        "state": "running",
        "command": command,
        "model_id": config["model"]["model_id"],
        "model_revision": config["model"]["revision"],
        "data": config["data"],
        "sealed_examples_loaded": 0,
        "swap_used_before_bytes": _swap_used_bytes(),
        "swap_used_after_bytes": None,
        "wall_seconds": None,
        "exit_code": None,
        "stdout": "",
        "stderr": "",
        "metrics": {},
        "adapter": None,
    }
    _write_record(run_directory, record)
    started = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=1800,
        )
    except subprocess.TimeoutExpired as exc:
        record.update(
            state="timeout",
            wall_seconds=round(time.monotonic() - started, 6),
            exit_code=2,
            stdout=exc.stdout or "",
            stderr=exc.stderr or "",
            swap_used_after_bytes=_swap_used_bytes(),
        )
        _write_record(run_directory, record)
        print(json.dumps(_summary(record, run_directory), indent=2, sort_keys=True))
        return 2

    stdout = completed.stdout
    metrics: dict[str, object] = {}
    result = TEST_RESULT.search(stdout)
    if result is not None:
        metrics.update(loss=float(result.group(1)), perplexity=float(result.group(2)))
    losses = [float(value) for value in re.findall(r"Train loss ([0-9.]+)", stdout)]
    if losses:
        metrics["train_losses"] = losses
        metrics["all_train_losses_finite"] = all(value == value and abs(value) != float("inf") for value in losses)
    validation_losses = [float(value) for value in re.findall(r"Val loss ([0-9.]+)", stdout)]
    if validation_losses:
        metrics["validation_losses"] = validation_losses
    peak_memory = [float(value) for value in re.findall(r"Peak mem ([0-9.]+) GB", stdout)]
    if peak_memory:
        metrics["peak_memory_gb"] = max(peak_memory)
    adapter_run_id = "m015-probe-v1" if arguments.mode == "reload" else arguments.run_id
    adapter = _adapter_evidence(adapter_run_id) if arguments.mode in {"probe", "reload"} else None
    successful = completed.returncode == 0 and (
        (arguments.mode == "baseline" and "loss" in metrics)
        or (
            arguments.mode == "probe"
            and adapter is not None
            and metrics.get("all_train_losses_finite") is True
            and 0 < metrics.get("peak_memory_gb", 25) <= 24
        )
        or (arguments.mode == "reload" and adapter is not None and "loss" in metrics)
    )
    record.update(
        state="completed" if successful else "failed",
        wall_seconds=round(time.monotonic() - started, 6),
        exit_code=0 if successful else 1,
        process_exit_code=completed.returncode,
        stdout=stdout,
        stderr=completed.stderr,
        metrics=metrics,
        adapter=adapter,
        swap_used_after_bytes=_swap_used_bytes(),
    )
    _write_record(run_directory, record)
    print(stdout, end="")
    if completed.stderr:
        print(completed.stderr, file=sys.stderr, end="")
    print(json.dumps(_summary(record, run_directory), indent=2, sort_keys=True))
    return int(record["exit_code"])


def _command(mode: str, run_id: str, config: dict[str, object]) -> list[str]:
    executable = str(ROOT / ".venv-mlx/bin/mlx_lm.lora")
    probe = config["probe"]
    common = [
        executable,
        "--model",
        str(MODEL_PATH),
        "--batch-size",
        str(probe["batch_size"]),
        "--max-seq-length",
        str(probe["max_sequence_length"]),
        "--seed",
        str(probe["seed"]),
    ]
    if mode in {"baseline", "reload"}:
        adapter_path = "" if mode == "baseline" else str(ROOT / "adapters/m015-probe-v1")
        return common + [
            "--data",
            str(VALIDATION_EVAL),
            "--test",
            "--test-batches",
            "-1" if mode == "baseline" else "2",
            "--adapter-path",
            adapter_path,
        ]
    return common + [
        "--data",
        str(TRAIN_DATA),
        "--train",
        "--fine-tune-type",
        str(probe["fine_tune_type"]),
        "--optimizer",
        str(probe["optimizer"]),
        "--mask-prompt",
        "--num-layers",
        str(probe["num_layers"]),
        "--iters",
        str(probe["iterations"]),
        "--val-batches",
        str(probe["validation_batches"]),
        "--learning-rate",
        str(probe["learning_rate"]),
        "--steps-per-report",
        "1",
        "--steps-per-eval",
        "1",
        "--save-every",
        "1",
        "--grad-checkpoint",
        "--adapter-path",
        str(ROOT / "adapters" / run_id),
    ]


def _swap_used_bytes() -> int | None:
    try:
        output = subprocess.run(
            ("sysctl", "vm.swapusage"),
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    match = SWAP.search(output)
    return None if match is None else round(float(match.group(1)) * 1024 * 1024)


def _adapter_evidence(run_id: str) -> dict[str, object] | None:
    path = ROOT / "adapters" / run_id / "adapters.safetensors"
    if not path.is_file():
        return None
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return {"path": str(path.relative_to(ROOT)), "bytes": path.stat().st_size, "sha256": digest}


def _write_record(directory: Path, record: dict[str, object]) -> None:
    temporary = directory / "run.json.tmp"
    destination = directory / "run.json"
    temporary.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(destination)


def _summary(record: dict[str, object], directory: Path) -> dict[str, object]:
    return {
        "run_id": record["run_id"],
        "mode": record["mode"],
        "state": record["state"],
        "wall_seconds": record["wall_seconds"],
        "metrics": record["metrics"],
        "adapter": record["adapter"],
        "swap_growth_bytes": (
            None
            if record["swap_used_before_bytes"] is None or record["swap_used_after_bytes"] is None
            else record["swap_used_after_bytes"] - record["swap_used_before_bytes"]
        ),
        "artifact": str(directory),
    }


if __name__ == "__main__":
    raise SystemExit(main())
