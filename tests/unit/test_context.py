from __future__ import annotations

import json
from pathlib import Path
import unittest

from localcode.context import (
    ContextRequest,
    RetrievalContextCompiler,
    SimpleContextCompiler,
    compile_single_shot_context,
    compile_simple_context,
)
from localcode.decisions import DecisionValidator
from localcode.loop import LoopBudgets, ReadOnlyAgentLoop
from localcode.registry import ToolRegistry


ROOT = Path("tests/fixtures/micro_repos/parser_none")
SCHEMAS = Path("benchmarks/model_compatibility/tool_schemas.json")
NOW = "2026-08-12T16:00:00+10:00"


def final() -> str:
    return json.dumps(
        {
            "protocol_version": "1",
            "thought_summary": "The retrieval pack is enough for this probe.",
            "decision": {"kind": "final", "answer": "done"},
        }
    )


class FakeBackend:
    def __init__(self, response: str) -> None:
        self.response = response
        self.requests = []

    def complete(self, request):
        self.requests.append(request)
        return self.response


class ContextCompilerTests(unittest.TestCase):
    def test_simple_context_compiler_preserves_historical_envelope(self) -> None:
        request = ContextRequest(
            issue="Find parser",
            history=("tool result",),
            budgets_remaining=(("turns", 1),),
            max_chars=1_000,
        )

        self.assertEqual(
            SimpleContextCompiler().compile(request),
            compile_simple_context(
                request.issue,
                request.history,
                request.budgets_remaining,
                request.max_chars,
            ),
        )

    def test_retrieval_context_contains_bounded_evidence_without_expected_labels(self) -> None:
        issue = (ROOT / "ISSUE.md").read_text(encoding="utf-8")
        request = ContextRequest(
            issue=issue,
            history=(),
            budgets_remaining=(("turns", 8),),
            max_chars=4_000,
        )

        payload = json.loads(RetrievalContextCompiler(ROOT, max_files=2).compile(request))

        self.assertEqual(payload["retrieval_treatment"]["kind"], "deterministic_v1")
        self.assertIn("retrieved_evidence", payload)
        self.assertIn("src/tiny_parser.py", payload["retrieved_evidence"]["selected_paths"])
        self.assertNotIn("ISSUE.md", payload["retrieved_evidence"]["selected_paths"])
        self.assertNotIn("expected_changed_paths", payload)
        self.assertLessEqual(len(json.dumps(payload, separators=(",", ":"))), 4_000)

    def test_single_shot_context_contains_bounded_repository_map_without_history(self) -> None:
        issue = (ROOT / "ISSUE.md").read_text(encoding="utf-8")

        payload = json.loads(compile_single_shot_context(issue, ROOT, 4_000, max_map_files=8))

        self.assertEqual(payload["single_shot_treatment"]["kind"], "bounded_repository_map_v1")
        self.assertIn("repository_map", payload)
        self.assertIn("src/tiny_parser.py", [entry["path"] for entry in payload["repository_map"]])
        self.assertEqual(payload["history"], [])
        self.assertEqual(payload["budgets_remaining"], {})
        self.assertLessEqual(len(json.dumps(payload, separators=(",", ":"))), 4_000)

    def test_loop_can_receive_retrieval_context_without_changing_tools_or_result(self) -> None:
        backend = FakeBackend(final())
        loop = ReadOnlyAgentLoop(
            backend,
            DecisionValidator.from_path(SCHEMAS),
            ToolRegistry(ROOT),
            LoopBudgets(max_turns=1, max_tool_calls=1),
            clock=lambda: NOW,
            monotonic=lambda: 0.0,
            context_compiler=RetrievalContextCompiler(ROOT, max_files=2),
        )

        result = loop.run(run_id="retrieval-context-loop", issue=(ROOT / "ISSUE.md").read_text(encoding="utf-8"))
        context = json.loads(backend.requests[0].context)

        self.assertEqual(result.final_answer, "done")
        self.assertEqual(result.tool_calls_used, 0)
        self.assertIn("retrieved_evidence", context)
        self.assertEqual(backend.requests[0].allowed_tools, ("git_diff", "list_files", "read_file", "search_code"))


if __name__ == "__main__":
    unittest.main()
