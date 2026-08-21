"""OpenAI Responses API adapter for one bounded LocalCode loop decision."""

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


class ResponsesClient(Protocol):
    def create_response(self, payload: dict[str, Any]) -> dict[str, Any]: ...


class OpenAIResponsesClient:
    """Small dependency-free client that never persists or exposes the API key."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str = "https://api.openai.com/v1",
        timeout_seconds: float = 300.0,
    ) -> None:
        key = os.environ.get("OPENAI_API_KEY") if api_key is None else api_key
        if not isinstance(key, str) or not key.strip():
            raise ValueError("OPENAI_API_KEY is required for the OpenAI backend")
        if base_url.rstrip("/") != "https://api.openai.com/v1":
            raise ValueError("OpenAI base URL must be https://api.openai.com/v1")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._api_key = key.strip()
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds

    def create_response(self, payload: dict[str, Any]) -> dict[str, Any]:
        request = Request(
            self._base_url + "/responses",
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
            raise BackendError(f"OpenAI Responses API returned HTTP {exc.code}") from exc
        except URLError as exc:
            raise BackendError("could not reach the OpenAI Responses API") from exc
        except (OSError, json.JSONDecodeError) as exc:
            raise BackendError("OpenAI Responses API returned an unreadable response") from exc
        if not isinstance(result, dict):
            raise BackendError("OpenAI Responses API response must be a JSON object")
        return result


class OpenAIResponsesLoopBackend:
    """Translate one Responses API result into LocalCode protocol v1."""

    def __init__(
        self,
        *,
        model: str,
        tool_document: dict[str, Any],
        client: ResponsesClient | None = None,
        max_output_tokens: int = 2_048,
        reasoning_effort: str = "medium",
        allow_tool_subsets: bool = False,
        system_prompt: str | None = None,
    ) -> None:
        if not isinstance(model, str) or not model or any(c.isspace() for c in model):
            raise ValueError("model must be a non-empty model ID without whitespace")
        if isinstance(max_output_tokens, bool) or not isinstance(max_output_tokens, int) or max_output_tokens < 1:
            raise ValueError("max_output_tokens must be a positive integer")
        if reasoning_effort not in {"low", "medium", "high", "xhigh"}:
            raise ValueError("reasoning_effort must be low, medium, high, or xhigh")
        if system_prompt is not None and (not isinstance(system_prompt, str) or not system_prompt.strip()):
            raise ValueError("system_prompt must be non-empty text")

        tools_by_name = schema_map(tool_document)
        self.model = model
        self.tool_names = tuple(sorted(tools_by_name))
        self._tools = _responses_tools(tool_document)
        self._client = OpenAIResponsesClient() if client is None else client
        self._max_output_tokens = max_output_tokens
        self._reasoning_effort = reasoning_effort
        self._allow_tool_subsets = allow_tool_subsets
        self._system_prompt = LOOP_SYSTEM_PROMPT if system_prompt is None else system_prompt
        self._generated_tokens = 0
        self._input_tokens = 0
        self._last_reasoning = ""

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
        result = self._client.create_response(
            {
                "model": self.model,
                "instructions": self._system_prompt,
                "input": request.context,
                "tools": [tool for tool in self._tools if tool["name"] in allowed],
                "tool_choice": "auto",
                "parallel_tool_calls": False,
                "reasoning": {"effort": self._reasoning_effort},
                "max_output_tokens": self._max_output_tokens,
                "store": False,
            }
        )
        self._record_usage(result.get("usage"))
        # Reasoning summaries are surfaced for the chat UI; they never change
        # the returned decision envelope (the controller stays authoritative).
        self._last_reasoning = _reasoning_text(result.get("output"))
        payload = _protocol_payload(result)
        _write_trace(request, result, payload)
        return payload

    @property
    def last_reasoning(self) -> str:
        """The model's latest reasoning summary, if the provider returned one."""
        return self._last_reasoning

    def _record_usage(self, usage: object) -> None:
        if not isinstance(usage, dict):
            return
        input_tokens = usage.get("input_tokens", 0)
        output_tokens = usage.get("output_tokens", 0)
        if isinstance(input_tokens, int) and not isinstance(input_tokens, bool) and input_tokens >= 0:
            self._input_tokens += input_tokens
        if isinstance(output_tokens, int) and not isinstance(output_tokens, bool) and output_tokens >= 0:
            self._generated_tokens += output_tokens

    @property
    def generated_tokens(self) -> int:
        return self._generated_tokens

    @property
    def input_tokens(self) -> int:
        return self._input_tokens


def _responses_tools(document: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert Chat-style function schemas into Responses API function tools."""
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
                "name": name,
                "description": function.get("description", ""),
                "parameters": parameters,
                # LocalCode's validator remains authoritative. Some existing
                # schemas intentionally have optional arguments with defaults,
                # so strict provider validation cannot be enabled yet.
                "strict": False,
            }
        )
    return json.loads(json.dumps(converted, sort_keys=True, separators=(",", ":")))


def _protocol_payload(result: dict[str, Any]) -> str:
    output = result.get("output")
    if not isinstance(output, list):
        raise BackendError("OpenAI Responses API output must be a list")
    calls = [item for item in output if isinstance(item, dict) and item.get("type") == "function_call"]
    text = _output_text(output)
    if not calls:
        if not text or len(text) > 4_000:
            return text
        return json.dumps(
            {
                "protocol_version": "1",
                "thought_summary": "Model returned a final response.",
                "decision": {"kind": "final", "answer": text},
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    if len(calls) != 1:
        return text
    call = calls[0]
    name = call.get("name")
    arguments_text = call.get("arguments")
    if not isinstance(name, str) or not isinstance(arguments_text, str):
        return text
    try:
        arguments = json.loads(arguments_text)
    except json.JSONDecodeError:
        return text
    if not isinstance(arguments, dict):
        return text
    return json.dumps(
        {
            "protocol_version": "1",
            "thought_summary": "Model proposed one native tool call.",
            "decision": {"kind": "tool", "tool": name, "arguments": arguments},
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def _write_trace(request: LoopRequest, result: dict[str, Any], payload: str) -> None:
    """Append one bounded decision to the optional LOCALCODE_TRACE_PATH file."""
    trace_path = os.environ.get("LOCALCODE_TRACE_PATH")
    if not trace_path:
        return
    output = result.get("output")
    content = json.dumps(output, sort_keys=True) if output is not None else ""
    with Path(trace_path).open("a", encoding="utf-8") as trace:
        trace.write(
            json.dumps(
                {
                    "turn": request.turn_index,
                    "context_tail": request.context[-1200:],
                    "content": content[:2000],
                    "payload": payload,
                },
                sort_keys=True,
            )
            + "\n"
        )


def _reasoning_text(output: object) -> str:
    """Extract provider reasoning summaries without changing the decision."""
    if not isinstance(output, list):
        return ""
    parts: list[str] = []
    for item in output:
        if not isinstance(item, dict) or item.get("type") != "reasoning":
            continue
        summary = item.get("summary")
        if not isinstance(summary, list):
            continue
        for block in summary:
            if isinstance(block, dict) and block.get("type") == "summary_text":
                value = block.get("text")
                if isinstance(value, str) and value.strip():
                    parts.append(value.strip())
    return "\n".join(parts)


def _output_text(output: list[object]) -> str:
    parts: list[str] = []
    for item in output:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "output_text":
                value = block.get("text")
                if isinstance(value, str):
                    parts.append(value)
    return "".join(parts).strip()
