#!/usr/bin/env python3
"""Create a disposable fixture workspace and apply one guarded patch."""

from __future__ import annotations

from pathlib import Path
import tempfile

from localcode.patches import apply_patch
from localcode.tools import git_diff
from localcode.workspace import create_workspace


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/micro_repos/parser_none"
PATCH = """diff --git a/src/tiny_parser.py b/src/tiny_parser.py
--- a/src/tiny_parser.py
+++ b/src/tiny_parser.py
@@ -1,2 +1,4 @@
 def parse_value(text: str | None) -> str:
+    if text is None:
+        return ""
     return text.strip()
"""


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="localcode-patch-demo-") as temporary:
        workspace = create_workspace(FIXTURE, Path(temporary) / "workspace")
        result = apply_patch(workspace.root, PATCH)
        diff = git_diff(workspace.root)
        print("WORKSPACE")
        print(workspace.root)
        print("PATCH RESULT")
        print(result.content)
        print("DIFF")
        print(diff.content)
        print("SOURCE FIXTURE UNCHANGED")
        print((FIXTURE / "src/tiny_parser.py").read_text(encoding="utf-8"), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
