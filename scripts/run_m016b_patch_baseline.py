#!/usr/bin/env python3
"""Measure untouched Qwen on the M016b issue-to-diff executable gate."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import time

from localcode.patch_baseline import (
    build_patch_messages,
    evaluate_patch_prediction,
    observe_failing_tests,
)
from localcode.training_baseline import load_executable_suite


ROOT = Path(__file__).resolve().parents[1]
SUITE = ROOT / "benchmarks/training/m015_executable_dev_v1.json"
MODEL_PATH = ROOT / "models/qwen25-coder-1.5b-instruct-m015"
RUN_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{2,79}$")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    arguments = parser.parse_args()
    if Path(sys.prefix).resolve() != (ROOT / ".venv-mlx").resolve():
        raise SystemExit("M016b baseline must run with .venv-mlx/bin/python")
    if RUN_ID.fullmatch(arguments.run_id) is None:
        raise SystemExit("run ID must contain 3-80 lowercase safe characters")
    directory = ROOT / "runs/training" / arguments.run_id
    try:
        directory.mkdir(parents=True)
    except FileExistsError as exc:
        raise SystemExit("run directory already exists; use a fresh run ID") from exc

    suite = load_executable_suite(SUITE, ROOT)
    record: dict[str, object] = {
        "schema_version": 1,
        "run_id": arguments.run_id,
        "state": "running",
        "treatment": "untouched_issue_failure_file_to_unified_diff",
        "model_id": "Qwen/Qwen2.5-Coder-1.5B-Instruct",
        "model_revision": "cc932d8a05bf5a3dcd700f50584714d17fc4d03a",
        "adapter_path": None,
        "suite_id": suite.suite_id,
        "registered": len(suite.cases),
        "solved": None,
        "cases": [],
        "sealed_examples_loaded": 0,
        "wall_seconds": None,
        "peak_memory_gb": None,
        "error": None,
    }
    _write(directory, record)
    started = time.monotonic()
    mlx_core = None
    try:
        import mlx.core as mlx_core
        from mlx_lm import generate, load
        from mlx_lm.sample_utils import make_sampler

        mlx_core.reset_peak_memory()
        model, tokenizer = load(str(MODEL_PATH), lazy=False)
        sampler = make_sampler(temp=0.0)
        cases = []
        for index, case in enumerate(suite.cases, 1):
            case_started = time.monotonic()
            failure = observe_failing_tests(case)
            messages = build_patch_messages(case, failure)
            prompt = tokenizer.apply_chat_template(
                list(messages), add_generation_prompt=True, tokenize=False
            )
            response = generate(
                model,
                tokenizer,
                prompt=prompt,
                max_tokens=suite.max_output_tokens,
                sampler=sampler,
                verbose=False,
            )
            result = evaluate_patch_prediction(
                case, response, max_prediction_bytes=suite.max_prediction_bytes
            )
            case_record = {
                **result.to_dict(),
                "failure_observation_sha256": hashlib.sha256(failure.content.encode()).hexdigest(),
                "prompt_tokens": len(tokenizer.encode(prompt)),
                "generated_tokens": len(tokenizer.encode(response)),
                "raw_response": response,
                "wall_seconds": round(time.monotonic() - case_started, 6),
            }
            cases.append(case_record)
            record["cases"] = cases
            _write(directory, record)
            print(
                f"CASE {index}/{len(suite.cases)} {case.case_id} status={result.status} "
                f"test_exit={result.test_exit_code} generated_tokens={case_record['generated_tokens']}",
                flush=True,
            )
    except Exception as exc:
        record.update(
            state="failed",
            wall_seconds=round(time.monotonic() - started, 6),
            peak_memory_gb=None if mlx_core is None else round(mlx_core.get_peak_memory() / 1e9, 6),
            error={"type": type(exc).__name__, "message": str(exc)},
        )
        _write(directory, record)
        print(json.dumps(_summary(record, directory), indent=2, sort_keys=True))
        return 2

    cases = record["cases"]
    solved = sum(bool(case["solved"]) for case in cases)
    operational_errors = sum(case["status"] == "evaluation_error" for case in cases)
    record.update(
        state="failed" if operational_errors else "measured",
        solved=solved,
        wall_seconds=round(time.monotonic() - started, 6),
        peak_memory_gb=round(mlx_core.get_peak_memory() / 1e9, 6),
        error=(None if not operational_errors else {
            "type": "evaluation_error", "message": f"{operational_errors} cases could not execute"
        }),
    )
    _write(directory, record)
    print(json.dumps(_summary(record, directory), indent=2, sort_keys=True))
    return 2 if operational_errors else 0


def _write(directory: Path, record: dict[str, object]) -> None:
    temporary = directory / "run.json.tmp"
    temporary.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(directory / "run.json")


def _summary(record: dict[str, object], directory: Path) -> dict[str, object]:
    return {
        "artifact": str(directory),
        "run_id": record["run_id"],
        "state": record["state"],
        "solved": record["solved"],
        "registered": record["registered"],
        "peak_memory_gb": record["peak_memory_gb"],
        "wall_seconds": record["wall_seconds"],
        "sealed_examples_loaded": record["sealed_examples_loaded"],
        "record_sha256": hashlib.sha256(
            json.dumps(record, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "error": record["error"],
    }


if __name__ == "__main__":
    raise SystemExit(main())
