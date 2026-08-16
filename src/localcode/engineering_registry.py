"""Exact capability registry for a disposable engineering workspace."""

from __future__ import annotations

from typing import Callable

from .actions import ValidatedAction
from .patches import apply_patch
from .test_runner import TestRunner
from .tools import ToolResult, git_diff, list_files, read_file, search_code
from .workspace import Workspace, write_file


EngineeringTool = Callable[..., ToolResult]


class EngineeringToolRegistry:
    """Bind read, patch, test, and diff tools to one disposable workspace."""

    def __init__(self, workspace: Workspace, test_runner: TestRunner | None = None) -> None:
        self.workspace = workspace
        self._test_runner = TestRunner() if test_runner is None else test_runner
        self._tools: dict[str, EngineeringTool] = {
            "apply_patch": self._apply_patch,
            "git_diff": self._git_diff,
            "list_files": self._list_files,
            "read_file": self._read_file,
            "run_tests": self._run_tests,
            "search_code": self._search_code,
            "write_file": self._write_file,
        }

    @property
    def tool_names(self) -> tuple[str, ...]:
        return tuple(sorted(self._tools))

    def execute(self, action: ValidatedAction) -> ToolResult:
        tool = self._tools.get(action.tool)
        if tool is None:
            raise ValueError(f"validated action references unregistered tool: {action.tool}")
        return tool(**action.arguments_dict())

    def _apply_patch(self, **arguments) -> ToolResult:
        return apply_patch(self.workspace.root, **arguments)

    def _write_file(self, **arguments) -> ToolResult:
        return write_file(self.workspace.root, **arguments)

    def _run_tests(self, **arguments) -> ToolResult:
        return self._test_runner.run(self.workspace, **arguments)

    def _git_diff(self, **arguments) -> ToolResult:
        return git_diff(self.workspace.root, **arguments)

    def _list_files(self, **arguments) -> ToolResult:
        return list_files(self.workspace.root, **arguments)

    def _read_file(self, **arguments) -> ToolResult:
        return read_file(self.workspace.root, **arguments)

    def _search_code(self, **arguments) -> ToolResult:
        return search_code(self.workspace.root, **arguments)
