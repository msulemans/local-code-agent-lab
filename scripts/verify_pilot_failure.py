#!/usr/bin/env python3
"""Deterministically confirm why real-model pilots failed on flask-5014.

Feeds the exact content-form JSON tool call that Qwen2.5-Coder-7B emitted
(preserved in runs/model-compatibility/m004c-qwen25-7b-v2/responses) through
the real loop-backend payload translator and strict decision validator.
"""

from __future__ import annotations

import json

from localcode.actions import ActionValidationError
from localcode.backends.ollama_loop import _loop_protocol_payload
from localcode.compatibility import ChatResult
from localcode.decisions import DecisionValidator


def make(content: str, tool_calls: list[dict]):
    return ChatResult(
        content=content,
        thinking="",
        tool_calls=tuple(tool_calls),
        prompt_eval_count=0,
        prompt_eval_duration_ns=0,
        eval_count=0,
        eval_duration_ns=0,
        load_duration_ns=0,
        total_duration_ns=0,
        time_to_first_output_seconds=0.0,
        wall_seconds=0.0,
        chunks=(),
    )


def main() -> int:
    # Exact native emission preserved in the m004c compatibility stream files:
    #   {"name": "git_diff", "arguments": {"max_bytes": 1024, "path": null, "staged": false}}
    emitted = json.dumps(
        {"name": "git_diff", "arguments": {"max_bytes": 1024, "path": None, "staged": False}},
        sort_keys=True,
    )
    result = make(emitted, [])
    payload = _loop_protocol_payload(result)
    print("backend payload:", payload)

    tool_document = json.loads(
        open("benchmarks/micro_agent/tool_schemas.json", encoding="utf-8").read()
    )
    validator = DecisionValidator.from_tool_document(tool_document)
    try:
        decision = validator.validate(payload)
        print("validator decision:", decision)
    except ActionValidationError as exc:
        print(f"validator rejected at strict argument schema (code={exc.code}): {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
