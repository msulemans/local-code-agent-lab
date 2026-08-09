"""Compatibility-only Ollama transport and deterministic response scoring."""

from __future__ import annotations

from dataclasses import dataclass
import json
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


class CompatibilityError(RuntimeError):
    """A bounded model compatibility failure."""


@dataclass(frozen=True, slots=True)
class ChatResult:
    content: str
    thinking: str
    tool_calls: tuple[dict[str, Any], ...]
    prompt_eval_count: int
    prompt_eval_duration_ns: int
    eval_count: int
    eval_duration_ns: int
    load_duration_ns: int
    total_duration_ns: int
    time_to_first_output_seconds: float
    wall_seconds: float
    chunks: tuple[dict[str, Any], ...]

    @property
    def output_tokens_per_second(self) -> float | None:
        if self.eval_count <= 0 or self.eval_duration_ns <= 0:
            return None
        return self.eval_count * 1_000_000_000 / self.eval_duration_ns

    @property
    def prompt_tokens_per_second(self) -> float | None:
        if self.prompt_eval_count <= 0 or self.prompt_eval_duration_ns <= 0:
            return None
        return self.prompt_eval_count * 1_000_000_000 / self.prompt_eval_duration_ns

    def summary_dict(self) -> dict[str, Any]:
        return {
            "content": self.content,
            "thinking": self.thinking,
            "tool_calls": list(self.tool_calls),
            "prompt_eval_count": self.prompt_eval_count,
            "prompt_eval_duration_ns": self.prompt_eval_duration_ns,
            "prompt_tokens_per_second": self.prompt_tokens_per_second,
            "eval_count": self.eval_count,
            "eval_duration_ns": self.eval_duration_ns,
            "output_tokens_per_second": self.output_tokens_per_second,
            "load_duration_ns": self.load_duration_ns,
            "total_duration_ns": self.total_duration_ns,
            "time_to_first_output_seconds": self.time_to_first_output_seconds,
            "wall_seconds": self.wall_seconds,
        }


class OllamaClient:
    """Small standard-library client restricted to a loopback Ollama server."""

    def __init__(self, base_url: str = "http://127.0.0.1:11434", timeout_seconds: float = 180.0) -> None:
        parsed = urlparse(base_url)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("Ollama base URL must be an HTTP loopback address")
        if parsed.path not in {"", "/"} or parsed.query or parsed.fragment or parsed.username:
            raise ValueError("Ollama base URL must not contain path, credentials, query, or fragment")
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def _request(self, path: str, *, body: dict[str, Any] | None = None):
        data = None if body is None else json.dumps(body, separators=(",", ":")).encode("utf-8")
        request = Request(
            self.base_url + path,
            data=data,
            headers={"Content-Type": "application/json"},
            method="GET" if data is None else "POST",
        )
        try:
            return urlopen(request, timeout=self.timeout_seconds)
        except HTTPError as error:
            detail = error.read(4_096).decode("utf-8", errors="replace")
            raise CompatibilityError(f"Ollama HTTP {error.code}: {detail}") from error
        except URLError as error:
            raise CompatibilityError(f"cannot reach Ollama at {self.base_url}: {error.reason}") from error

    def running_models(self) -> list[dict[str, Any]]:
        with self._request("/api/ps") as response:
            try:
                payload = json.load(response)
            except json.JSONDecodeError as error:
                raise CompatibilityError("Ollama /api/ps returned invalid JSON") from error
        models = payload.get("models") if isinstance(payload, dict) else None
        if not isinstance(models, list) or any(not isinstance(model, dict) for model in models):
            raise CompatibilityError("Ollama /api/ps returned an invalid models list")
        return models

    def stream_chat(self, payload: dict[str, Any]) -> ChatResult:
        if payload.get("stream") is not True:
            raise ValueError("compatibility requests must stream")
        start = time.monotonic()
        first_output: float | None = None
        chunks: list[dict[str, Any]] = []
        content_parts: list[str] = []
        thinking_parts: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        final: dict[str, Any] | None = None

        with self._request("/api/chat", body=payload) as response:
            for raw_line in response:
                if not raw_line.strip():
                    continue
                try:
                    chunk = json.loads(raw_line)
                except json.JSONDecodeError as error:
                    raise CompatibilityError("Ollama stream contained invalid JSON") from error
                if not isinstance(chunk, dict):
                    raise CompatibilityError("Ollama stream chunks must be JSON objects")
                chunks.append(chunk)
                if "error" in chunk:
                    raise CompatibilityError(f"Ollama generation error: {chunk['error']}")
                message = chunk.get("message", {})
                if not isinstance(message, dict):
                    raise CompatibilityError("Ollama message must be an object")
                content = message.get("content", "")
                thinking = message.get("thinking", "")
                calls = message.get("tool_calls", [])
                if not isinstance(content, str) or not isinstance(thinking, str) or not isinstance(calls, list):
                    raise CompatibilityError("Ollama message fields have invalid types")
                if content or thinking or calls:
                    if first_output is None:
                        first_output = time.monotonic()
                    content_parts.append(content)
                    thinking_parts.append(thinking)
                    for call in calls:
                        if not isinstance(call, dict):
                            raise CompatibilityError("Ollama tool calls must be objects")
                        tool_calls.append(call)
                if chunk.get("done") is True:
                    final = chunk

        end = time.monotonic()
        if final is None:
            raise CompatibilityError("Ollama stream ended without a done chunk")
        if first_output is None:
            first_output = end

        def metric(name: str) -> int:
            value = final.get(name, 0)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise CompatibilityError(f"Ollama metric {name} must be a non-negative integer")
            return value

        return ChatResult(
            content="".join(content_parts),
            thinking="".join(thinking_parts),
            tool_calls=tuple(tool_calls),
            prompt_eval_count=metric("prompt_eval_count"),
            prompt_eval_duration_ns=metric("prompt_eval_duration"),
            eval_count=metric("eval_count"),
            eval_duration_ns=metric("eval_duration"),
            load_duration_ns=metric("load_duration"),
            total_duration_ns=metric("total_duration"),
            time_to_first_output_seconds=first_output - start,
            wall_seconds=end - start,
            chunks=tuple(chunks),
        )


