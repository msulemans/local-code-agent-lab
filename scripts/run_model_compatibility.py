#!/usr/bin/env python3
"""Run the frozen Milestone 004 compatibility pack without executing tools."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import statistics
import subprocess
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from localcode.compatibility import CompatibilityError, OllamaClient, schema_map, score_prompt  # noqa: E402


RUN_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{2,79}$")
GIB = 1024**3
EXPERIMENT_MANIFESTS = {
    "base": ROOT / "configs/model_candidates.json",
    "extension-v1": ROOT / "configs/model_candidate_extension_v1.json",
}
RUNNABLE_CANDIDATE_STATUSES = {
    "downloaded_verified_not_run",
    "downloaded_verified_run_incomplete",
}


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    values = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    if any(not isinstance(value, dict) for value in values):
        raise ValueError(f"{path} must contain JSON objects")
    return values


def write_json(path: Path, value: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def candidate_run_error(candidate: dict[str, Any], run_id: str) -> str | None:
    """Return a preflight error without contacting Ollama."""
    if candidate.get("status") not in RUNNABLE_CANDIDATE_STATUSES:
        return "candidate must be downloaded, verified, and eligible to run"
    prior_runs = candidate.get("compatibility_runs", [])
    if not isinstance(prior_runs, list):
        return "candidate 1 compatibility_runs must be a list"
    if any(isinstance(run, dict) and run.get("run_id") == run_id for run in prior_runs):
        return f"run ID is already registered: {run_id}"
    return None


def read_swap_used_bytes() -> int | None:
    try:
        completed = subprocess.run(
            ["/usr/sbin/sysctl", "-n", "vm.swapusage"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return None
    match = re.search(r"used\s*=\s*([0-9.]+)([KMG])", completed.stdout)
    if match is None:
        return None
    multiplier = {"K": 1024, "M": 1024**2, "G": 1024**3}[match.group(2)]
    return round(float(match.group(1)) * multiplier)


def read_memory_free_percent() -> int | None:
    try:
        completed = subprocess.run(
            ["/usr/bin/memory_pressure", "-Q"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return None
    match = re.search(r"System-wide memory free percentage:\s*([0-9]+)%", completed.stdout)
    return None if match is None else int(match.group(1))


def snapshot_sources(run_directory: Path, paths: list[Path]) -> list[dict[str, Any]]:
    snapshot_root = run_directory / "source_snapshot"
    records: list[dict[str, Any]] = []
    for path in paths:
        relative = path.relative_to(ROOT)
        destination = snapshot_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
        content = path.read_bytes()
        records.append({"path": relative.as_posix(), "bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()})
    write_json(snapshot_root / "files.json", records)
    return records


def model_sample(client: OllamaClient, model: str) -> dict[str, Any] | None:
    for item in client.running_models():
        if item.get("name") == model or item.get("model") == model:
            return {
                "name": item.get("name"),
                "size_bytes": item.get("size"),
                "size_vram_bytes": item.get("size_vram"),
                "context_length": item.get("context_length"),
                "digest": item.get("digest"),
            }
    return None


def ratio(value: str) -> tuple[int, int]:
    numerator, denominator = value.split("/", 1)
    return int(numerator), int(denominator)


def probe_user_message(repetitions: int) -> str:
    return (
        "Read the following inert context. Do not analyze or quote it.\n<CONTEXT>\n"
        + ("x " * repetitions)
        + "\n</CONTEXT>\nReply by writing the integers 1 through 128, separated by single spaces."
    )


class RunRecorder:
    def __init__(self, run_directory: Path) -> None:
        self.run_directory = run_directory
        self.responses = run_directory / "responses"
        self.responses.mkdir()
        self.calls: list[dict[str, Any]] = []
        self.memory_samples: list[dict[str, Any]] = []
        self.consecutive_failures = 0

    def record_success(self, call_id: str, request: dict[str, Any], result: Any) -> dict[str, Any]:
        (self.responses / f"{call_id}.request.json").write_text(
            json.dumps(request, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        with (self.responses / f"{call_id}.stream.jsonl").open("w", encoding="utf-8") as stream:
            for chunk in result.chunks:
                stream.write(json.dumps(chunk, sort_keys=True, separators=(",", ":")) + "\n")
        record = {"id": call_id, "ok": True, **result.summary_dict()}
        self.calls.append(record)
        self.consecutive_failures = 0
        write_json(self.run_directory / "calls.json", self.calls)
        return record

    def record_failure(self, call_id: str, request: dict[str, Any], error: Exception) -> dict[str, Any]:
        (self.responses / f"{call_id}.request.json").write_text(
            json.dumps(request, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        record = {"id": call_id, "ok": False, "error_type": type(error).__name__, "error": str(error)}
        self.calls.append(record)
        self.consecutive_failures += 1
        write_json(self.run_directory / "calls.json", self.calls)
        return record


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True, help="new immutable run identifier")
    parser.add_argument(
        "--experiment",
        choices=tuple(EXPERIMENT_MANIFESTS),
        default="base",
        help="registered experiment manifest (default: base)",
    )
    parser.add_argument(
        "--candidate",
        type=int,
        choices=(1, 2),
        default=1,
        help="registered candidate order (default: 1)",
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:11434")
    parser.add_argument("--timeout-seconds", type=float, default=300.0)
    return parser.parse_args()


def main() -> int:
    arguments = parse_args()
    if not RUN_ID.fullmatch(arguments.run_id):
        print("ERROR: run ID must be 3-80 lowercase safe characters", file=sys.stderr)
        return 2

    manifest_path = EXPERIMENT_MANIFESTS[arguments.experiment]
    manifest = load_json(manifest_path)
    candidates = manifest["candidates"]
    if arguments.candidate > len(candidates):
        print(f"ERROR: experiment {arguments.experiment} has no candidate {arguments.candidate}", file=sys.stderr)
        return 2
    candidate = candidates[arguments.candidate - 1]
    model = candidate["ollama_tag"]
    eligibility_error = candidate_run_error(candidate, arguments.run_id)
    if eligibility_error is not None:
        print(f"ERROR: {eligibility_error}", file=sys.stderr)
        return 2
    tools_document = load_json(ROOT / manifest["tool_schemas"])
    tools = tools_document["tools"]
    tools_by_name = schema_map(tools_document)
    prompts = load_jsonl(ROOT / manifest["prompt_pack"])
    system_prompt = (ROOT / manifest["system_prompt"]).read_text(encoding="utf-8").strip()

    run_directory = ROOT / "runs" / "model-compatibility" / arguments.run_id
    if run_directory.exists():
        print(f"ERROR: run directory already exists: {run_directory}", file=sys.stderr)
        return 2
    run_directory.mkdir(parents=True)
    recorder = RunRecorder(run_directory)
    source_snapshot = snapshot_sources(
        run_directory,
        [
            manifest_path,
            ROOT / manifest["prompt_pack"],
            ROOT / manifest["tool_schemas"],
            ROOT / manifest["system_prompt"],
            ROOT / "scripts/run_model_compatibility.py",
            ROOT / "src/localcode/compatibility.py",
        ],
    )
    run_state: dict[str, Any] = {
        "schema_version": 1,
        "experiment_id": manifest["experiment_id"],
        "run_id": arguments.run_id,
        "candidate_order": arguments.candidate,
        "candidate_id": candidate["id"],
        "state": "preflight",
        "model": model,
        "model_manifest_sha256": candidate["local_artifact_sha256"],
        "base_url": arguments.base_url,
        "tools_executed": 0,
        "source_snapshot": source_snapshot,
    }
    write_json(run_directory / "run.json", run_state)

    client = OllamaClient(arguments.base_url, arguments.timeout_seconds)
    try:
        loaded_before = model_sample(client, model)
    except CompatibilityError as error:
        run_state.update(state="failed_preflight", error=str(error))
        write_json(run_directory / "run.json", run_state)
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    if loaded_before is not None:
        message = f"model is already loaded; run `ollama stop {model}` before a cold-load measurement"
        run_state.update(state="failed_preflight", error=message, loaded_before=loaded_before)
        write_json(run_directory / "run.json", run_state)
        print(f"ERROR: {message}", file=sys.stderr)
        return 1

    swap_before = read_swap_used_bytes()
    run_state.update(state="running", swap_used_before_bytes=swap_before)
    write_json(run_directory / "run.json", run_state)
    scores: list[dict[str, Any]] = []
    probe_records: dict[str, list[dict[str, Any]]] = {}
    maximum_model_size = 0
    maximum_size_vram = 0
    minimum_memory_free_percent: int | None = read_memory_free_percent()
    stopped_reason: str | None = None

    def request(call_id: str, payload: dict[str, Any]):
        nonlocal maximum_model_size, maximum_size_vram, minimum_memory_free_percent, stopped_reason
        try:
            result = client.stream_chat(payload)
            record = recorder.record_success(call_id, payload, result)
            print(
                f"[ok] {call_id}: prompt_tokens={result.prompt_eval_count} "
                f"output_tokens={result.eval_count} wall={result.wall_seconds:.2f}s",
                flush=True,
            )
        except (CompatibilityError, OSError, ValueError) as error:
            recorder.record_failure(call_id, payload, error)
            print(f"[failed] {call_id}: {error}", flush=True)
            if recorder.consecutive_failures >= 3:
                stopped_reason = "three_consecutive_request_failures"
            return None, None
        try:
            sample = model_sample(client, model)
        except CompatibilityError:
            sample = None
        if sample is not None:
            sample["after_call"] = call_id
            recorder.memory_samples.append(sample)
            size = sample.get("size_bytes")
            size_vram = sample.get("size_vram_bytes")
            if isinstance(size, int):
                maximum_model_size = max(maximum_model_size, size)
            if isinstance(size_vram, int):
                maximum_size_vram = max(maximum_size_vram, size_vram)
            write_json(run_directory / "memory_samples.json", recorder.memory_samples)
        maximum_gib = manifest["gates"]["maximum_peak_model_working_set_gib"]
        if maximum_model_size > maximum_gib * GIB:
            stopped_reason = "model_working_set_limit"
        swap_now = read_swap_used_bytes()
        if swap_before is not None and swap_now is not None:
            growth = max(0, swap_now - swap_before)
            if growth > manifest["gates"]["maximum_swap_growth_gib"] * GIB:
                stopped_reason = "swap_growth_limit"
        memory_free_percent = read_memory_free_percent()
        if memory_free_percent is not None:
            minimum_memory_free_percent = (
                memory_free_percent
                if minimum_memory_free_percent is None
                else min(minimum_memory_free_percent, memory_free_percent)
            )
            if memory_free_percent < manifest["gates"]["minimum_host_memory_free_percent"]:
                stopped_reason = "critical_host_memory_pressure"
        return result, record

    sampling = manifest["sampling"]
    for prompt in prompts:
        if stopped_reason:
            break
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt["user"]},
            ],
            "tools": tools,
            "stream": True,
            "think": False,
            "keep_alive": "2m",
            "options": {
                "temperature": sampling["temperature"],
                "seed": sampling["seed"],
                "num_predict": sampling["max_output_tokens"],
                "num_ctx": 4096,
            },
        }
        result, _ = request(prompt["id"], payload)
        if result is not None:
            scores.append(score_prompt(prompt, result, tools_by_name))
            write_json(run_directory / "prompt_scores.json", scores)

    if not stopped_reason:
        for target in manifest["context_probes_tokens"]:
            initial_repetitions = max(1, target - 128)
            calibration_payload = {
                "model": model,
                "messages": [{"role": "user", "content": probe_user_message(initial_repetitions)}],
                "stream": True,
                "think": False,
                "keep_alive": "2m",
                "options": {"temperature": 0, "seed": sampling["seed"], "num_predict": 1, "num_ctx": target + 512},
            }
            calibration, _ = request(f"probe-{target}-calibration", calibration_payload)
            if calibration is None or stopped_reason:
                break
            if calibration.prompt_eval_count <= 0:
                stopped_reason = f"probe_{target}_calibration_missing_tokens"
                break
            adjusted_repetitions = max(1, round(initial_repetitions * target / calibration.prompt_eval_count))
            probe_records[str(target)] = []
            for repetition in range(1, manifest["context_probe_repetitions"] + 1):
                probe_payload = {
                    "model": model,
                    "messages": [{"role": "user", "content": probe_user_message(adjusted_repetitions)}],
                    "stream": True,
                    "think": False,
                    "keep_alive": "2m",
                    "options": {
                        "temperature": 0,
                        "seed": sampling["seed"],
                        "num_predict": sampling["max_output_tokens"],
                        "num_ctx": target + 512,
                    },
                }
                _, record = request(f"probe-{target}-{repetition}", probe_payload)
                if record is not None:
                    probe_records[str(target)].append(record)
                    write_json(run_directory / "context_probes.json", probe_records)
                if stopped_reason:
                    break
            if stopped_reason:
                break

    swap_after = read_swap_used_bytes()
    schema_valid = sum(score.get("schema_valid") is True for score in scores)
    decision_correct = sum(score.get("decision_correct") is True for score in scores)
    reasoning_correct = sum(score.get("reasoning_correct") is True for score in scores)
    gates = manifest["gates"]
    required_schema, schema_denominator = ratio(gates["minimum_schema_valid_tool_calls"])
    required_decisions, decision_denominator = ratio(gates["minimum_correct_action_decisions"])
    required_reasoning, reasoning_denominator = ratio(gates["minimum_correct_reasoning_answers"])
    gate_results: dict[str, bool] = {
        "cold_load_completes": any(
            call.get("id") == prompts[0]["id"] and call.get("ok") is True and call.get("load_duration_ns", 0) > 0
            for call in recorder.calls
        ),
        "schema_valid_tool_calls": schema_valid >= required_schema and sum(score["schema_valid"] is not None for score in scores) == schema_denominator,
        "correct_action_decisions": decision_correct >= required_decisions and sum(score["decision_correct"] is not None for score in scores) == decision_denominator,
        "correct_reasoning_answers": reasoning_correct >= required_reasoning and sum(score["reasoning_correct"] is not None for score in scores) == reasoning_denominator,
        "model_working_set": maximum_model_size <= gates["maximum_peak_model_working_set_gib"] * GIB,
        "swap_growth": swap_before is not None and swap_after is not None and max(0, swap_after - swap_before) <= gates["maximum_swap_growth_gib"] * GIB,
        "host_memory_pressure": minimum_memory_free_percent is not None
        and minimum_memory_free_percent >= gates["minimum_host_memory_free_percent"],
    }
    probe_summaries: dict[str, Any] = {}
    tolerance = manifest["context_probe_token_tolerance_fraction"]
    for target in manifest["context_probes_tokens"]:
        records = probe_records.get(str(target), [])
        speeds = [record["output_tokens_per_second"] for record in records if record.get("output_tokens_per_second") is not None]
        first_output = [record["time_to_first_output_seconds"] for record in records]
        prompt_counts = [record["prompt_eval_count"] for record in records]
        complete = len(records) == manifest["context_probe_repetitions"]
        token_match = complete and all(abs(count - target) / target <= tolerance for count in prompt_counts)
        median_speed = statistics.median(speeds) if len(speeds) == len(records) and speeds else None
        median_first = statistics.median(first_output) if complete else None
        suffix = "4k" if target == 4096 else "16k"
        speed_pass = median_speed is not None and median_speed >= gates["minimum_median_output_tokens_per_second_each_context"]
        first_pass = median_first is not None and median_first <= gates[f"maximum_median_time_to_first_token_seconds_{suffix}"]
        gate_results[f"context_{target}_complete"] = complete and token_match
        gate_results[f"context_{target}_speed"] = speed_pass
        gate_results[f"context_{target}_time_to_first_output"] = first_pass
        probe_summaries[str(target)] = {
            "prompt_eval_counts": prompt_counts,
            "median_output_tokens_per_second": median_speed,
            "median_time_to_first_output_seconds": median_first,
            "complete": complete,
            "within_token_tolerance": token_match,
        }

    evaluated_schema = sum(score["schema_valid"] is not None for score in scores)
    evaluated_decisions = sum(score["decision_correct"] is not None for score in scores)
    evaluated_reasoning = sum(score["reasoning_correct"] is not None for score in scores)
    summary = {
        "schema_version": 1,
        "run_id": arguments.run_id,
        "model": model,
        "stopped_reason": stopped_reason,
        "scores": {
            "schema_valid_tool_calls": {
                "correct": schema_valid,
                "evaluated": evaluated_schema,
                "planned": schema_denominator,
                "required": required_schema,
            },
            "correct_action_decisions": {
                "correct": decision_correct,
                "evaluated": evaluated_decisions,
                "planned": decision_denominator,
                "required": required_decisions,
            },
            "correct_reasoning_answers": {
                "correct": reasoning_correct,
                "evaluated": evaluated_reasoning,
                "planned": reasoning_denominator,
                "required": required_reasoning,
            },
        },
        "semantic_pack_complete": len(scores) == len(prompts),
        "context_probes": probe_summaries,
        "maximum_model_size_bytes": maximum_model_size,
        "maximum_size_vram_bytes": maximum_size_vram,
        "swap_used_before_bytes": swap_before,
        "swap_used_after_bytes": swap_after,
        "swap_growth_bytes": None if swap_before is None or swap_after is None else max(0, swap_after - swap_before),
        "minimum_host_memory_free_percent": minimum_memory_free_percent,
        "gate_results": gate_results,
        "passed": stopped_reason is None and all(gate_results.values()),
        "tools_executed": 0,
    }
    write_json(run_directory / "summary.json", summary)
    run_state.update(state="complete" if summary["passed"] else "failed_gate", summary="summary.json")
    write_json(run_directory / "run.json", run_state)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
