#!/usr/bin/env python3
"""Prepare or evaluate a pinned LocalCode real-issue benchmark run."""

from __future__ import annotations

import argparse
from dataclasses import replace
import json
from pathlib import Path

from localcode.real_benchmark import (
    EvaluationInstanceResult,
    PatchAttempt,
    RealBenchmarkConfiguration,
    RealBenchmarkIssue,
    load_real_benchmark_manifest,
    run_real_benchmark,
)
from localcode.real_benchmark_adapters import (
    DatasetControlPatchProducer,
    JsonDatasetIssueResolver,
    LocalCodePatchProducer,
    OfficialSwebenchEvaluator,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "benchmarks/real_benchmark/manifest_v1.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--dataset", required=True, help="local pinned SWE-bench JSON/JSONL snapshot")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--runs-root", default=str(ROOT / "runs"))
    parser.add_argument("--evaluation-root", default=str(ROOT))
    parser.add_argument("--python", default="python3.11", dest="python_executable")
    parser.add_argument("--max-workers", type=int, default=1)
    parser.add_argument("--cache-level", choices=("none", "base", "env", "instance"), default="base")
    parser.add_argument("--model-name", default="localcode/empty-control")
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--dataset-name", default=None)
    parser.add_argument("--control", choices=("empty", "gold"), default="empty")
    parser.add_argument("--control-id", default=None, help="run gold for only one pinned instance")
    parser.add_argument("--producer", choices=("control", "ollama"), default="control")
    parser.add_argument("--model", default="qwen3.5:9b-q4_K_M")
    parser.add_argument(
        "--tool-schemas",
        default=str(ROOT / "benchmarks/micro_agent/tool_schemas.json"),
    )
    parser.add_argument("--configuration-id", choices=("B0", "A1", "A2", "A3"), default=None,
                        help="measure only this configuration for a control run")
    parser.add_argument(
        "--no-progress",
        action="store_false",
        dest="progress",
        default=True,
        help="disable per-instance progress lines during preparation",
    )
    arguments = parser.parse_args()

    progress_observer = (
        (lambda line: print(f"PROGRESS {line}", flush=True)) if arguments.progress else None
    )

    manifest = load_real_benchmark_manifest(arguments.manifest)
    if arguments.configuration_id is not None:
        manifest = replace(
            manifest,
            configurations=tuple(
                replace(
                    configuration,
                    availability=(
                        "implemented"
                        if configuration.configuration_id == arguments.configuration_id
                        else "planned"
                    ),
                )
                for configuration in manifest.configurations
            ),
        )
    resolver = JsonDatasetIssueResolver(arguments.dataset)
    if arguments.producer == "ollama":
        tool_document = json.loads(Path(arguments.tool_schemas).read_text(encoding="utf-8"))
        producer = LocalCodePatchProducer(
            model=arguments.model,
            tool_document=tool_document,
            only_instance_id=arguments.control_id,
        )
    else:
        producer = DatasetControlPatchProducer(
            arguments.dataset,
            mode=arguments.control,
            only_instance_id=arguments.control_id,
        )
    if arguments.prepare_only:
        from localcode.real_benchmark import prepare_real_benchmark_run

        prepared = prepare_real_benchmark_run(
            manifest,
            run_id=arguments.run_id,
            runs_root=arguments.runs_root,
            issue_resolver=resolver,
            patch_producer=producer,
            progress_observer=progress_observer,
        )
        print(json.dumps(prepared.to_dict(), indent=2, sort_keys=True))
        return 0

    evaluator = OfficialSwebenchEvaluator(
        dataset_name=arguments.dataset_name or arguments.dataset,
        split=manifest.dataset_split,
        evaluation_root=arguments.evaluation_root,
        python_executable=arguments.python_executable,
        max_workers=arguments.max_workers,
        cache_level=arguments.cache_level,
    )
    result = run_real_benchmark(
        manifest,
        run_id=arguments.run_id,
        runs_root=arguments.runs_root,
        issue_resolver=resolver,
        patch_producer=producer,
        evaluator=evaluator,
        progress_observer=progress_observer,
    )
    for configuration in result.configurations:
        print(
            f"CONFIG {configuration.configuration_id} status={configuration.status} "
            f"resolved={configuration.resolved}/{configuration.registered}"
        )
    print("SUMMARY " + json.dumps(result.to_dict(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
