#!/usr/bin/env python3
"""Measure untouched Qwen on the pinned executable Phase 4 development suite."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import time

from localcode.training_baseline import (
    ExecutableBaselineError,
    build_case_messages,
    evaluate_prediction,
    load_executable_suite,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "benchmarks/training/m015_executable_dev_v1.json"
MODEL_CONFIG = ROOT / "benchmarks/training/m015_baseline_v1.json"
MODEL_MANIFEST = ROOT / "models/m015-local-model.json"
MODEL_PATH = ROOT / "models/qwen25-coder-1.5b-instruct-m015"
RUN_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{2,79}$")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    arguments = parser.parse_args()
    if Path(sys.prefix).resolve() != (ROOT / ".venv-mlx").resolve():
        raise SystemExit("M015 executable baseline must run with .venv-mlx/bin/python")
    if RUN_ID.fullmatch(arguments.run_id) is None:
        raise SystemExit("run ID must contain 3-80 lowercase safe characters")
    run_directory = ROOT / "runs/training" / arguments.run_id
    try:
        run_directory.mkdir(parents=True)
    except FileExistsError as exc:
        raise SystemExit(f"run directory already exists: {run_directory}") from exc

    try:
        suite = load_executable_suite(arguments.manifest, ROOT)
        model_config = json.loads(MODEL_CONFIG.read_text(encoding="utf-8"))
        local_model = json.loads(MODEL_MANIFEST.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ExecutableBaselineError) as exc:
        return _record_setup_error(run_directory, arguments.run_id, exc)
    if local_model.get("resolved_revision") != model_config["model"]["revision"]:
        return _record_setup_error(run_directory, arguments.run_id, RuntimeError("local model revision mismatch"))

    record: dict[str, object] = {
        "schema_version": 1,
        "run_id": arguments.run_id,
        "state": "running",
        "suite_id": suite.suite_id,
        "suite_purpose": suite.purpose,
        "model_id": model_config["model"]["model_id"],
        "model_revision": model_config["model"]["revision"],
        "model_role": "untouched_instruction_tuned_base",
        "adapter_path": None,
        "temperature": suite.temperature,
        "max_output_tokens": suite.max_output_tokens,
        "sealed_examples_loaded": 0,
        "cases": [],
        "solved": None,
        "registered": len(suite.cases),
        "peak_memory_gb": None,
        "wall_seconds": None,
        "error": None,
    }
    _write_record(run_directory, record)
    started = time.monotonic()
    mlx_core = None
    try:
        import mlx.core as mlx_core
        from mlx_lm import generate, load
        from mlx_lm.sample_utils import make_sampler

        mlx_core.reset_peak_memory()
        model, tokenizer = load(str(MODEL_PATH), lazy=False)
        sampler = make_sampler(temp=0.0)
        cases: list[dict[str, object]] = []
        for index, case in enumerate(suite.cases, 1):
            case_started = time.monotonic()
            messages = list(build_case_messages(case))
            prompt = tokenizer.apply_chat_template(
                messages,
                add_generation_prompt=True,
                tokenize=False,
            )
            response = generate(
                model,
                tokenizer,
                prompt=prompt,
                max_tokens=suite.max_output_tokens,
                sampler=sampler,
                verbose=False,
            )
            result = evaluate_prediction(
                case,
                response,
                max_prediction_bytes=suite.max_prediction_bytes,
            )
            case_record = {
                **result.to_dict(),
                "prompt_tokens": len(tokenizer.encode(prompt)),
                "generated_tokens": len(tokenizer.encode(response)),
                "raw_response": response,
                "wall_seconds": round(time.monotonic() - case_started, 6),
            }
            cases.append(case_record)
            print(
                f"CASE {index}/{len(suite.cases)} {case.case_id} "
                f"status={result.status} test_exit={result.test_exit_code} "
                f"generated_tokens={case_record['generated_tokens']}",
                flush=True,
            )
            record["cases"] = cases
            _write_record(run_directory, record)
    except Exception as exc:  # runtime/model failures must remain diagnosable
        record.update(
            state="failed",
            wall_seconds=round(time.monotonic() - started, 6),
            peak_memory_gb=(
                None if mlx_core is None else round(mlx_core.get_peak_memory() / 1e9, 6)
            ),
            error={"type": type(exc).__name__, "message": str(exc)},
        )
        _write_record(run_directory, record)
        print(json.dumps(_summary(record, run_directory), indent=2, sort_keys=True))
        return 2

    case_records = record["cases"]
    evaluation_errors = sum(case["status"] == "evaluation_error" for case in case_records)
    solved = sum(bool(case["solved"]) for case in case_records)
    record.update(
        state="failed" if evaluation_errors else "measured",
        solved=solved,
        wall_seconds=round(time.monotonic() - started, 6),
        peak_memory_gb=round(mlx_core.get_peak_memory() / 1e9, 6),
        error=(
            {"type": "evaluation_error", "message": f"{evaluation_errors} cases could not execute"}
            if evaluation_errors
            else None
        ),
    )
    _write_record(run_directory, record)
    print(json.dumps(_summary(record, run_directory), indent=2, sort_keys=True))
    return 2 if evaluation_errors else 0


def _record_setup_error(directory: Path, run_id: str, error: Exception) -> int:
    record = {
        "schema_version": 1,
        "run_id": run_id,
        "state": "setup_failed",
        "sealed_examples_loaded": 0,
        "error": {"type": type(error).__name__, "message": str(error)},
    }
    _write_record(directory, record)
    print(json.dumps(_summary(record, directory), indent=2, sort_keys=True))
    return 2


def _write_record(directory: Path, record: dict[str, object]) -> None:
    destination = directory / "run.json"
    temporary = directory / "run.json.tmp"
    temporary.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(destination)


def _summary(record: dict[str, object], directory: Path) -> dict[str, object]:
    return {
        "artifact": str(directory),
        "run_id": record["run_id"],
        "state": record["state"],
        "suite_id": record.get("suite_id"),
        "solved": record.get("solved"),
        "registered": record.get("registered"),
        "peak_memory_gb": record.get("peak_memory_gb"),
        "wall_seconds": record.get("wall_seconds"),
        "sealed_examples_loaded": record["sealed_examples_loaded"],
        "record_sha256": hashlib.sha256(
            json.dumps(record, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        "error": record.get("error"),
    }


if __name__ == "__main__":
    raise SystemExit(main())