def schema_map(tool_document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    tools = tool_document.get("tools")
    if not isinstance(tools, list):
        raise ValueError("tool document must contain a tools list")
    result: dict[str, dict[str, Any]] = {}
    for tool in tools:
        function = tool.get("function") if isinstance(tool, dict) else None
        if not isinstance(function, dict) or not isinstance(function.get("name"), str):
            raise ValueError("invalid function tool schema")
        result[function["name"]] = function
    return result


def _matches_type(value: Any, expected: str) -> bool:
    if expected == "null":
        return value is None
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "object":
        return isinstance(value, dict)
    return False


def arguments_match_schema(arguments: Any, function_schema: dict[str, Any]) -> bool:
    if not isinstance(arguments, dict):
        return False
    parameters = function_schema.get("parameters", {})
    properties = parameters.get("properties", {})
    required = parameters.get("required", [])
    if not isinstance(properties, dict) or not isinstance(required, list):
        return False
    if any(name not in arguments for name in required):
        return False
    if parameters.get("additionalProperties") is False and any(name not in properties for name in arguments):
        return False
    for name, value in arguments.items():
        rule = properties.get(name)
        if not isinstance(rule, dict):
            return False
        types = rule.get("type")
        allowed_types = [types] if isinstance(types, str) else types
        if not isinstance(allowed_types, list) or not any(_matches_type(value, item) for item in allowed_types):
            return False
        if isinstance(value, int) and not isinstance(value, bool):
            if "minimum" in rule and value < rule["minimum"]:
                return False
            if "maximum" in rule and value > rule["maximum"]:
                return False
        if isinstance(value, str):
            if "minLength" in rule and len(value) < rule["minLength"]:
                return False
            if "maxLength" in rule and len(value) > rule["maxLength"]:
                return False
    return True


def _normalized_call(call: dict[str, Any]) -> tuple[str | None, Any]:
    function = call.get("function")
    if not isinstance(function, dict):
        return None, None
    return function.get("name"), function.get("arguments")


def score_prompt(prompt: dict[str, Any], result: ChatResult, tools_by_name: dict[str, dict[str, Any]]) -> dict[str, Any]:
    expected = prompt["expected"]
    kind = expected["kind"]
    calls = result.tool_calls
    score: dict[str, Any] = {
        "id": prompt["id"],
        "category": prompt["category"],
        "expected_kind": kind,
        "tool_call_count": len(calls),
        "schema_valid": None,
        "decision_correct": None,
        "reasoning_correct": None,
    }

    if kind == "tool":
        valid = False
        correct = False
        if len(calls) == 1:
            name, arguments = _normalized_call(calls[0])
            function_schema = tools_by_name.get(name) if isinstance(name, str) else None
            valid = function_schema is not None and arguments_match_schema(arguments, function_schema)
            correct = valid and name == expected["name"] and arguments == expected["arguments"]
        score["schema_valid"] = valid
        score["decision_correct"] = correct
    elif kind == "no_tool":
        lowered = result.content.casefold()
        score["decision_correct"] = not calls and any(term.casefold() in lowered for term in expected["must_mention_any"])
    elif kind == "answer":
        score["reasoning_correct"] = not calls and result.content.strip() == expected["exact"]
    else:
        raise ValueError(f"unsupported expected kind: {kind}")
    return score
