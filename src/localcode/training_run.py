"""Pure contracts and metric parsing for the controlled M016 LoRA run."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable


_TRAIN = re.compile(
    r"Iter (\d+): Train loss ([0-9.]+).*?Tokens/sec ([0-9.]+).*?Peak mem ([0-9.]+) GB"
)
_VALIDATION = re.compile(r"Test loss ([0-9.]+), Test ppl ([0-9.]+)\.")


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


def parse_train_metrics(output: str) -> tuple[TrainMetric, ...]:
    return tuple(
        TrainMetric(int(iteration), float(loss), float(speed), float(memory))
        for iteration, loss, speed, memory in _TRAIN.findall(output)
    )


def diagnostic_passed(
    metrics: tuple[TrainMetric, ...],
    *,
    required_relative_improvement: float,
    maximum_peak_memory_gb: float,
) -> bool:
    if len(metrics) < 2 or not 0 < required_relative_improvement < 1:
        return False
    first, last = metrics[0], metrics[-1]
    return (
        all(metric.loss == metric.loss and metric.loss >= 0 for metric in metrics)
        and max(metric.peak_memory_gb for metric in metrics) <= maximum_peak_memory_gb
        and last.loss <= first.loss * (1 - required_relative_improvement)
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
