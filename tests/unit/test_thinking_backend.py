from __future__ import annotations

import unittest

from localcode.loop import LoopRequest
from localcode.thinking import ThinkingBackend, extract_thought


def request(*tools: str) -> LoopRequest:
    return LoopRequest(
        issue="Fix parser",
        context='{"issue":"Fix parser"}',
        allowed_tools=tools,
        turn_index=0,
        budgets_remaining=(("turns", 3),),
    )


class _FakeBackend:
    def __init__(self, payload, *, last_reasoning=""):
        self._payload = payload
        self.last_reasoning = last_reasoning
        self.generated_tokens = 42
        self.calls = 0

    def complete(self, request):
        self.calls += 1
        return self._payload


class ExtractThoughtTests(unittest.TestCase):
    def test_envelope_thought_is_extracted(self) -> None:
        payload = (
            '{"protocol_version":"1","thought_summary":"Read the file first.",'
            '"decision":{"kind":"tool","tool":"read_file","arguments":{"path":"a.py"}}}'
        )
        self.assertEqual(extract_thought(payload), "Read the file first.")

    def test_non_envelope_payload_returns_none(self) -> None:
        self.assertIsNone(extract_thought("not json at all"))
        self.assertIsNone(extract_thought('{"no_thought":true}'))


class ThinkingBackendTests(unittest.TestCase):
    def test_reports_thought_and_passes_payload_through(self) -> None:
        payload = (
            '{"protocol_version":"1","thought_summary":"The boundary is wrong.",'
            '"decision":{"kind":"tool","tool":"edit_file","arguments":{}}}'
        )
        seen: list[tuple[str, LoopRequest]] = []
        backend = ThinkingBackend(_FakeBackend(payload), on_thought=lambda t, r: seen.append((t, r)))

        returned = backend.complete(request("edit_file"))

        self.assertEqual(returned, payload)
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0][0], "The boundary is wrong.")
        self.assertEqual(seen[0][1].issue, "Fix parser")

    def test_prefers_backend_last_reasoning_over_envelope_thought(self) -> None:
        payload = (
            '{"protocol_version":"1","thought_summary":"generic",'
            '"decision":{"kind":"tool","tool":"read_file","arguments":{}}}'
        )
        seen: list[str] = []
        backend = ThinkingBackend(
            _FakeBackend(payload, last_reasoning="provider reasoning text"),
            on_thought=lambda t, r: seen.append(t),
        )

        backend.complete(request("read_file"))

        self.assertEqual(seen, ["provider reasoning text"])

    def test_proxies_counters_to_the_wrapped_backend(self) -> None:
        wrapped = _FakeBackend("{}")
        backend = ThinkingBackend(wrapped)
        self.assertEqual(backend.generated_tokens, 42)
        self.assertEqual(backend.calls, 0)  # reads attribute, not complete()

    def test_no_thought_does_not_call_callback(self) -> None:
        seen: list[str] = []
        backend = ThinkingBackend(_FakeBackend("plain text"), on_thought=lambda t, r: seen.append(t))
        backend.complete(request("read_file"))
        self.assertEqual(seen, [])


if __name__ == "__main__":
    unittest.main()
