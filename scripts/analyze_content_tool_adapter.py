#!/usr/bin/env python3
"""Counterfactually score a strict JSON-content adapter without model inference."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from localcode.compatibility import ChatResult, schema_map, score_prompt  # noqa: E402


def parse_content_tool_call(content: str) -> dict[str, Any]:
    """Accept only one exact JSON object with name and arguments keys."""
    try:
        value = json.loads(content)
    except json.JSONDecodeError as error:
        raise ValueError(f"content is not one JSON value: {error.msg}") from error
    if not isinstance(value, dict) or set(value) != {"name", "arguments"}:
        raise ValueError("content must be an object containing exactly name and arguments")
    if not isinstance(value["name"], str) or not isinstance(value["arguments"], dict):
        raise ValueError("name must be a string and arguments must be an object")
    return {"function": {"name": value["name"], "arguments": value["arguments"]}}


def result_from_call(call: dict[str, Any], tool_calls: tuple[dict[str, Any], ...]) -> ChatResult:
    return ChatResult(
        content=call.get("content", ""),
        thinking=call.get("thinking", ""),
        tool_calls=tool_calls,
        prompt_eval_count=call.get("prompt_eval_count", 0),
        prompt_eval_duration_ns=call.get("prompt_eval_duration_ns", 0),
        eval_count=call.get("eval_count", 0),
        eval_duration_ns=call.get("eval_duration_ns", 0),
        load_duration_ns=call.get("load_duration_ns", 0),
        total_duration_ns=call.get("total_duration_ns", 0),
        time_to_first_output_seconds=call.get("time_to_first_output_seconds", 0.0),
        wall_seconds=call.get("wall_seconds", 0.0),
        chunks=(),
    )


def analyze(run_directory: Path) -> dict[str, Any]:
    prompts = [
        json.loads(line)
        for line in (ROOT / "benchmarks/model_compatibility/prompt_pack.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line
    ]
    tools = schema_map(
        json.loads((ROOT / "benchmarks/model_compatibility/tool_schemas.json").read_text(encoding="utf-8"))
    )
    calls = {
        call["id"]: call
        for call in json.loads((run_directory / "calls.json").read_text(encoding="utf-8"))
        if call.get("ok") is True
    }

    scores: list[dict[str, Any]] = []
    for prompt in prompts:
        call = calls.get(prompt["id"])
        if call is None:
            continue
        adapter_error: str | None = None
        adapted_calls = tuple(call.get("tool_calls", []))
        if prompt["expected"]["kind"] == "tool" and not adapted_calls:
            try:
                adapted_calls = (parse_content_tool_call(call.get("content", "")),)
            except ValueError as error:
                adapter_error = str(error)
        score = score_prompt(prompt, result_from_call(call, adapted_calls), tools)
        score["adapter_accepted"] = bool(adapted_calls) and not call.get("tool_calls")
        score["adapter_error"] = adapter_error
        scores.append(score)

    tool_scores = [score for score in scores if score["expected_kind"] == "tool"]
    decision_scores = [score for score in scores if score["decision_correct"] is not None]
    reasoning_scores = [score for score in scores if score["reasoning_correct"] is not None]
    return {
        "schema_version": 1,
        "analysis_kind": "strict_content_adapter_counterfactual",
        "source_run_id": run_directory.name,
        "source_run_unchanged": True,
        "scores": {
            "schema_valid_tool_calls": {
                "correct": sum(score["schema_valid"] is True for score in tool_scores),
                "evaluated": len(tool_scores),
                "required": 11,
            },
            "correct_action_decisions": {
                "correct": sum(score["decision_correct"] is True for score in decision_scores),
                "evaluated": len(decision_scores),
                "required": 14,
            },
            "correct_reasoning_answers": {
                "correct": sum(score["reasoning_correct"] is True for score in reasoning_scores),
                "evaluated": len(reasoning_scores),
                "required": 3,
            },
        },
        "adapter_accepted_calls": sum(score["adapter_accepted"] for score in scores),
        "prompt_scores": scores,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-directory",
        type=Path,
        default=ROOT / "runs/model-compatibility/m004c-qwen25-7b-v2",
    )
    return parser.parse_args()


def main() -> int:
    arguments = parse_args()
    try:
        report = analyze(arguments.run_directory.resolve(strict=True))
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
