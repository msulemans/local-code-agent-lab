#!/usr/bin/env python3
"""Train, select, and executable-gate the M016b repair-diff LoRA."""

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

from localcode.patch_baseline import (
    build_patch_messages,
    evaluate_patch_prediction,
    observe_failing_tests,
)
from localcode.training_baseline import load_executable_suite
from localcode.training_run import (
    diagnostic_passed,
    parse_overfit_validation_metrics,
    parse_train_metrics,
    parse_validation_metric,
    select_validation_checkpoint,
)


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "benchmarks/training/m016b_lora_v2.json"
MODEL_PATH = ROOT / "models/qwen25-coder-1.5b-instruct-m015"
MODEL_MANIFEST = ROOT / "models/m015-local-model.json"
RUN_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{2,79}$")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--validate-only", action="store_true")
    arguments = parser.parse_args()
    if Path(sys.prefix).resolve() != (ROOT / ".venv-mlx").resolve():
        raise SystemExit("M016b training must run with .venv-mlx/bin/python")
    if RUN_ID.fullmatch(arguments.run_id) is None:
        raise SystemExit("run ID must contain 3-80 lowercase safe characters")

    try:
        config, base, suite = _load_and_verify()
    except Exception as exc:
        print(json.dumps({"status": "invalid", "error": str(exc)}, sort_keys=True))
        return 2
    if arguments.validate_only:
        print(json.dumps({
            "status": "m016b_ready",
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
    record: dict[str, object] = {
        "schema_version": 1,
        "run_id": arguments.run_id,
        "state": "diagnostic_running",
        "experiment_id": config["experiment_id"],
        "model_id": base["model"]["model_id"],
        "model_revision": base["model"]["revision"],
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
        process = _run(
            _training_command(config, diagnostic_data, diagnostic_adapter, config["diagnostic"]),
            int(config["diagnostic"]["maximum_wall_seconds"]),
        )
        metrics = parse_train_metrics(process.stdout)
        validation = parse_overfit_validation_metrics(process.stdout)
        passed = process.returncode == 0 and diagnostic_passed(
            metrics,
            validation,
            required_relative_improvement=float(config["diagnostic"]["minimum_relative_loss_improvement"]),
            maximum_peak_memory_gb=float(config["shared"]["maximum_peak_memory_gb"]),
        )
        record["diagnostic"] = {
            "passed": passed,
            "process_exit_code": process.returncode,
            "metrics": [asdict(value) for value in metrics],
            "same_row_validation_metrics": [asdict(value) for value in validation],
            "stdout": process.stdout,
        }
        if not passed:
            raise RuntimeError("tiny overfit diagnostic did not meet its frozen loss and memory gate")
        record["state"] = "full_training_running"
        _write(run_dir, record)

        full_adapter = adapter_root / "full"
        process = _run(
            _training_command(config, ROOT / config["data"]["directory"], full_adapter, config["full_training"]),
            int(config["full_training"]["maximum_wall_seconds"]),
        )
        metrics = parse_train_metrics(process.stdout)
        record["full_training"] = {
            "process_exit_code": process.returncode,
            "metrics": [asdict(value) for value in metrics],
            "stdout": process.stdout,
        }
        _write(run_dir, record)
        if process.returncode != 0 or not metrics:
            raise RuntimeError("full LoRA process failed or produced no training metrics")
        if max(value.peak_memory_gb for value in metrics) > config["shared"]["maximum_peak_memory_gb"]:
            raise RuntimeError("full LoRA process exceeded the frozen peak-memory ceiling")

        record["state"] = "checkpoint_selection_running"
        _write(run_dir, record)
        validation_dir = _prepare_validation_data(config, arguments.run_id)
        validations = []
        for iteration in config["full_training"]["checkpoint_iterations"]:
            candidate = _candidate_adapter(full_adapter, adapter_root, int(iteration))
            process = _run(_validation_command(config, validation_dir, candidate), 900)
            if process.returncode != 0:
                raise RuntimeError(f"validation failed for checkpoint {iteration}")
            metric = parse_validation_metric(int(iteration), process.stdout)
            validations.append(metric)
            print(f"CHECKPOINT {iteration} validation_loss={metric.loss:.3f}", flush=True)
        selected = select_validation_checkpoint(validations)
        selected_dir = adapter_root / "selected"
        selected_dir.mkdir()
        shutil.copy2(full_adapter / f"{selected.iteration:07d}_adapters.safetensors", selected_dir / "adapters.safetensors")
        shutil.copy2(full_adapter / "adapter_config.json", selected_dir / "adapter_config.json")
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


def _load_and_verify():
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    base = json.loads((ROOT / config["base_config"]).read_text(encoding="utf-8"))
    evidence = json.loads((ROOT / config["data_evidence"]).read_text(encoding="utf-8"))
    model = json.loads(MODEL_MANIFEST.read_text(encoding="utf-8"))
    suite = load_executable_suite(ROOT / config["executable_suite"], ROOT)
    if config["schema_version"] != 1 or config["data"]["sealed_examples_loaded"] != 0:
        raise ValueError("invalid M016b config or sealed-data boundary")
    if evidence["sealed_examples_loaded_for_training"] != 0:
        raise ValueError("data evidence violates the sealed boundary")
    if model["resolved_revision"] != base["model"]["revision"]:
        raise ValueError("local model revision mismatch")
    data_dir = ROOT / config["data"]["directory"]
    for split in ("train", "valid"):
        path = data_dir / f"{split}.jsonl"
        count_key = "validation_examples" if split == "valid" else "train_examples"
        hash_key = "validation_sha256" if split == "valid" else "train_sha256"
        if sum(1 for _ in path.open(encoding="utf-8")) != config["data"][count_key]:
            raise ValueError(f"{split} data count mismatch")
        if _sha(path) != config["data"][hash_key]:
            raise ValueError(f"{split} data hash mismatch")
    baseline = json.loads(
        (ROOT / "runs/training" / config["untouched_baseline"]["run_id"] / "run.json").read_text(encoding="utf-8")
    )
    digest = hashlib.sha256(json.dumps(baseline, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if digest != config["untouched_baseline"]["record_sha256"]:
        raise ValueError("untouched patch baseline hash mismatch")
    if baseline["state"] != "measured" or baseline["solved"] != config["untouched_baseline"]["solved"]:
        raise ValueError("untouched patch baseline result mismatch")
    return config, base, suite


def _prepare_diagnostic_data(config, run_id: str) -> Path:
    source = ROOT / config["data"]["directory"] / "train.jsonl"
    content = "".join(source.read_text(encoding="utf-8").splitlines(keepends=True)[: config["diagnostic"]["train_prefix_examples"]])
    if hashlib.sha256(content.encode()).hexdigest() != config["diagnostic"]["prefix_sha256"]:
        raise ValueError("diagnostic prefix hash mismatch")
    destination = ROOT / "data/processed" / f"{run_id}-diagnostic"
    destination.mkdir()
    for name in ("train.jsonl", "valid.jsonl"):
        (destination / name).write_text(content, encoding="utf-8")
    return destination


def _prepare_validation_data(config, run_id: str) -> Path:
    source = ROOT / config["data"]["directory"] / "valid.jsonl"
    destination = ROOT / "data/processed" / f"{run_id}-validation"
    destination.mkdir()
    shutil.copy2(source, destination / "test.jsonl")
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


def _validation_command(config, data: Path, adapter: Path) -> list[str]:
    shared = config["shared"]
    return [
        str(ROOT / ".venv-mlx/bin/mlx_lm.lora"), "--model", str(MODEL_PATH),
        "--data", str(data), "--test", "--test-batches", "-1",
        "--batch-size", str(shared["batch_size"]), "--max-seq-length", str(shared["max_sequence_length"]),
        "--seed", str(shared["seed"]), "--adapter-path", str(adapter),
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


def _evaluate_adapter(suite, adapter: Path) -> list[dict[str, object]]:
    from mlx_lm import generate, load
    from mlx_lm.sample_utils import make_sampler

    model, tokenizer = load(str(MODEL_PATH), adapter_path=str(adapter), lazy=False)
    sampler = make_sampler(temp=0.0)
    results = []
    for case in suite.cases:
        failure = observe_failing_tests(case)
        prompt = tokenizer.apply_chat_template(
            list(build_patch_messages(case, failure)), add_generation_prompt=True, tokenize=False
        )
        response = generate(model, tokenizer, prompt=prompt, max_tokens=suite.max_output_tokens, sampler=sampler, verbose=False)
        result = evaluate_patch_prediction(case, response, max_prediction_bytes=suite.max_prediction_bytes)
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
        command, cwd=ROOT, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, start_new_session=True,
    )
    if process.stdout is None:
        raise RuntimeError("could not capture training output")
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
    lines = []
    try:
        for line in process.stdout:
            lines.append(line)
            print(line, end="", flush=True)
        return_code = process.wait()
    finally:
        timer.cancel()
        process.stdout.close()
    return subprocess.CompletedProcess(command, 124 if timed_out else return_code, "".join(lines), "")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(directory: Path, record: dict[str, object]) -> None:
    temporary = directory / "run.json.tmp"
    temporary.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(directory / "run.json")


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
