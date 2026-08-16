from __future__ import annotations

from io import StringIO
import unittest

from localcode.demo_repair import run_parser_repair_demo
from localcode.tools import ToolResult
from localcode.tui import TerminalEventStream, TerminalRenderer


NOW = "2026-08-12T13:00:00+10:00"


class PassingTestRunner:
    def run(
        self,
        workspace,
        command_name: str,
        *,
        timeout_seconds: int = 30,
        max_output_bytes: int = 65_536,
    ) -> ToolResult:
        return ToolResult(
            content="test_none_is_empty ... ok\n\nOK",
            metadata=(
                ("command", command_name),
                ("exit_code", 0),
                ("timed_out", False),
                ("output_limit_hit", False),
                ("duration_ms", 1),
                ("sandboxed", True),
            ),
        )


def run_demo(observer=None):
    return run_parser_repair_demo(
        run_id="tui-equivalence",
        observer=observer,
        clock=lambda: NOW,
        monotonic=lambda: 0.0,
        test_runner=PassingTestRunner(),
    )


class TerminalRendererTests(unittest.TestCase):
    def test_terminal_stream_renders_live_agent_progress(self) -> None:
        output = StringIO()
        renderer = TerminalRenderer(output, width=60, use_color=False, preview_chars=90)
        stream = TerminalEventStream(renderer)
        stream.start(run_id="tui-equivalence", issue="Parser crashes when text is None.")

        demo = run_demo(stream)
        stream.finish(
            demo.result,
            final_diff=demo.final_diff,
            source_fixture_unchanged=demo.source_fixture_unchanged,
        )

        rendered = output.getvalue()
        self.assertIsNone(stream.render_error)
        self.assertIn("LocalCode", rendered)
        self.assertIn("Searching repository", rendered)
        self.assertIn("Reading file", rendered)
        self.assertIn("Editing", rendered)
        self.assertIn("patch files=1 +2 -0", rendered)
        self.assertIn("python-unittest exit=0 sandboxed", rendered)
        self.assertIn("Final answer ready", rendered)
        self.assertIn("Source fixture unchanged: True", rendered)

    def test_headless_and_terminal_view_share_exact_result_and_diff(self) -> None:
        headless = run_demo()
        output = StringIO()
        renderer = TerminalRenderer(output, width=60, use_color=False)
        stream = TerminalEventStream(renderer)
        stream.start(run_id="tui-equivalence", issue="Parser crashes when text is None.")

        terminal = run_demo(stream)
        stream.finish(terminal.result, final_diff=terminal.final_diff)

        self.assertEqual(
            tuple(event.to_json() for event in terminal.result.events),
            tuple(event.to_json() for event in headless.result.events),
        )
        self.assertEqual(terminal.result.observations, headless.result.observations)
        self.assertEqual(terminal.result.final_answer, headless.result.final_answer)
        self.assertEqual(terminal.final_diff, headless.final_diff)
        self.assertTrue(terminal.source_fixture_unchanged)


if __name__ == "__main__":
    unittest.main()
