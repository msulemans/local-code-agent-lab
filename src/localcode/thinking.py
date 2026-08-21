"""A loop-backend decorator that surfaces the model's reasoning per turn.

The wrapped backend's returned envelope is passed through unchanged; the
controller remains the validating authority. ``thought_summary`` is present in
every LocalCode decision envelope and is surfaced per turn. When the wrapped
backend exposes a richer ``last_reasoning`` (the OpenAI Responses backend
captures provider reasoning summaries), that text is surfaced instead.
"""

from __future__ import annotations

import json
from typing import Any, Callable

from .loop import LoopRequest


def extract_thought(payload: str) -> str | None:
    """Return the envelope's ``thought_summary`` when the payload is an envelope."""
    try:
        value = json.loads(payload)
    except json.JSONDecodeError:
        return None
    if not isinstance(value, dict):
        return None
    thought = value.get("thought_summary")
    if isinstance(thought, str) and thought.strip():
        return thought.strip()
    return None


class ThinkingBackend:
    """Wrap any loop backend and report the model's reasoning to a callback."""

    def __init__(
        self,
        backend: Any,
        *,
        on_thought: Callable[[str, LoopRequest], None] | None = None,
    ) -> None:
        if on_thought is not None and not callable(on_thought):
            raise ValueError("on_thought must be callable")
        self._backend = backend
        self._on_thought = on_thought or (lambda thought, request: None)
        # Observability: the last request/context the model saw, so the chat
        # UI can show exactly what was sent (D-059).
        self.last_request: LoopRequest | None = None
        self.last_context: str | None = None

    def complete(self, request: LoopRequest) -> str:
        self.last_request = request
        self.last_context = request.context
        payload = self._backend.complete(request)
        reasoning = getattr(self._backend, "last_reasoning", None)
        if isinstance(reasoning, str) and reasoning.strip():
            self._on_thought(reasoning, request)
        else:
            thought = extract_thought(payload)
            if thought is not None:
                self._on_thought(thought, request)
        return payload

    def __getattr__(self, name: str) -> Any:
        # Proxy counters and any other state (generated_tokens, input_tokens,
        # last_reasoning, ...) to the wrapped backend.
        return getattr(self._backend, name)
