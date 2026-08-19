from __future__ import annotations

import json
from pathlib import Path
import unittest

from localcode.context import (
    ContextRequest,
    RetrievalContextCompiler,
    SimpleContextCompiler,
    _rank_map_files,
    _retrieval_payload,
    compile_single_shot_context,
    compile_simple_context,
)
from localcode.decisions import DecisionValidator
from localcode.loop import LoopBudgets, ReadOnlyAgentLoop
from localcode.registry import ToolRegistry
from localcode.retrieval import (
    EvidenceExcerpt,
    RepositoryFile,
    RepositoryMap,
    RetrievalPack,
)


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

    def test_retrieval_payload_bounds_the_rendered_repository_map(self) -> None:
        files = tuple(
            RepositoryFile(
                path=f"src/module_{index:04d}.py",
                kind="source",
                language="python",
                size_bytes=100,
                line_count=10,
                symbols=("sym",),
            )
            for index in range(120)
        )
        pack = RetrievalPack(
            repository_map=RepositoryMap(files, truncated=False),
            issue_terms=("blueprint", "name"),
            excerpts=(
                EvidenceExcerpt(
                    path="src/module_0000.py",
                    kind="source",
                    score=5,
                    reason="matched terms",
                    start_line=1,
                    end_line=3,
                    content="def sym():\n    pass\n",
                ),
            ),
            truncated=False,
        )

        payload = _retrieval_payload(pack)

        self.assertEqual(len(payload["map"]), 40)
        self.assertTrue(payload["map_truncated"])
        self.assertTrue(payload["truncated"])
        self.assertEqual(payload["map"][0]["path"], "src/module_0000.py")

    def test_single_shot_context_contains_bounded_repository_map_without_history(self) -> None:
        issue = (ROOT / "ISSUE.md").read_text(encoding="utf-8")

        payload = json.loads(compile_single_shot_context(issue, ROOT, 4_000, max_map_files=8))

        self.assertEqual(payload["single_shot_treatment"]["kind"], "issue_ranked_repository_map_v2")
        self.assertIn("repository_map", payload)
        self.assertIn("src/tiny_parser.py", [entry["path"] for entry in payload["repository_map"]])
        self.assertEqual(payload["history"], [])
        self.assertEqual(payload["budgets_remaining"], {})
        self.assertLessEqual(len(json.dumps(payload, separators=(",", ":"))), 4_000)

    def test_single_shot_map_ranks_issue_paths_and_symbols_before_lexical_noise(self) -> None:
        files = tuple(
            RepositoryFile(
                path=f"docs/noise_{index:03d}.rst",
                kind="other",
                language="rst",
                size_bytes=10,
                line_count=1,
                symbols=(),
            )
            for index in range(200)
        ) + (
            RepositoryFile(
                path="requests/models.py",
                kind="source",
                language="python",
                size_bytes=100,
                line_count=20,
                symbols=("RequestEncodingMixin",),
            ),
        )

        ranked = _rank_map_files(
            files,
            "Request with binary payload fails in RequestEncodingMixin",
            40,
        )

        self.assertEqual(ranked[0].path, "requests/models.py")
        self.assertNotIn("docs/noise_199.rst", [file.path for file in ranked])

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
