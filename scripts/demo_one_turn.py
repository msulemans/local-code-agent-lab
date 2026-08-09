#!/usr/bin/env python3
"""Run deterministic Milestone 005 examples without loading a model."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from localcode.actions import ActionValidator
from localcode.controller import OneTurnController, OneTurnRequest
from localcode.registry import ToolRegistry


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = REPOSITORY_ROOT / "tests/fixtures/micro_repos/parser_none"
TOOL_SCHEMAS = REPOSITORY_ROOT / "benchmarks/model_compatibility/tool_schemas.json"
FIXED_TIME = "2026-08-09T19:00:00+10:00"


class FakeBackend:
    """Return registered text instead of performing model inference."""

    def __init__(self, response: str) -> None:
        self.response = response

    def complete(self, request: OneTurnRequest) -> str:
        return self.response


def action(tool: str, arguments: dict[str, object]) -> str:
    return json.dumps(
        {
            "protocol_version": "1",
            "thought_summary": "Inspect one bounded piece of repository evidence.",
            "action": {"tool": tool, "arguments": arguments},
        }
    )


CASES = {
    "valid": action("search_code", {"query": "def parse"}),
    "invalid-json": "I should search the repository first.",
    "unknown-tool": action("terminal", {"command": "pwd"}),
    "path-escape": action("read_file", {"path": "../secret.txt"}),
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=tuple(CASES), default="valid")
    arguments = parser.parse_args()

    controller = OneTurnController(
        FakeBackend(CASES[arguments.case]),
        ActionValidator.from_path(TOOL_SCHEMAS),
        ToolRegistry(FIXTURE_ROOT),
        clock=lambda: FIXED_TIME,
    )
    result = controller.run(
        run_id=f"demo-{arguments.case}",
        issue="Parser crashes when given None.",
    )

    print("EVENTS")
    for event in result.events:
        print(event.to_json())
    print("OBSERVATION")
    print(
        json.dumps(
            {
                "content": result.observation.content,
                "truncated": result.observation.truncated,
                "metadata": result.observation.metadata_dict(),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
