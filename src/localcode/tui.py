"""Terminal rendering for LocalCode loop events and observations."""

from __future__ import annotations

from dataclasses import dataclass
from queue import SimpleQueue
from threading import Thread
from typing import TextIO

from .events import Event, EventType
from .loop import LoopResult, TerminationReason
from .tools import ToolResult


_STOP = object()


@dataclass(frozen=True, slots=True)
class TerminalLine:
    prefix: str
    text: str


class TerminalRenderer:
    """Render LocalCode traces without owning agent behavior."""

    def __init__(
        self,
        stream: TextIO,
        *,
        width: int = 72,
        use_color: bool | None = None,
        preview_chars: int = 180,
    ) -> None:
        if isinstance(width, bool) or width < 40:
            raise ValueError("width must be at least 40")
        if isinstance(preview_chars, bool) or preview_chars < 40:
            raise ValueError("preview_chars must be at least 40")
        self._stream = stream
        self._width = width
        self._use_color = stream.isatty() if use_color is None else use_color
        self._preview_chars = preview_chars

    def start(self, *, run_id: str, issue: str) -> None:
        self._write(f"┌─ LocalCode {self._rule(14)}")
        self._write(f"Run: {run_id}")
        self._write("")
        self._write("Issue:")
        self._write(_clip(issue.strip().replace("\n", " "), self._preview_chars))
        self._write(self._rule())

    def on_event(self, event: Event) -> None:
        line = _event_line(event)
        self._write(f"{line.prefix} {line.text}")

    def on_observation(self, observation: ToolResult) -> None:
        for line in _observation_lines(observation, self._preview_chars):
            self._write(f"  → {line}")

    def finish(
        self,
        result: LoopResult,
        *,
        final_diff: str | None = None,
        source_fixture_unchanged: bool | None = None,
    ) -> None:
        self._write(self._rule())
        if result.termination_reason is TerminationReason.FINAL_ANSWER:
            self._write(self._success("✓ Final answer ready"))
            if result.final_answer is not None:
                self._write(f"  {result.final_answer}")
        else:
            self._write(self._failure(f"✗ Stopped: {result.termination_reason.value}"))
        if final_diff is not None:
            changed_lines = sum(1 for line in final_diff.splitlines() if line.startswith(("+", "-")))
            self._write(f"Diff: {changed_lines} changed diff lines")
        if source_fixture_unchanged is not None:
            self._write(f"Source fixture unchanged: {source_fixture_unchanged}")
        self._write(
            f"Turns: {result.turns_used}  Tools: {result.tool_calls_used}  "
            f"Invalid: {result.invalid_actions_used}"
        )
        self._write("└" + "─" * (self._width - 1))

    def _write(self, line: str = "") -> None:
        print(line, file=self._stream, flush=True)

    def _rule(self, used: int = 0) -> str:
        return "─" * max(0, self._width - used)

    def _success(self, text: str) -> str:
        if not self._use_color:
            return text
        return f"\033[32m{text}\033[0m"

    def _failure(self, text: str) -> str:
        if not self._use_color:
            return text
        return f"\033[31m{text}\033[0m"


class TerminalEventStream:
    """Threaded observer that keeps terminal writes out of the agent loop."""

    def __init__(self, renderer: TerminalRenderer) -> None:
        self._renderer = renderer
        self._queue: SimpleQueue[tuple[str, object]] = SimpleQueue()
        self._thread = Thread(target=self._drain, name="localcode-tui", daemon=True)
        self.render_error: str | None = None
        self._started = False

    def start(self, *, run_id: str, issue: str) -> None:
        if self._started:
            raise RuntimeError("terminal event stream already started")
        self._renderer.start(run_id=run_id, issue=issue)
        self._started = True
        self._thread.start()

    def on_event(self, event: Event) -> None:
        self._queue.put(("event", event))

    def on_observation(self, observation: ToolResult) -> None:
        self._queue.put(("observation", observation))

    def finish(
        self,
        result: LoopResult,
        *,
        final_diff: str | None = None,
        source_fixture_unchanged: bool | None = None,
    ) -> None:
        if not self._started:
            raise RuntimeError("terminal event stream was not started")
        self._queue.put(("finish", (result, final_diff, source_fixture_unchanged)))
        self._queue.put(("stop", _STOP))
        self._thread.join(timeout=5)
        if self._thread.is_alive():
            self.render_error = "terminal event stream did not drain within 5 seconds"

    def _drain(self) -> None:
        while True:
            kind, payload = self._queue.get()
            if kind == "stop":
                return
            try:
                if kind == "event":
                    self._renderer.on_event(payload)  # type: ignore[arg-type]
                elif kind == "observation":
                    self._renderer.on_observation(payload)  # type: ignore[arg-type]
                elif kind == "finish":
                    result, final_diff, source_fixture_unchanged = payload  # type: ignore[misc]
                    self._renderer.finish(
                        result,
                        final_diff=final_diff,
                        source_fixture_unchanged=source_fixture_unchanged,
                    )
            except Exception as exc:
                self.render_error = str(exc)


def _event_line(event: Event) -> TerminalLine:
    if event.event_type is EventType.ACTION_ACCEPTED:
        return TerminalLine("◉", _accepted_action_text(event.summary))
    if event.event_type is EventType.TOOL_RESULT:
        return TerminalLine("✓", event.summary)
    if event.event_type in {EventType.ACTION_REJECTED, EventType.TOOL_ERROR}:
        return TerminalLine("!", event.summary)
    if event.event_type is EventType.FINAL_ANSWER:
        return TerminalLine("✓", "Final answer proposed")
    if event.event_type in {EventType.BACKEND_ERROR, EventType.REPEATED_ACTION, EventType.RUN_TERMINATED}:
        return TerminalLine("✗", event.summary)
    return TerminalLine("◉", event.summary)


def _accepted_action_text(summary: str) -> str:
    tool = summary.removeprefix("Accepted tool: ").removesuffix(".")
    labels = {
        "apply_patch": "Editing",
        "git_diff": "Reviewing diff",
        "list_files": "Listing files",
        "read_file": "Reading file",
        "run_tests": "Running tests",
        "search_code": "Searching repository",
    }
    return labels.get(tool, summary)


def _observation_lines(observation: ToolResult, preview_chars: int) -> tuple[str, ...]:
    metadata = observation.metadata_dict()
    if "code" in metadata:
        return (_clip(observation.content, preview_chars),)
    if "command" in metadata:
        timed = " timed_out" if metadata.get("timed_out") else ""
        sandboxed = " sandboxed" if metadata.get("sandboxed") else ""
        return (
            f"{metadata['command']} exit={metadata.get('exit_code')}{timed}{sandboxed}",
            _clip(observation.content.replace("\n", " "), preview_chars),
        )
    if {"file_count", "added_lines", "removed_lines"}.issubset(metadata):
        return (
            f"patch files={metadata['file_count']} +{metadata['added_lines']} -{metadata['removed_lines']}",
        )
    if {"file_count", "staged"}.issubset(metadata):
        suffix = " truncated" if observation.truncated else ""
        return (f"diff files={metadata['file_count']}{suffix}",)
    if observation.content:
        return (_clip(observation.content.replace("\n", " "), preview_chars),)
    return ("empty observation",)


def _clip(value: str, limit: int) -> str:
    text = " ".join(value.split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"
