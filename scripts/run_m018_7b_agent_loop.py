#!/usr/bin/env python3
"""Measure pinned Qwen 7B inside the real bounded engineering loop."""

from __future__ import annotations

import argparse
import json
import hashlib
from pathlib import Path
import re
import sys
import time
from typing import Any

from localcode.backends.mlx_loop import MlxLoopBackend
from localcode.decisions import DecisionValidator
from localcode.engineering_registry import EngineeringToolRegistry, ProductionReviewRegistry
from localcode.loop import AgentLoop, CompletionRequirements, LoopBudgets
from localcode.model_pin import verify_model_pin
from localcode.context import RetrievalContextCompiler, SimpleContextCompiler
from localcode.tools import git_diff
from localcode.training_baseline import load_executable_suite
from localcode.workspace import create_workspace


ROOT = Path(__file__).resolve().parents[1]
MODEL_CONFIG = ROOT / "benchmarks/training/m017_7b_baseline_v1.json"
SCHEMAS = ROOT / "benchmarks/micro_agent/tool_schemas.json"
RUN_ID = __import__("re").compile(r"^[a-z0-9][a-z0-9._-]{2,79}$")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--context-mode", choices=("simple", "retrieval"), default="retrieval")
    parser.add_argument("--max-cases", type=int, default=6)
    parser.add_argument("--max-turns", type=int, default=10)
    parser.add_argument("--adapter-path", type=Path, default=None)
    arguments = parser.parse_args()
    if Path(sys.prefix).resolve() != (ROOT / ".venv-mlx").resolve():
        raise SystemExit("M018 must run with .venv-mlx/bin/python")
    if RUN_ID.fullmatch(arguments.run_id) is None:
        raise SystemExit("run ID must contain 3-80 lowercase safe characters")
    if not 1 <= arguments.max_cases <= 6 or not 1 <= arguments.max_turns <= 20:
        raise SystemExit("max-cases must be 1-6 and max-turns must be 1-20")

    model_document = json.loads(MODEL_CONFIG.read_text(encoding="utf-8"))
    model_path = verify_model_pin(model_document["model"], project_root=ROOT)
    if arguments.adapter_path is not None:
        adapter_path = arguments.adapter_path
        if not adapter_path.is_absolute():
            adapter_path = ROOT / adapter_path
        if not adapter_path.is_dir() or not (adapter_path / "adapter_config.json").is_file() or not (adapter_path / "adapters.safetensors").is_file():
            raise SystemExit("adapter-path must contain adapter_config.json and adapters.safetensors")
    else:
        adapter_path = None
    suite = load_executable_suite(ROOT / model_document["executable_suite"], ROOT)
    tool_document = json.loads(SCHEMAS.read_text(encoding="utf-8"))
    directory = ROOT / "runs/training" / arguments.run_id
    try:
        directory.mkdir(parents=True)
    except FileExistsError as exc:
        raise SystemExit("run directory already exists; use a fresh run ID") from exc

    import mlx.core as mx

    mx.reset_peak_memory()
    backend = MlxLoopBackend(
        model_path=model_path,
        adapter_path=adapter_path,
        tool_document=tool_document,
        max_output_tokens=768,
    )
    validator = DecisionValidator.from_tool_document(tool_document)
    record: dict[str, Any] = {
        "schema_version": 1,
        "run_id": arguments.run_id,
        "state": "running",
        "experiment_id": "m018-qwen25-coder-7b-bounded-agent-loop-v1",
        "model_id": model_document["model"]["model_id"],
        "model_revision": model_document["model"]["revision"],
        "adapter_path": None if adapter_path is None else str(adapter_path),
        "quantization_bits": 4,
        "action_representation": "typed_tools_edit_file_retry",
        "context_mode": arguments.context_mode,
        "suite_id": suite.suite_id,
        "registered": min(arguments.max_cases, len(suite.cases)),
        "solved": None,
        "cases": [],
        "sealed_examples_loaded": 0,
        "peak_memory_gb": None,
        "generated_tokens": 0,
        "wall_seconds": None,
        "error": None,
    }
    _write(directory, record)
    started = time.monotonic()
    try:
        for index, case in enumerate(suite.cases[: arguments.max_cases], 1):
            case_started = time.monotonic()
            source_before = _fixture_fingerprint(case.fixture)
            with __import__("tempfile").TemporaryDirectory(prefix=f"localcode-m018-{case.case_id}-") as temporary:
                workspace = create_workspace(case.fixture, Path(temporary) / "workspace")
                registry = EngineeringToolRegistry(workspace)
                context = (
                    RetrievalContextCompiler(workspace.root, max_files=5)
                    if arguments.context_mode == "retrieval"
                    else SimpleContextCompiler()
                )
                result = AgentLoop(
                    backend,
                    validator,
                    ProductionReviewRegistry(registry),
                    LoopBudgets(
                        max_turns=arguments.max_turns,
                        max_tool_calls=10,
                        max_invalid_actions=3,
                        max_identical_actions=1,
                        recover_repeated_actions=True,
                        phase_tool_policy=True,
                        auto_test_after_edit=True,
                        max_wall_seconds=300,
                        max_context_chars=12_000,
                    ),
                    clock=lambda: time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                    monotonic=time.monotonic,
                    completion_requirements=CompletionRequirements(
                        require_patch=True,
                        require_passing_tests=True,
                        require_test_execution=True,
                    ),
                    context_compiler=context,
                ).run(run_id=f"m018-{case.case_id}", issue=case.issue)
                diff = git_diff(workspace.root)
                changed_paths = tuple(
                    sorted(
                        {
                            match.group(1)
                            for match in re.finditer(
                                r"^diff --git a/([^\s]+) b/([^\s]+)$", diff.content, re.MULTILINE
                            )
                        }
                    )
                )
                tests = [
                    int(observation.metadata_dict()["exit_code"])
                    for observation in result.observations
                    if "exit_code" in observation.metadata_dict()
                ]
                solved = result.termination_reason.value == "final_answer" and bool(diff.content.strip()) and tests and tests[-1] == 0
                case_record = {
                    "case_id": case.case_id,
                    "solved": bool(solved),
                    "termination_reason": result.termination_reason.value,
                    "turns_used": result.turns_used,
                    "tool_calls_used": result.tool_calls_used,
                    "invalid_actions_used": result.invalid_actions_used,
                    "tests_executed": tests,
                    "changed": bool(diff.content.strip()),
                    "changed_paths": list(changed_paths),
                    "expected_changed_paths": [case.source_path],
                    "source_unchanged": source_before == _fixture_fingerprint(case.fixture),
                    "diff": diff.content,
                    "events": [event.to_dict() for event in result.events],
                    "observations": [
                        {
                            "content": observation.content,
                            "metadata": observation.metadata_dict(),
                        }
                        for observation in result.observations
                    ],
                    "wall_seconds": round(time.monotonic() - case_started, 6),
                }
                record["cases"].append(case_record)
                _write(directory, record)
                print(
                    f"CASE {index}/{record['registered']} {case.case_id} "
                    f"solved={bool(solved)} termination={result.termination_reason.value} "
                    f"tools={result.tool_calls_used} tests={tests}",
                    flush=True,
                )
    except Exception as exc:
        record.update(
            state="failed",
            wall_seconds=round(time.monotonic() - started, 6),
            peak_memory_gb=round(mx.get_peak_memory() / 1e9, 6),
            generated_tokens=backend.generated_tokens,
            error={"type": type(exc).__name__, "message": str(exc)},
        )
        _write(directory, record)
        print(json.dumps(_summary(record, directory), indent=2, sort_keys=True))
        return 2

    record.update(
        state="measured",
        solved=sum(bool(case["solved"]) for case in record["cases"]),
        wall_seconds=round(time.monotonic() - started, 6),
        peak_memory_gb=round(mx.get_peak_memory() / 1e9, 6),
        generated_tokens=backend.generated_tokens,
    )
    _write(directory, record)
    print(json.dumps(_summary(record, directory), indent=2, sort_keys=True))
    return 0


def _write(directory: Path, record: dict[str, Any]) -> None:
    temporary = directory / "run.json.tmp"
    temporary.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(directory / "run.json")


def _fixture_fingerprint(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if not path.is_file() or ".git" in path.parts:
            continue
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _summary(record: dict[str, Any], directory: Path) -> dict[str, Any]:
    return {
        "artifact": str(directory),
        "run_id": record["run_id"],
        "state": record["state"],
        "model_id": record["model_id"],
        "context_mode": record["context_mode"],
        "solved": record["solved"],
        "registered": record["registered"],
        "generated_tokens": record["generated_tokens"],
        "peak_memory_gb": record["peak_memory_gb"],
        "wall_seconds": record["wall_seconds"],
        "sealed_examples_loaded": record["sealed_examples_loaded"],
        "error": record["error"],
    }


if __name__ == "__main__":
    raise SystemExit(main())
