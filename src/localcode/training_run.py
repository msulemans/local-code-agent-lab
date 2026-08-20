"""Pure contracts and metric parsing for the controlled M016 LoRA run."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Iterable


_TRAIN = re.compile(
    r"Iter (\d+): Train loss ([0-9.]+).*?Tokens/sec ([0-9.]+).*?Peak mem ([0-9.]+) GB"
)
_OVERFIT_VALIDATION = re.compile(r"Iter (\d+): Val loss ([0-9.]+)")
_VALIDATION = re.compile(r"Test loss ([0-9.]+), Test ppl ([0-9.]+)\.")
_CHECKPOINT = re.compile(r"^(\d{7})_adapters\.safetensors$")


@dataclass(frozen=True, slots=True)
class TrainMetric:
    iteration: int
    loss: float
    tokens_per_second: float
    peak_memory_gb: float


@dataclass(frozen=True, slots=True)
class ValidationMetric:
    iteration: int
    loss: float
    perplexity: float


@dataclass(frozen=True, slots=True)
class OverfitValidationMetric:
    iteration: int
    loss: float


def parse_train_metrics(output: str) -> tuple[TrainMetric, ...]:
    return tuple(
        TrainMetric(int(iteration), float(loss), float(speed), float(memory))
        for iteration, loss, speed, memory in _TRAIN.findall(output)
    )


def parse_overfit_validation_metrics(output: str) -> tuple[OverfitValidationMetric, ...]:
    return tuple(
        OverfitValidationMetric(int(iteration), float(loss))
        for iteration, loss in _OVERFIT_VALIDATION.findall(output)
    )


def diagnostic_passed(
    metrics: tuple[TrainMetric, ...],
    validation_metrics: tuple[OverfitValidationMetric, ...],
    *,
    required_relative_improvement: float,
    maximum_peak_memory_gb: float,
) -> bool:
    if len(metrics) < 2 or len(validation_metrics) < 2 or not 0 < required_relative_improvement < 1:
        return False
    first = metrics[0]
    first_validation, last_validation = validation_metrics[0], validation_metrics[-1]
    return (
        all(metric.loss == metric.loss and metric.loss >= 0 for metric in metrics)
        and all(metric.loss == metric.loss and metric.loss >= 0 for metric in validation_metrics)
        and max(metric.peak_memory_gb for metric in metrics) <= maximum_peak_memory_gb
        # Individual shuffled mini-batches are not directly comparable. Require
        # both a lower observed train loss and improvement on the same frozen
        # eight-row validation set.
        and min(metric.loss for metric in metrics[1:]) <= first.loss * (1 - required_relative_improvement)
        and last_validation.loss <= first_validation.loss * (1 - required_relative_improvement)
    )


def parse_validation_metric(iteration: int, output: str) -> ValidationMetric:
    match = _VALIDATION.search(output)
    if match is None:
        raise ValueError(f"checkpoint {iteration} has no validation metric")
    return ValidationMetric(iteration, float(match.group(1)), float(match.group(2)))


def select_validation_checkpoint(metrics: Iterable[ValidationMetric]) -> ValidationMetric:
    values = tuple(metrics)
    if not values or len({value.iteration for value in values}) != len(values):
        raise ValueError("checkpoint validation metrics must be non-empty and unique")
    if any(value.loss != value.loss or value.loss < 0 for value in values):
        raise ValueError("checkpoint validation losses must be finite and non-negative")
    return min(values, key=lambda value: (value.loss, value.iteration))


def available_checkpoint_iterations(
    directory: str | Path,
    expected_iterations: Iterable[int],
) -> tuple[int, ...]:
    """Return complete, expected MLX checkpoints without accepting stray files."""

    root = Path(directory)
    expected = tuple(expected_iterations)
    if not root.is_dir() or not (root / "adapter_config.json").is_file():
        raise ValueError("checkpoint directory must contain adapter_config.json")
    if not expected or len(set(expected)) != len(expected) or any(value <= 0 for value in expected):
        raise ValueError("expected checkpoint iterations must be positive and unique")
    discovered = {
        int(match.group(1))
        for path in root.iterdir()
        if path.is_file() and (match := _CHECKPOINT.fullmatch(path.name)) is not None
    }
    unexpected = discovered.difference(expected)
    if unexpected:
        raise ValueError(f"unexpected checkpoint iterations: {sorted(unexpected)}")
    return tuple(value for value in expected if value in discovered)
