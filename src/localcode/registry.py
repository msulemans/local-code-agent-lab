"""Exact dispatch table for LocalCode's read-only tools."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from .actions import ValidatedAction
from .tools import ToolResult, git_diff, list_files, read_file, search_code


ReadOnlyTool = Callable[..., ToolResult]


class ToolRegistry:
    """Bind validated action names to tools at one repository root."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self._tools: dict[str, ReadOnlyTool] = {
            "git_diff": git_diff,
            "list_files": list_files,
            "read_file": read_file,
            "search_code": search_code,
        }

    @property
    def tool_names(self) -> tuple[str, ...]:
        return tuple(sorted(self._tools))

    def execute(self, action: ValidatedAction) -> ToolResult:
        tool = self._tools.get(action.tool)
        if tool is None:
            raise ValueError(f"validated action references unregistered tool: {action.tool}")
        return tool(self.root, **action.arguments_dict())
