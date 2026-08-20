#!/usr/bin/env python3
"""Validate and executable-test M016b checkpoints preserved after Metal stops."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import re
import shutil
import sys
import time

from localcode.training_run import available_checkpoint_iterations, parse_validation_metric
from run_m016b_training import (
    ROOT,
    _adapter_evidence,
    _candidate_adapter,
    _evaluate_adapter,
    _load_and_verify,
    _prepare_validation_data,
    _run,
    _sha,
    _validation_command,
    _write,
)


RUN_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{2,79}$")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-run-id", required=True)
    parser.add_argument("--run-id", required=True)
    arguments = parser.parse_args()
    if Path(sys.prefix).resolve() != (ROOT / ".venv-mlx").resolve():
        raise SystemExit("M016b recovery must run with .venv-mlx/bin/python")
    if RUN_ID.fullmatch(arguments.source_run_id) is None or RUN_ID.fullmatch(arguments.run_id) is None:
        raise SystemExit("run IDs must contain 3-80 lowercase safe characters")
    if arguments.source_run_id == arguments.run_id:
        raise SystemExit("recovery requires a fresh immutable run ID")

    run_dir = ROOT / "runs/training" / arguments.run_id
    adapter_root = ROOT / "adapters" / arguments.run_id
    try:
        run_dir.mkdir(parents=True)
        adapter_root.mkdir(parents=True)
    except FileExistsError as exc:
        raise SystemExit("run or adapter directory already exists; use a new run ID") from exc

    started = time.monotonic()
    record: dict[str, object] = {
        "schema_version": 1,
        "run_id": arguments.run_id,
        "state": "setup",
        "treatment": "completed_checkpoints_after_interrupted_m016b_training",
        "source_run_id": arguments.source_run_id,
        "source_run_state": None,
        "original_800_step_treatment_complete": False,
        "available_checkpoint_iterations": [],
        "checkpoint_validation": [],
        "selected_adapter": None,
        "executable_evaluation": None,
        "sealed_examples_loaded": 0,
        "wall_seconds": None,
        "error": None,
    }
    _write(run_dir, record)
    try:
        config, _, suite = _load_and_verify()
        source_record = json.loads(
            (ROOT / "runs/training" / arguments.source_run_id / "run.json").read_text(encoding="utf-8")
        )
        if source_record.get("state") != "failed" or source_record.get("sealed_examples_loaded") != 0:
            raise ValueError("source must be a failed zero-sealed M016b run")
        allowed_experiments = {
            config["experiment_id"],
            "m016b-qwen25-coder-executable-lora-v3-staged",
        }
        if source_record.get("experiment_id") not in allowed_experiments:
            raise ValueError("source run does not belong to an executable-aligned M016b experiment")

        source_adapter = ROOT / "adapters" / arguments.source_run_id / "full"
        expected = tuple(int(value) for value in config["full_training"]["checkpoint_iterations"])
        available = available_checkpoint_iterations(source_adapter, expected)
        if not available:
            raise ValueError("recovery requires at least one completed checkpoint")
        record.update(
            state="checkpoint_validation_running",
            source_run_state=source_record["state"],
            available_checkpoint_iterations=list(available),
        )
        _write(run_dir, record)

        validation_dir = _prepare_validation_data(config, arguments.run_id)
        validations = []
        for iteration in available:
            candidate = _candidate_adapter(source_adapter, adapter_root, iteration)
            process = _run(_validation_command(config, validation_dir, candidate), 900)
            if process.returncode != 0:
                raise RuntimeError(f"validation failed for checkpoint {iteration}")
            metric = parse_validation_metric(iteration, process.stdout)
            validations.append(metric)
            print(f"CHECKPOINT {iteration} validation_loss={metric.loss:.3f}", flush=True)
        selected = min(validations, key=lambda value: (value.loss, value.iteration))

        selected_dir = adapter_root / "selected"
        selected_dir.mkdir()
        shutil.copy2(
            source_adapter / f"{selected.iteration:07d}_adapters.safetensors",
            selected_dir / "adapters.safetensors",
        )
        shutil.copy2(source_adapter / "adapter_config.json", selected_dir / "adapter_config.json")
        record["checkpoint_validation"] = [asdict(value) for value in validations]
        record["selected_adapter"] = _adapter_evidence(selected_dir, selected)
        record["state"] = "executable_evaluation_running"
        _write(run_dir, record)

        cases = _evaluate_adapter(suite, selected_dir)
        solved = sum(bool(case["solved"]) for case in cases)
        improved = solved > int(config["promotion_gate"]["must_exceed"])
        record["executable_evaluation"] = {
            "registered": len(cases),
            "solved": solved,
            "improved_over_untouched": improved,
            "cases": cases,
        }
        record["state"] = "recovered_positive" if improved else "recovered_negative"
        record["wall_seconds"] = round(time.monotonic() - started, 6)
        _write(run_dir, record)
    except Exception as exc:
        record.update(
            state="failed",
            wall_seconds=round(time.monotonic() - started, 6),
            error={"type": type(exc).__name__, "message": str(exc)},
        )
        _write(run_dir, record)
        print(json.dumps(_summary(record, run_dir), indent=2, sort_keys=True))
        return 2

    print(json.dumps(_summary(record, run_dir), indent=2, sort_keys=True))
    return 0


def _summary(record: dict[str, object], directory: Path) -> dict[str, object]:
    selected = record.get("selected_adapter") or {}
    executable = record.get("executable_evaluation") or {}
    return {
        "artifact": str(directory),
        "run_id": record["run_id"],
        "state": record["state"],
        "source_run_id": record["source_run_id"],
        "original_800_step_treatment_complete": False,
        "available_checkpoint_iterations": record["available_checkpoint_iterations"],
        "selected_iteration": selected.get("iteration"),
        "validation_loss": selected.get("validation_loss"),
        "executable_solved": executable.get("solved"),
        "executable_registered": executable.get("registered"),
        "sealed_examples_loaded": record["sealed_examples_loaded"],
        "wall_seconds": record.get("wall_seconds"),
        "error": record.get("error"),
    }


if __name__ == "__main__":
    raise SystemExit(main())
