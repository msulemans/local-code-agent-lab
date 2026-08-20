"""Sequence-bounded MLX export for executable-aligned issue-to-diff training."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Callable, Iterable

from .training_data import TrainingDataError, TrainingExample, TrainingSplit, TrainingTask


SYSTEM_PROMPT = (
    "You repair Python repositories. Return only one valid unified diff that "
    "fixes the issue, without Markdown fences or explanation."
)
TokenCounter = Callable[[tuple[dict[str, str], ...]], int]


@dataclass(frozen=True, slots=True)
class ExecutableExportSummary:
    source_examples: int
    train_examples: int
    validation_examples: int
    sealed_examples_withheld: int
    sealed_examples_tokenized: int
    overlength_counts: tuple[tuple[str, int], ...]
    maximum_sequence_tokens: int
    observed_maximum_tokens: int
    train_sha256: str
    validation_sha256: str

    def to_dict(self) -> dict[str, object]:
        return {
            "source_examples": self.source_examples,
            "train_examples": self.train_examples,
            "validation_examples": self.validation_examples,
            "sealed_examples_withheld": self.sealed_examples_withheld,
            "sealed_examples_tokenized": self.sealed_examples_tokenized,
            "overlength_counts": dict(self.overlength_counts),
            "maximum_sequence_tokens": self.maximum_sequence_tokens,
            "observed_maximum_tokens": self.observed_maximum_tokens,
            "train_sha256": self.train_sha256,
            "validation_sha256": self.validation_sha256,
        }


def export_executable_mlx(
    examples: Iterable[TrainingExample],
    *,
    output_directory: str | Path,
    token_counter: TokenCounter,
    maximum_sequence_tokens: int = 1024,
) -> ExecutableExportSummary:
    """Export train/validation only; skip sealed rows before rendering or tokenizing."""

    if isinstance(maximum_sequence_tokens, bool) or maximum_sequence_tokens <= 0:
        raise TrainingDataError("sequence_limit", "maximum sequence tokens must be positive")
    records = tuple(examples)
    train: list[str] = []
    validation: list[str] = []
    sealed = 0
    overlength: Counter[str] = Counter()
    observed_maximum = 0
    for example in sorted(records, key=lambda item: item.example_id):
        if example.split is TrainingSplit.SEALED_TEST:
            sealed += 1
            continue
        if example.task_type is not TrainingTask.ISSUE_TO_DIFF:
            raise TrainingDataError("export_task", "M016b exports only issue_to_diff examples")
        messages = executable_messages(example)
        sequence_tokens = token_counter(messages)
        if isinstance(sequence_tokens, bool) or not isinstance(sequence_tokens, int) or sequence_tokens <= 0:
            raise TrainingDataError("token_counter", "token counter returned an invalid length")
        observed_maximum = max(observed_maximum, sequence_tokens)
        if sequence_tokens > maximum_sequence_tokens:
            overlength[example.split.value] += 1
            continue
        row = json.dumps(
            {"messages": list(messages)},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        if example.split is TrainingSplit.TRAIN:
            train.append(row)
        elif example.split is TrainingSplit.VALIDATION:
            validation.append(row)
        else:
            raise TrainingDataError("export_split", "unsupported development split")
    if not train or not validation:
        raise TrainingDataError("export_split", "bounded export requires train and validation rows")
    train_text = "".join(row + "\n" for row in train)
    validation_text = "".join(row + "\n" for row in validation)
    destination = Path(output_directory)
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "train.jsonl").write_text(train_text, encoding="utf-8")
    (destination / "valid.jsonl").write_text(validation_text, encoding="utf-8")
    return ExecutableExportSummary(
        source_examples=len(records),
        train_examples=len(train),
        validation_examples=len(validation),
        sealed_examples_withheld=sealed,
        sealed_examples_tokenized=0,
        overlength_counts=tuple(sorted(overlength.items())),
        maximum_sequence_tokens=maximum_sequence_tokens,
        observed_maximum_tokens=observed_maximum,
        train_sha256=hashlib.sha256(train_text.encode("utf-8")).hexdigest(),
        validation_sha256=hashlib.sha256(validation_text.encode("utf-8")).hexdigest(),
    )


def executable_messages(example: TrainingExample) -> tuple[dict[str, str], ...]:
    return (
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"Issue:\n{example.instruction}\n\n{example.input_text}",
        },
        {"role": "assistant", "content": example.target_text},
    )
