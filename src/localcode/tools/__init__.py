"""Bounded read-only repository tools.

These functions inspect repository state but cannot edit files or run tests.
"""

from .base import ToolError, ToolResult
from .files import list_files, read_file
from .git import git_diff
from .search import search_code

__all__ = [
    "ToolError",
    "ToolResult",
    "git_diff",
    "list_files",
    "read_file",
    "search_code",
]
