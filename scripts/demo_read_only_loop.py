#!/usr/bin/env python3
"""Run a deterministic three-turn read-only agent loop without a model."""

from __future__ import annotations

import json
from pathlib import Path

from localcode.decisions import DecisionValidator
from localcode.loop import LoopBudgets, LoopRequest, ReadOnlyAgentLoop
from localcode.registry import ToolRegistry


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/micro_repos/parser_none"
SCHEMAS = ROOT / "benchmarks/model_compatibility/tool_schemas.json"
NOW = "2026-08-10T12:00:00+10:00"


def decision(value: dict[str, object]) -> str:
    return json.dumps(
        {
            "protocol_version": "1",
            "thought_summary": "Follow the repository evidence.",
            "decision": value,
        }
    )


class FakeBackend:
    """Return a search, a read, and then one evidence-grounded answer."""

    def __init__(self) -> None:
        self._responses = iter(
            (
                decision(
                    {
                        "kind": "tool",
                        "tool": "search_code",
                        "arguments": {"query": "def parse_value"},
                    }
                ),
                decision(
                    {
                        "kind": "tool",
                        "tool": "read_file",
                        "arguments": {"path": "src/tiny_parser.py"},
                    }
                ),
                decision(
                    {
                        "kind": "final",
                        "answer": (
                            "parse_value is defined in src/tiny_parser.py. "
                            "It calls text.strip() without handling None."
                        ),
                    }
                ),
            )
        )

    def complete(self, request: LoopRequest) -> str:
        return next(self._responses)


def main() -> int:
    loop = ReadOnlyAgentLoop(
        FakeBackend(),
        DecisionValidator.from_path(SCHEMAS),
        ToolRegistry(FIXTURE),
        LoopBudgets(max_turns=4, max_tool_calls=3),
        clock=lambda: NOW,
        monotonic=lambda: 0.0,
    )
    result = loop.run(
        run_id="demo-read-only-loop",
        issue="Why does parse_value crash when passed None?",
    )

    print("EVENTS")
    for event in result.events:
        print(event.to_json())
    print("FINAL")
    print(result.final_answer)
    print("TERMINATION")
    print(result.termination_reason.value)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
