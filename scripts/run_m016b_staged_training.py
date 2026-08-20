#!/usr/bin/env python3
"""Continue M016b in bounded 100-update MLX processes, then select and test."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
import time

from localcode.training_run import parse_train_metrics, parse_validation_metric, select_validation_checkpoint
from run_m016b_training import (
    ROOT,
    _adapter_evidence,
    _candidate_adapter,
    _evaluate_adapter,
    _load_and_verify,
    _prepare_validation_data,
    _run,
    _training_command,
    _validation_command,
    _write,
)


STAGED_CONFIG = ROOT / "benchmarks/training/m016b_lora_v3.json"
RUN_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{2,79}$")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    arguments = parser.parse_args()
    if Path(sys.prefix).resolve() != (ROOT / ".venv-mlx").resolve():
        raise SystemExit("M016b staged training must run with .venv-mlx/bin/python")
    if RUN_ID.fullmatch(arguments.run_id) is None:
        raise SystemExit("run ID must contain 3-80 lowercase safe characters")

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
        "experiment_id": "m016b-qwen25-coder-executable-lora-v3-staged",
        "source_checkpoint": None,
        "optimizer_state_between_stages": "reset",
        "stages": [],
        "checkpoint_validation": [],
        "selected_adapter": None,
        "executable_evaluation": None,
        "sealed_examples_loaded": 0,
        "wall_seconds": None,
        "error": None,
    }
    _write(run_dir, record)
    try:
        treatment, _, suite = _load_and_verify()
        staged = json.loads(STAGED_CONFIG.read_text(encoding="utf-8"))
        _verify_staged(staged, treatment)
        source = ROOT / staged["source_checkpoint"]["path"]
        canonical = adapter_root / "full"
        canonical.mkdir()
        shutil.copy2(source, canonical / "0000100_adapters.safetensors")
        source_config = source.parent / "adapter_config.json"
        shutil.copy2(source_config, canonical / "adapter_config.json")
        record["source_checkpoint"] = staged["source_checkpoint"]
        record["state"] = "staged_training_running"
        _write(run_dir, record)

        previous = source
        stage_spec = {
            "iterations": staged["stage_policy"]["iterations_per_stage"],
            "validation_batches_during_training": 25,
            "steps_per_report": 20,
            "steps_per_evaluation": 100,
            "save_every": 100,
        }
        for cumulative in staged["stage_policy"]["cumulative_checkpoints"][1:]:
            stage_dir = adapter_root / "stages" / f"{cumulative:07d}"
            command = _training_command(
                treatment, ROOT / treatment["data"]["directory"], stage_dir, stage_spec
            )
            command.extend(["--resume-adapter-file", str(previous)])
            process = _run(command, int(staged["stage_policy"]["maximum_wall_seconds_per_stage"]))
            metrics = parse_train_metrics(process.stdout)
            produced = stage_dir / "0000100_adapters.safetensors"
            stage_record = {
                "cumulative_iteration": cumulative,
                "process_exit_code": process.returncode,
                "metrics": [asdict(value) for value in metrics],
                "checkpoint_produced": produced.is_file(),
                "stdout": process.stdout,
            }
            record["stages"].append(stage_record)
            _write(run_dir, record)
            if process.returncode != 0 or not metrics or not produced.is_file():
                raise RuntimeError(f"staged training failed before cumulative checkpoint {cumulative}")
            destination = canonical / f"{cumulative:07d}_adapters.safetensors"
            shutil.copy2(produced, destination)
            previous = destination
            print(f"STAGE cumulative={cumulative} checkpoint={destination}", flush=True)

        record["state"] = "checkpoint_validation_running"
        _write(run_dir, record)
        validation_dir = _prepare_validation_data(treatment, arguments.run_id)
        validations = []
        for iteration in staged["stage_policy"]["cumulative_checkpoints"]:
            candidate = _candidate_adapter(canonical, adapter_root, int(iteration))
            process = _run(_validation_command(treatment, validation_dir, candidate), 900)
            if process.returncode != 0:
                raise RuntimeError(f"validation failed for cumulative checkpoint {iteration}")
            metric = parse_validation_metric(int(iteration), process.stdout)
            validations.append(metric)
            print(f"CHECKPOINT {iteration} validation_loss={metric.loss:.3f}", flush=True)
        selected = select_validation_checkpoint(validations)
        selected_dir = adapter_root / "selected"
        selected_dir.mkdir()
        shutil.copy2(canonical / f"{selected.iteration:07d}_adapters.safetensors", selected_dir / "adapters.safetensors")
        shutil.copy2(canonical / "adapter_config.json", selected_dir / "adapter_config.json")
        record["checkpoint_validation"] = [asdict(value) for value in validations]
        record["selected_adapter"] = _adapter_evidence(selected_dir, selected)
        record["state"] = "executable_evaluation_running"
        _write(run_dir, record)

        cases = _evaluate_adapter(suite, selected_dir)
        solved = sum(bool(case["solved"]) for case in cases)
        improved = solved > int(treatment["promotion_gate"]["must_exceed"])
        record["executable_evaluation"] = {
            "registered": len(cases), "solved": solved,
            "improved_over_untouched": improved, "cases": cases,
        }
        record["state"] = "completed_positive" if improved else "completed_negative"
        record["wall_seconds"] = round(time.monotonic() - started, 6)
        _write(run_dir, record)
    except Exception as exc:
        record.update(
            state="failed", wall_seconds=round(time.monotonic() - started, 6),
            error={"type": type(exc).__name__, "message": str(exc)},
        )
        _write(run_dir, record)
        print(json.dumps(_summary(record, run_dir), indent=2, sort_keys=True))
        return 2

    print(json.dumps(_summary(record, run_dir), indent=2, sort_keys=True))
    return 0


def _verify_staged(staged, treatment) -> None:
    if staged["schema_version"] != 1 or staged["sealed_examples_loaded"] != 0:
        raise ValueError("invalid staged config or sealed boundary")
    expected = list(range(100, 801, 100))
    if staged["stage_policy"]["cumulative_checkpoints"] != expected:
        raise ValueError("staged checkpoints must be the frozen 100-800 sequence")
    if staged["stage_policy"]["optimizer_state_between_stages"] != "reset":
        raise ValueError("optimizer reset must be explicit")
    source = ROOT / staged["source_checkpoint"]["path"]
    if source.stat().st_size != staged["source_checkpoint"]["bytes"]:
        raise ValueError("source checkpoint byte count mismatch")
    if hashlib.sha256(source.read_bytes()).hexdigest() != staged["source_checkpoint"]["sha256"]:
        raise ValueError("source checkpoint hash mismatch")
    if treatment["data"]["sealed_examples_loaded"] != 0:
        raise ValueError("base treatment violates sealed boundary")


def _summary(record: dict[str, object], directory: Path) -> dict[str, object]:
    selected = record.get("selected_adapter") or {}
    executable = record.get("executable_evaluation") or {}
    return {
        "artifact": str(directory), "run_id": record["run_id"], "state": record["state"],
        "stages_completed": sum(bool(item["checkpoint_produced"]) for item in record["stages"]),
        "selected_iteration": selected.get("iteration"), "validation_loss": selected.get("validation_loss"),
        "executable_solved": executable.get("solved"), "executable_registered": executable.get("registered"),
        "sealed_examples_loaded": record["sealed_examples_loaded"], "wall_seconds": record["wall_seconds"],
        "error": record["error"],
    }


if __name__ == "__main__":
    raise SystemExit(main())
