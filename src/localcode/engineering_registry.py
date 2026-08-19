"""Exact capability registry for a disposable engineering workspace."""

from __future__ import annotations

from pathlib import PurePosixPath
import re
from typing import Callable

from .actions import ValidatedAction
from .patches import apply_patch
from .test_runner import TestRunner
from .tools import ToolError, ToolResult, git_diff, list_files, read_file, search_code
from .workspace import Workspace, edit_file, write_file


EngineeringTool = Callable[..., ToolResult]
_DIFF_PATH = re.compile(r"^diff --git a/([^\s]+) b/([^\s]+)$", re.MULTILINE)


class EngineeringToolRegistry:
    """Bind read, patch, test, and diff tools to one disposable workspace."""

    def __init__(self, workspace: Workspace, test_runner: TestRunner | None = None) -> None:
        self.workspace = workspace
        self._test_runner = TestRunner() if test_runner is None else test_runner
        self._tools: dict[str, EngineeringTool] = {
            "apply_patch": self._apply_patch,
            "edit_file": self._edit_file,
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

    def _edit_file(self, **arguments) -> ToolResult:
        return edit_file(self.workspace.root, **arguments)

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


class ToolSubsetRegistry:
    """Expose an exact treatment-specific subset of an existing registry."""

    def __init__(self, registry: EngineeringToolRegistry, allowed_tools: set[str]) -> None:
        unknown = allowed_tools.difference(registry.tool_names)
        if unknown:
            raise ValueError(f"tool subset contains unknown tools: {sorted(unknown)}")
        self._registry = registry
        self._tool_names = tuple(sorted(allowed_tools))

    @property
    def tool_names(self) -> tuple[str, ...]:
        return self._tool_names

    def execute(self, action: ValidatedAction) -> ToolResult:
        if action.tool not in self._tool_names:
            raise ValueError(f"validated action is outside the tool subset: {action.tool}")
        return self._registry.execute(action)


class ProductionReviewRegistry:
    """Keep tests readable and runnable while forbidding review-time test edits."""

    def __init__(self, registry: EngineeringToolRegistry) -> None:
        self._registry = registry

    @property
    def tool_names(self) -> tuple[str, ...]:
        return self._registry.tool_names

    def execute(self, action: ValidatedAction) -> ToolResult:
        arguments = action.arguments_dict()
        if action.tool in {"edit_file", "write_file"}:
            path = arguments.get("path")
            if isinstance(path, str) and _is_test_path(path):
                raise ToolError(
                    "review_test_edit_forbidden",
                    "review may read and run tests but must repair production code, not edit tests",
                )
        elif action.tool == "apply_patch":
            patch = arguments.get("patch")
            if isinstance(patch, str) and any(
                _is_test_path(path)
                for pair in _DIFF_PATH.findall(patch)
                for path in pair
            ):
                raise ToolError(
                    "review_test_edit_forbidden",
                    "review patch may not modify test files",
                )
        return self._registry.execute(action)


def _is_test_path(path: str) -> bool:
    parts = PurePosixPath(path).parts
    name = parts[-1].casefold() if parts else ""
    return (
        any(part.casefold() in {"test", "tests"} for part in parts[:-1])
        or name.startswith("test_")
        or name.endswith("_test.py")
        or name in {"conftest.py", "test_requests.py"}
    )
