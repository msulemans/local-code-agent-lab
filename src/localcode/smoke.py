"""Bounded orchestration for the Milestone 005 real-model smoke gate."""

from __future__ import annotations

from dataclasses import dataclass
import subprocess
from pathlib import Path
from typing import Callable

from .actions import ActionValidator
from .backends.ollama import OllamaBackend
from .compatibility import OllamaClient
from .controller import OneTurnController, OneTurnResult
from .preflight import SmokeBaseline, SmokePreflightError, validate_smoke_baseline
from .registry import ToolRegistry


CommandRunner = Callable[[tuple[str, ...]], str]


@dataclass(frozen=True, slots=True)
class SmokeRun:
    """Baseline evidence and the one permitted controller result."""

    baseline: SmokeBaseline
    result: OneTurnResult


def run_one_turn_smoke(
    *,
    run_id: str,
    issue: str,
    model: str,
    repository_root: str | Path,
    tool_document: dict[str, object],
    clock: Callable[[], str],
    client: OllamaClient | None = None,
    command_runner: CommandRunner | None = None,
) -> SmokeRun:
    """Capture a clean baseline, then permit exactly one Ollama-backed turn."""

    ollama = client if client is not None else OllamaClient()
    run_command = command_runner if command_runner is not None else _run_host_command
    baseline = validate_smoke_baseline(
        swapusage_output=run_command(("sysctl", "vm.swapusage")),
        memory_pressure_output=run_command(("memory_pressure", "-Q")),
        running_models=ollama.running_models(),
    )

    validator = ActionValidator.from_tool_document(tool_document)
    controller = OneTurnController(
        OllamaBackend(model=model, tool_document=tool_document, client=ollama),
        validator,
        ToolRegistry(repository_root),
        clock=clock,
    )
    return SmokeRun(
        baseline=baseline,
        result=controller.run(run_id=run_id, issue=issue),
    )


def _run_host_command(arguments: tuple[str, ...]) -> str:
    try:
        completed = subprocess.run(
            arguments,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise SmokePreflightError(
            "host_command_failed",
            f"could not capture smoke baseline with {arguments[0]!r}",
        ) from exc
    return completed.stdout
