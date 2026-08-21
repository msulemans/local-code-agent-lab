"""OpenAI-compatible Chat Completions adapter for one bounded LocalCode decision.

This is the bring-your-own-key (BYOK) transport. It speaks the widely
supported ``/chat/completions`` shape, so any provider that implements the
OpenAI-compatible function-calling contract can serve LocalCode decisions:
OpenAI itself, OpenRouter, Groq, Together, LM Studio, vLLM, and others. The
adapter deliberately knows nothing about repositories or tools. It only turns
one ``LoopRequest`` into a chat prompt and converts the model's response back
into the versioned LocalCode decision envelope. The controller remains the
authority that validates and executes the decision.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ..compatibility import schema_map
from ..loop import LoopRequest
from .ollama import BackendError
from .ollama_loop import LOOP_SYSTEM_PROMPT


class ChatClient(Protocol):
    def create_chat_completion(self, payload: dict[str, Any]) -> dict[str, Any]: ...


class OpenAIChatClient:
    """Small dependency-free client that never persists or exposes the API key."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        api_key_env: str = "OPENAI_API_KEY",
        base_url: str = "https://api.openai.com/v1",
        timeout_seconds: float = 300.0,
    ) -> None:
        if not isinstance(api_key_env, str) or not api_key_env or any(c.isspace() for c in api_key_env):
            raise ValueError("api_key_env must be a non-empty environment variable name")
        key = os.environ.get(api_key_env) if api_key is None else api_key
        if not isinstance(key, str) or not key.strip():
            raise ValueError(
                f"environment variable {api_key_env!r} is not set. "
                f"Set it with `export {api_key_env}=<your-key>` before running; "
                "--api-key-env expects the NAME of an environment variable "
                "(e.g. DS_KEY), not the key value itself."
            )
        base = base_url.rstrip("/")
        if not base.startswith("https://"):
            raise ValueError("base_url must be an https endpoint")
        if isinstance(timeout_seconds, bool) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._api_key = key.strip()
        self._base_url = base
        self._timeout_seconds = timeout_seconds

    def create_chat_completion(self, payload: dict[str, Any]) -> dict[str, Any]:
        request = Request(
            self._base_url + "/chat/completions",
            data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                result = json.load(response)
        except HTTPError as exc:
            # Do not echo provider response bodies: they are untrusted and can
            # contain request details. The status is enough for diagnostics.
            raise BackendError(f"OpenAI-compatible API returned HTTP {exc.code}") from exc
        except URLError as exc:
            raise BackendError("could not reach the OpenAI-compatible API") from exc
        except (OSError, json.JSONDecodeError) as exc:
            raise BackendError("OpenAI-compatible API returned an unreadable response") from exc
        if not isinstance(result, dict):
            raise BackendError("OpenAI-compatible API response must be a JSON object")
        return result


class OpenAIChatLoopBackend:
    """Translate one Chat Completions result into LocalCode protocol v1."""

    def __init__(
        self,
        *,
        model: str,
        tool_document: dict[str, Any],
        client: ChatClient | None = None,
        base_url: str = "https://api.openai.com/v1",
        api_key_env: str = "OPENAI_API_KEY",
        max_output_tokens: int = 2_048,
        temperature: float = 0.0,
        allow_tool_subsets: bool = False,
        system_prompt: str | None = None,
    ) -> None:
        if not isinstance(model, str) or not model or any(c.isspace() for c in model):
            raise ValueError("model must be a non-empty model ID without whitespace")
        if isinstance(max_output_tokens, bool) or not isinstance(max_output_tokens, int) or max_output_tokens < 1:
            raise ValueError("max_output_tokens must be a positive integer")
        if isinstance(temperature, bool) or not isinstance(temperature, (int, float)) or not 0.0 <= temperature <= 2.0:
            raise ValueError("temperature must be a number between 0 and 2")
        if not isinstance(allow_tool_subsets, bool):
            raise ValueError("allow_tool_subsets must be a boolean")
        if system_prompt is not None and (not isinstance(system_prompt, str) or not system_prompt.strip()):
            raise ValueError("system_prompt must be non-empty text")

        tools_by_name = schema_map(tool_document)
        self.model = model
        self.tool_names = tuple(sorted(tools_by_name))
        self._tools = _chat_tools(tool_document)
        self._client = (
            OpenAIChatClient(base_url=base_url, api_key_env=api_key_env)
            if client is None
            else client
        )
        self._max_output_tokens = max_output_tokens
        self._temperature = temperature
        self._allow_tool_subsets = allow_tool_subsets
        self._system_prompt = LOOP_SYSTEM_PROMPT if system_prompt is None else system_prompt
        self._generated_tokens = 0
        self._input_tokens = 0
        self._cache_hit_tokens = 0
        self._cache_miss_tokens = 0

    def complete(self, request: LoopRequest) -> str:
        if request.protocol_version != "1":
            raise BackendError(f"unsupported request protocol: {request.protocol_version!r}")
        if self._allow_tool_subsets:
            valid_surface = set(request.allowed_tools).issubset(self.tool_names)
        else:
            valid_surface = tuple(sorted(request.allowed_tools)) == self.tool_names
        if not valid_surface:
            raise BackendError("controller requested an unknown tool surface")

        allowed = set(request.allowed_tools)
        result = self._client.create_chat_completion(
            {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": self._system_prompt},
                    {"role": "user", "content": request.context},
                ],
                "tools": [tool for tool in self._tools if tool["function"]["name"] in allowed],
                "tool_choice": "auto",
                # LocalCode's controller is strict: one validated decision per
                # turn, and a multi-tool response is never silently pruned to
                # one call. Providers such as DeepSeek parallelize tool calls
                # by default, so request a single call explicitly (D-055).
                "parallel_tool_calls": False,
                "temperature": self._temperature,
                "max_tokens": self._max_output_tokens,
                "stream": False,
            }
        )
        self._record_usage(result.get("usage"))
        payload = _chat_payload(result)
        _write_trace(request, result, payload)
        return payload

    def _record_usage(self, usage: object) -> None:
        if not isinstance(usage, dict):
            return
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)
        if isinstance(prompt_tokens, int) and not isinstance(prompt_tokens, bool) and prompt_tokens >= 0:
            self._input_tokens += prompt_tokens
        if isinstance(completion_tokens, int) and not isinstance(completion_tokens, bool) and completion_tokens >= 0:
            self._generated_tokens += completion_tokens
        # Prompt cache accounting: DeepSeek reports prompt_cache_hit_tokens /
        # prompt_cache_miss_tokens; OpenAI reports prompt_tokens_details.
        hit = usage.get("prompt_cache_hit_tokens", 0)
        miss = usage.get("prompt_cache_miss_tokens", 0)
        details = usage.get("prompt_tokens_details")
        if isinstance(details, dict) and isinstance(details.get("cached_tokens"), int) and not isinstance(details.get("cached_tokens"), bool):
            hit = details["cached_tokens"]
        if isinstance(hit, int) and not isinstance(hit, bool) and hit >= 0:
            self._cache_hit_tokens += hit
        if isinstance(miss, int) and not isinstance(miss, bool) and miss >= 0:
            self._cache_miss_tokens += miss

    @property
    def generated_tokens(self) -> int:
        return self._generated_tokens

    @property
    def input_tokens(self) -> int:
        return self._input_tokens

    @property
    def cache_hit_tokens(self) -> int:
        return self._cache_hit_tokens

    @property
    def cache_miss_tokens(self) -> int:
        return self._cache_miss_tokens


