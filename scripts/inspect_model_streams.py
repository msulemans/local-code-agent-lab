#!/usr/bin/env python3
"""Inspect preserved Ollama stream files from model compatibility runs.

Reconstructs the final message (content + tool_calls) from a stream JSONL and
prints a compact summary so the native tool-call shape can be compared with
what LocalCode's validator expects.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def summarize_stream(path: Path) -> None:
    print("=====", path)
    lines = path.read_text(encoding="utf-8").splitlines()
    print("lines:", len(lines))
    content_parts: list[str] = []
    tool_calls: list[object] = []
    last_msg_keys: list[str] = []
    for ln in lines:
        try:
            payload = json.loads(ln)
        except json.JSONDecodeError:
            continue
        message = payload.get("message", {})
        if not isinstance(message, dict):
            continue
        last_msg_keys = list(message.keys())
        content = message.get("content")
        if isinstance(content, str) and content:
            content_parts.append(content)
        calls = message.get("tool_calls")
        if calls:
            tool_calls.append(calls)
    print("final message keys:", last_msg_keys)
    print("content:", "".join(content_parts)[:500])
    if tool_calls:
        print("first tool_calls chunk:", json.dumps(tool_calls[0], indent=1)[:2000])
    else:
        print("NO tool_calls in stream")


def main() -> int:
    for pattern in sys.argv[1:]:
        for path in sorted(Path(".").glob(pattern)):
            summarize_stream(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
