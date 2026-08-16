"""Shared fake-backend parser repair demo for headless and TUI runs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import tempfile
import time
from typing import Callable

from .decisions import DecisionValidator
from .engineering_registry import EngineeringToolRegistry
from .loop import (
    AgentLoop,
    CompletionRequirements,
    LoopBudgets,
    LoopObserver,
    LoopRequest,
    LoopResult,
)
from .test_runner import TestRunner
from .tools import ToolResult, git_diff
from .workspace import create_workspace


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PARSER_FIXTURE = PROJECT_ROOT / "tests/fixtures/micro_repos/parser_none"
MICRO_AGENT_SCHEMAS = PROJECT_ROOT / "benchmarks/micro_agent/tool_schemas.json"
PARSER_PATCH = """diff --git a/src/tiny_parser.py b/src/tiny_parser.py
--- a/src/tiny_parser.py
+++ b/src/tiny_parser.py
@@ -1,2 +1,4 @@
 def parse_value(text: str | None) -> str:
+    if text is None:
+        return ""
     return text.strip()
"""


@dataclass(frozen=True, slots=True)
class DemoRepairRun:
    result: LoopResult
    final_diff: str
    test_metadata: tuple[tuple[str, object], ...]
    source_fixture_unchanged: bool


def decision(value: dict[str, object], summary: str) -> str:
    return json.dumps(
        {
            "protocol_version": "1",
            "thought_summary": summary,
            "decision": value,
        }
    )


class FakeCodingBackend:
    """Deterministic stand-in for future local-model repair decisions."""

    def __init__(self) -> None:
        self._responses = iter(
            (
                decision(
                    {"kind": "tool", "tool": "search_code", "arguments": {"query": "parse_value"}},
                    "Find the failing parser implementation.",
                ),
                decision(
                    {"kind": "tool", "tool": "read_file", "arguments": {"path": "src/tiny_parser.py"}},
                    "Read the implementation before editing.",
                ),
                decision(
                    {"kind": "tool", "tool": "apply_patch", "arguments": {"patch": PARSER_PATCH}},
                    "Handle None before calling strip.",
                ),
                decision(
                    {
                        "kind": "tool",
                        "tool": "run_tests",
                        "arguments": {"command_name": "python-unittest"},
                    },
                    "Verify the registered fixture test command.",
                ),
                decision(
                    {"kind": "tool", "tool": "git_diff", "arguments": {}},
                    "Inspect the exact final patch.",
                ),
                decision(
                    {
                        "kind": "final",
                        "answer": "Handled None before strip; the registered sandboxed tests pass.",
                    },
                    "The patch and current test evidence are ready.",
                ),
            )
        )

    def complete(self, request: LoopRequest) -> str:
        return next(self._responses)


def run_parser_repair_demo(
    *,
    run_id: str = "demo-engineering-agent",
    observer: LoopObserver | None = None,
    clock: Callable[[], str] | None = None,
    monotonic: Callable[[], float] | None = None,
    test_runner: TestRunner | None = None,
) -> DemoRepairRun:
    """Run the parser fixture repair in a disposable workspace and return evidence."""

    source_before = (PARSER_FIXTURE / "src/tiny_parser.py").read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory(prefix="localcode-agent-demo-") as temporary:
        workspace = create_workspace(PARSER_FIXTURE, Path(temporary) / "workspace")
        result = AgentLoop(
            FakeCodingBackend(),
            DecisionValidator.from_path(MICRO_AGENT_SCHEMAS),
            EngineeringToolRegistry(workspace, test_runner=test_runner),
            LoopBudgets(max_turns=8, max_tool_calls=6, max_wall_seconds=30),
            clock=clock
            if clock is not None
            else lambda: datetime.now().astimezone().isoformat(timespec="microseconds"),
            monotonic=monotonic if monotonic is not None else time.monotonic,
            completion_requirements=CompletionRequirements(
                require_patch=True,
                require_passing_tests=True,
            ),
            observer=observer,
        ).run(
            run_id=run_id,
            issue=(PARSER_FIXTURE / "ISSUE.md").read_text(encoding="utf-8"),
        )
        final_diff = git_diff(workspace.root).content
        test_observation = _test_observation(result)

    source_after = (PARSER_FIXTURE / "src/tiny_parser.py").read_text(encoding="utf-8")
    return DemoRepairRun(
        result=result,
        final_diff=final_diff,
        test_metadata=tuple(test_observation.metadata),
        source_fixture_unchanged=source_before == source_after,
    )


def _test_observation(result: LoopResult) -> ToolResult:
    for observation in result.observations:
        if observation.metadata_dict().get("command") == "python-unittest":
            return observation
    raise RuntimeError("demo completed without python-unittest evidence")