def _chat_tools(document: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert Chat-style function schemas into Chat Completions function tools."""
    tools = document.get("tools")
    if not isinstance(tools, list):
        raise ValueError("tool document must contain a tools list")
    converted = []
    for tool in tools:
        function = tool.get("function") if isinstance(tool, dict) else None
        if not isinstance(function, dict):
            raise ValueError("invalid function tool schema")
        name = function.get("name")
        parameters = function.get("parameters")
        if not isinstance(name, str) or not isinstance(parameters, dict):
            raise ValueError("invalid function tool schema")
        converted.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": function.get("description", ""),
                    "parameters": parameters,
                },
            }
        )
    return json.loads(json.dumps(converted, sort_keys=True, separators=(",", ":")))


def _chat_payload(result: dict[str, Any]) -> str:
    """Convert one non-streamed Chat Completions response to the decision envelope."""
    choices = result.get("choices")
    if not isinstance(choices, list) or not choices:
        raise BackendError("OpenAI-compatible API response has no choices")
    message = choices[0].get("message")
    if not isinstance(message, dict):
        raise BackendError("OpenAI-compatible API message must be an object")
    content = message.get("content")
    text = _content_text(content)
    calls = message.get("tool_calls")
    if not calls:
        if not text:
            return ""
        if len(text) > 4_000:
            text = text[:4_000] + "…"
        return json.dumps(
            {
                "protocol_version": "1",
                "thought_summary": "Model returned a final response.",
                "decision": {"kind": "final", "answer": text},
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    if not isinstance(calls, list) or not calls:
        return text
    # Providers such as DeepSeek parallelize tool calls by default and may
    # return several in one response even when parallel_tool_calls is false.
    # LocalCode's controller accepts exactly one decision per turn, so the
    # transport maps the provider response to the model's primary (first)
    # well-formed call; the controller still validates every argument, so no
    # action bypasses the tool schema (D-055).
    for call in calls:
        function = call.get("function") if isinstance(call, dict) else None
        if not isinstance(function, dict):
            continue
        name = function.get("name")
        arguments_text = function.get("arguments")
        if not isinstance(name, str) or not isinstance(arguments_text, str):
            continue
        try:
            arguments = json.loads(arguments_text)
        except json.JSONDecodeError:
            continue
        if not isinstance(arguments, dict):
            continue
        return json.dumps(
            {
                "protocol_version": "1",
                "thought_summary": "Model proposed one native tool call.",
                "decision": {"kind": "tool", "tool": name, "arguments": arguments},
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    return text


def _content_text(content: object) -> str:
    """Extract plain text from either a string or an array of content parts."""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
        return "".join(parts).strip()
    return ""


def _write_trace(request: LoopRequest, result: dict[str, Any], payload: str) -> None:
    """Append one bounded decision to the optional LOCALCODE_TRACE_PATH file."""
    trace_path = os.environ.get("LOCALCODE_TRACE_PATH")
    if not trace_path:
        return
    with Path(trace_path).open("a", encoding="utf-8") as trace:
        trace.write(
            json.dumps(
                {
                    "turn": request.turn_index,
                    "context_tail": request.context[-1200:],
                    "content": json.dumps(result, sort_keys=True)[:2000],
                    "payload": payload,
                },
                sort_keys=True,
            )
            + "\n"
        )
