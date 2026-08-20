#!/usr/bin/env python3
"""Run M016 diagnostic, full LoRA training, validation selection, and dev evaluation."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
import time

from localcode.training_baseline import build_case_messages, evaluate_prediction, load_executable_suite
from localcode.training_run import (
    diagnostic_passed,
    parse_overfit_validation_metrics,
    parse_train_metrics,
    parse_validation_metric,
    select_validation_checkpoint,
)


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "benchmarks/training/m016_lora_v1.json"
MODEL_PATH = ROOT / "models/qwen25-coder-1.5b-instruct-m015"
MODEL_MANIFEST = ROOT / "models/m015-local-model.json"
VALIDATION_EVAL = ROOT / "data/processed/mlx-m015-validation-eval"
RUN_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{2,79}$")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--validate-only", action="store_true")
    arguments = parser.parse_args()
    if Path(sys.prefix).resolve() != (ROOT / ".venv-mlx").resolve():
        raise SystemExit("M016 training must run with .venv-mlx/bin/python")
    if RUN_ID.fullmatch(arguments.run_id) is None:
        raise SystemExit("run ID must contain 3-80 lowercase safe characters")
    if arguments.validate_only:
        try:
            config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            base_config = json.loads((ROOT / config["base_config"]).read_text(encoding="utf-8"))
            model_manifest = json.loads(MODEL_MANIFEST.read_text(encoding="utf-8"))
            load_executable_suite(ROOT / config["executable_suite"], ROOT)
            _verify_inputs(config, base_config, model_manifest)
        except Exception as exc:
            print(json.dumps({"status": "invalid", "error": str(exc)}, sort_keys=True))
            return 2
        print(json.dumps({
            "status": "m016_ready",
            "run_id_available": not (ROOT / "runs/training" / arguments.run_id).exists(),
            "baseline_solved": config["untouched_baseline"]["solved"],
            "train_examples": config["data"]["train_examples"],
            "validation_examples": config["data"]["validation_examples"],
            "sealed_examples_loaded": 0,
        }, indent=2, sort_keys=True))
        return 0
    run_dir = ROOT / "runs/training" / arguments.run_id
    adapter_root = ROOT / "adapters" / arguments.run_id
    try:
        run_dir.mkdir(parents=True)
        adapter_root.mkdir(parents=True)
    except FileExistsError as exc:
        raise SystemExit("run or adapter directory already exists; use a new run ID") from exc

    started = time.monotonic()
    try:
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        base_config = json.loads((ROOT / config["base_config"]).read_text(encoding="utf-8"))
        model_manifest = json.loads(MODEL_MANIFEST.read_text(encoding="utf-8"))
        suite = load_executable_suite(ROOT / config["executable_suite"], ROOT)
        _verify_inputs(config, base_config, model_manifest)
    except Exception as exc:
        return _fail(run_dir, arguments.run_id, "setup_failed", exc, started)

    record: dict[str, object] = {
        "schema_version": 1,
        "run_id": arguments.run_id,
        "state": "diagnostic_running",
        "experiment_id": config["experiment_id"],
        "model_id": base_config["model"]["model_id"],
        "model_revision": base_config["model"]["revision"],
        "data": config["data"],
        "sealed_examples_loaded": 0,
        "untouched_baseline": config["untouched_baseline"],
        "diagnostic": None,
        "full_training": None,
        "checkpoint_validation": [],
        "selected_adapter": None,
        "executable_evaluation": None,
        "wall_seconds": None,
        "error": None,
    }
    _write(run_dir, record)

    try:
        diagnostic_data = _prepare_diagnostic_data(config, arguments.run_id)
        diagnostic_adapter = adapter_root / "diagnostic"
        diagnostic_command = _training_command(
            config, diagnostic_data, diagnostic_adapter, config["diagnostic"]
        )
        diagnostic_process = _run(
            diagnostic_command, int(config["diagnostic"]["maximum_wall_seconds"])
        )
        diagnostic_metrics = parse_train_metrics(diagnostic_process.stdout)
        diagnostic_validation = parse_overfit_validation_metrics(diagnostic_process.stdout)
        diagnostic_ok = diagnostic_process.returncode == 0 and diagnostic_passed(
            diagnostic_metrics,
            diagnostic_validation,
            required_relative_improvement=float(
                config["diagnostic"]["minimum_relative_loss_improvement"]
            ),
            maximum_peak_memory_gb=float(config["shared"]["maximum_peak_memory_gb"]),
        )
        record["diagnostic"] = {
            "passed": diagnostic_ok,
            "command": diagnostic_command,
            "process_exit_code": diagnostic_process.returncode,
            "metrics": [asdict(metric) for metric in diagnostic_metrics],
            "same_row_validation_metrics": [asdict(metric) for metric in diagnostic_validation],
            "stdout": diagnostic_process.stdout,
            "stderr": diagnostic_process.stderr,
        }
        if not diagnostic_ok:
            raise RuntimeError("tiny overfit diagnostic did not meet its frozen loss and memory gate")
        record["state"] = "full_training_running"
        _write(run_dir, record)

        full_adapter = adapter_root / "full"
        full_command = _training_command(
            config, ROOT / config["data"]["directory"], full_adapter, config["full_training"]
        )
        full_process = _run(
            full_command, int(config["full_training"]["maximum_wall_seconds"])
        )
        full_metrics = parse_train_metrics(full_process.stdout)
        # Preserve streamed evidence even when MLX or Metal terminates before
        # the configured final checkpoint. Recovery must not depend on a
        # transient terminal transcript.
        record["full_training"] = {
            "command": full_command,
            "process_exit_code": full_process.returncode,
            "metrics": [asdict(metric) for metric in full_metrics],
            "stdout": full_process.stdout,
            "stderr": full_process.stderr,
        }
        _write(run_dir, record)
        if full_process.returncode != 0 or not full_metrics:
            raise RuntimeError("full LoRA process failed or produced no training metrics")
        if max(metric.peak_memory_gb for metric in full_metrics) > config["shared"]["maximum_peak_memory_gb"]:
            raise RuntimeError("full LoRA process exceeded the frozen peak-memory ceiling")
        record["state"] = "checkpoint_selection_running"
        _write(run_dir, record)

        validations = []
        for iteration in config["full_training"]["checkpoint_iterations"]:
            candidate = _candidate_adapter(full_adapter, adapter_root, int(iteration))
            process = _run(_validation_command(config, candidate), 600)
            if process.returncode != 0:
                raise RuntimeError(f"validation failed for checkpoint {iteration}")
            metric = parse_validation_metric(int(iteration), process.stdout)
            validations.append(metric)
            print(f"CHECKPOINT {iteration} validation_loss={metric.loss:.3f}", flush=True)
        selected = select_validation_checkpoint(validations)
        selected_dir = adapter_root / "selected"
        selected_dir.mkdir()
        source_checkpoint = full_adapter / f"{selected.iteration:07d}_adapters.safetensors"
        shutil.copy2(source_checkpoint, selected_dir / "adapters.safetensors")
        shutil.copy2(full_adapter / "adapter_config.json", selected_dir / "adapter_config.json")
        record["checkpoint_validation"] = [asdict(metric) for metric in validations]
        record["selected_adapter"] = _adapter_evidence(selected_dir, selected)
        record["state"] = "executable_evaluation_running"
        _write(run_dir, record)

        executable = _evaluate_adapter(suite, selected_dir)
        solved = sum(case["solved"] for case in executable)
        improved = solved > int(config["promotion_gate"]["must_exceed"])
        record["executable_evaluation"] = {
            "registered": len(executable),
            "solved": solved,
            "improved_over_untouched": improved,
            "cases": executable,
        }
        record["state"] = "completed_positive" if improved else "completed_negative"
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


def _verify_inputs(config, base_config, model_manifest) -> None:
    if config["schema_version"] != 1 or config["data"]["sealed_examples_loaded"] != 0:
        raise ValueError("invalid M016 config or sealed-data boundary")
    if model_manifest["resolved_revision"] != base_config["model"]["revision"]:
        raise ValueError("local model revision mismatch")
    data_dir = ROOT / config["data"]["directory"]
    for split in ("train", "valid"):
        path = data_dir / f"{split}.jsonl"
        expected = config["data"][f"{'validation' if split == 'valid' else split}_sha256"]
        if _sha(path) != expected:
            raise ValueError(f"{split} data hash mismatch")
    baseline_path = ROOT / "runs/training" / config["untouched_baseline"]["run_id"] / "run.json"
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    digest = hashlib.sha256(
        json.dumps(baseline, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if digest != config["untouched_baseline"]["record_sha256"]:
        raise ValueError("untouched executable baseline hash mismatch")
    if baseline["state"] != "measured" or baseline["solved"] != config["untouched_baseline"]["solved"]:
        raise ValueError("untouched executable baseline result mismatch")


def _prepare_diagnostic_data(config, run_id: str) -> Path:
    source = ROOT / config["data"]["directory"] / "train.jsonl"
    count = int(config["diagnostic"]["train_prefix_examples"])
    lines = source.read_text(encoding="utf-8").splitlines(keepends=True)[:count]
    content = "".join(lines)
    if hashlib.sha256(content.encode("utf-8")).hexdigest() != config["diagnostic"]["prefix_sha256"]:
        raise ValueError("diagnostic prefix hash mismatch")
    destination = ROOT / "data/processed" / f"{run_id}-diagnostic"
    destination.mkdir()
    for name in ("train.jsonl", "valid.jsonl"):
        (destination / name).write_text(content, encoding="utf-8")
    return destination


def _training_command(config, data: Path, adapter: Path, stage) -> list[str]:
    shared = config["shared"]
    return [
        str(ROOT / ".venv-mlx/bin/mlx_lm.lora"), "--model", str(MODEL_PATH),
        "--data", str(data), "--train", "--fine-tune-type", shared["fine_tune_type"],
        "--optimizer", shared["optimizer"], "--mask-prompt", "--num-layers", str(shared["num_layers"]),
        "--batch-size", str(shared["batch_size"]), "--learning-rate", str(shared["learning_rate"]),
        "--max-seq-length", str(shared["max_sequence_length"]), "--seed", str(shared["seed"]),
        "--iters", str(stage["iterations"]),
        "--val-batches", str(stage.get("validation_batches", stage.get("validation_batches_during_training"))),
        "--steps-per-report", str(stage["steps_per_report"]),
        "--steps-per-eval", str(stage["steps_per_evaluation"]),
        "--save-every", str(stage["save_every"]), "--grad-checkpoint", "--adapter-path", str(adapter),
    ]


def _candidate_adapter(full: Path, root: Path, iteration: int) -> Path:
    checkpoint = full / f"{iteration:07d}_adapters.safetensors"
    if not checkpoint.is_file():
        raise FileNotFoundError(f"missing checkpoint {checkpoint}")
    candidate = root / "checkpoint-eval" / f"{iteration:07d}"
    candidate.mkdir(parents=True)
    shutil.copy2(checkpoint, candidate / "adapters.safetensors")
    shutil.copy2(full / "adapter_config.json", candidate / "adapter_config.json")
    return candidate


def _validation_command(config, adapter: Path) -> list[str]:
    shared = config["shared"]
    return [
        str(ROOT / ".venv-mlx/bin/mlx_lm.lora"), "--model", str(MODEL_PATH),
        "--data", str(VALIDATION_EVAL), "--test", "--test-batches", "-1",
        "--batch-size", str(shared["batch_size"]), "--max-seq-length", str(shared["max_sequence_length"]),
        "--seed", str(shared["seed"]), "--adapter-path", str(adapter),
    ]


def _evaluate_adapter(suite, adapter: Path) -> list[dict[str, object]]:
    from mlx_lm import generate, load
    from mlx_lm.sample_utils import make_sampler

    model, tokenizer = load(str(MODEL_PATH), adapter_path=str(adapter), lazy=False)
    sampler = make_sampler(temp=0.0)
    results = []
    for case in suite.cases:
        prompt = tokenizer.apply_chat_template(list(build_case_messages(case)), add_generation_prompt=True, tokenize=False)
        response = generate(model, tokenizer, prompt=prompt, max_tokens=suite.max_output_tokens, sampler=sampler)
        result = evaluate_prediction(case, response, max_prediction_bytes=suite.max_prediction_bytes)
        results.append({**result.to_dict(), "raw_response": response})
        print(f"EXECUTABLE {case.case_id} status={result.status}", flush=True)
    return results


def _adapter_evidence(path: Path, selected) -> dict[str, object]:
    adapter = path / "adapters.safetensors"
    return {
        "iteration": selected.iteration,
        "validation_loss": selected.loss,
        "validation_perplexity": selected.perplexity,
        "path": str(path.relative_to(ROOT)),
        "bytes": adapter.stat().st_size,
        "sha256": _sha(adapter),
    }


def _run(command: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    process = subprocess.Popen(
        command,
        cwd=ROOT,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )
    if process.stdout is None:
        raise RuntimeError("could not capture training process output")
    timed_out = False

    def terminate() -> None:
        nonlocal timed_out
        timed_out = True
        try:
            os.killpg(process.pid, 15)
        except ProcessLookupError:
            pass

    timer = threading.Timer(timeout, terminate)
    timer.start()
    chunks = []
    try:
        for line in process.stdout:
            chunks.append(line)
            print(line, end="", flush=True)
        return_code = process.wait()
    finally:
        timer.cancel()
        process.stdout.close()
    if timed_out:
        return_code = 124
    return subprocess.CompletedProcess(command, return_code, "".join(chunks), "")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(directory: Path, record: dict[str, object]) -> None:
    temporary = directory / "run.json.tmp"
    temporary.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(directory / "run.json")


def _fail(directory: Path, run_id: str, state: str, error: Exception, started: float) -> int:
    record = {"schema_version": 1, "run_id": run_id, "state": state, "sealed_examples_loaded": 0,
              "wall_seconds": round(time.monotonic() - started, 6),
              "error": {"type": type(error).__name__, "message": str(error)}}
    _write(directory, record)
    print(json.dumps(_summary(record, directory), indent=2, sort_keys=True))
    return 2


def _summary(record: dict[str, object], directory: Path) -> dict[str, object]:
    executable = record.get("executable_evaluation") or {}
    selected = record.get("selected_adapter") or {}
    return {
        "artifact": str(directory), "run_id": record["run_id"], "state": record["state"],
        "selected_iteration": selected.get("iteration"), "validation_loss": selected.get("validation_loss"),
        "executable_solved": executable.get("solved"), "executable_registered": executable.get("registered"),
        "sealed_examples_loaded": record["sealed_examples_loaded"], "wall_seconds": record.get("wall_seconds"),
        "error": record.get("error"),
    }


if __name__ == "__main__":
    raise SystemExit(main())
