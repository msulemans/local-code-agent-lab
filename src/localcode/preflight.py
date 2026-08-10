"""Pure validation for a clean, unloaded real-model smoke baseline."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Sequence


_SWAP_USED = re.compile(r"\bused\s*=\s*([0-9]+(?:\.[0-9]+)?)M\b")
_MEMORY_FREE = re.compile(r"System-wide memory free percentage:\s*([0-9]+)%")


class SmokePreflightError(RuntimeError):
    """Explain why a real-model smoke run must not begin."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class SmokeBaseline:
    """Parsed evidence captured before any model inference."""

    swap_used_bytes: int
    memory_free_percent: int
    loaded_models: tuple[str, ...]


def validate_smoke_baseline(
    *,
    swapusage_output: str,
    memory_pressure_output: str,
    running_models: Sequence[dict[str, Any]],
) -> SmokeBaseline:
    """Require zero retained swap and an empty Ollama process list."""

    swap_used_bytes = _parse_swap_used_bytes(swapusage_output)
    memory_free_percent = _parse_memory_free_percent(memory_pressure_output)
    loaded_models = _loaded_model_names(running_models)

    if swap_used_bytes != 0:
        raise SmokePreflightError(
            "retained_swap",
            f"real-model smoke requires zero swap; observed {swap_used_bytes} bytes",
        )
    if loaded_models:
        raise SmokePreflightError(
            "model_already_loaded",
            f"real-model smoke requires an empty Ollama process list; observed {loaded_models}",
        )

    return SmokeBaseline(
        swap_used_bytes=swap_used_bytes,
        memory_free_percent=memory_free_percent,
        loaded_models=loaded_models,
    )


def _parse_swap_used_bytes(output: str) -> int:
    if not isinstance(output, str):
        raise SmokePreflightError("invalid_swapusage", "swapusage output must be text")
    match = _SWAP_USED.search(output)
    if match is None:
        raise SmokePreflightError("invalid_swapusage", "could not parse used swap in MiB")
    return round(float(match.group(1)) * 1_024 * 1_024)


def _parse_memory_free_percent(output: str) -> int:
    if not isinstance(output, str):
        raise SmokePreflightError(
            "invalid_memory_pressure",
            "memory-pressure output must be text",
        )
    match = _MEMORY_FREE.search(output)
    if match is None:
        raise SmokePreflightError(
            "invalid_memory_pressure",
            "could not parse system-wide memory free percentage",
        )
    percent = int(match.group(1))
    if percent > 100:
        raise SmokePreflightError(
            "invalid_memory_pressure",
            "memory free percentage must be between 0 and 100",
        )
    return percent


def _loaded_model_names(running_models: Sequence[dict[str, Any]]) -> tuple[str, ...]:
    if isinstance(running_models, (str, bytes)) or not isinstance(running_models, Sequence):
        raise SmokePreflightError("invalid_ollama_ps", "Ollama process data must be a sequence")

    names = []
    for model in running_models:
        if not isinstance(model, dict):
            raise SmokePreflightError("invalid_ollama_ps", "Ollama process entries must be objects")
        name = model.get("name", model.get("model"))
        if not isinstance(name, str) or not name:
            raise SmokePreflightError("invalid_ollama_ps", "loaded Ollama model has no name")
        names.append(name)
    return tuple(sorted(names))
