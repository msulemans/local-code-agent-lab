"""Deterministic MLX-LM export without exposing the sealed-test split."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Iterable

from .training_data import TrainingDataError, TrainingExample, TrainingSplit, TrainingTask


SYSTEM_PROMPT = (
    "You repair Python source code. Follow the instruction and return only the "
    "complete corrected file contents, without Markdown fences or explanation."
)


@dataclass(frozen=True, slots=True)
class MlxExportSummary:
    source_examples: int
    train_examples: int
    validation_examples: int
    sealed_examples_withheld: int
    sealed_examples_exported: int
    train_sha256: str
    validation_sha256: str
    task_counts: tuple[tuple[str, int], ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "source_examples": self.source_examples,
            "train_examples": self.train_examples,
            "validation_examples": self.validation_examples,
            "sealed_examples_withheld": self.sealed_examples_withheld,
            "sealed_examples_exported": self.sealed_examples_exported,
            "train_sha256": self.train_sha256,
            "validation_sha256": self.validation_sha256,
            "task_counts": dict(self.task_counts),
        }


def export_mlx_chat_data(
    examples: Iterable[TrainingExample],
    *,
    output_directory: str | Path,
    validation_evaluation_directory: str | Path | None = None,
) -> MlxExportSummary:
    """Write train/valid chat JSONL and never create a sealed-test file."""

    records = tuple(examples)
    if not records:
        raise TrainingDataError("empty_export", "MLX export requires at least one example")
    output = Path(output_directory)
    train_rows: list[str] = []
    validation_rows: list[str] = []
    sealed_count = 0
    task_counts: Counter[str] = Counter()
    for example in sorted(records, key=lambda item: item.example_id):
        task_counts[example.task_type.value] += 1
        if example.split is TrainingSplit.SEALED_TEST:
            sealed_count += 1
            continue
        if example.task_type is not TrainingTask.BROKEN_TO_CORRECTED:
            raise TrainingDataError(
                "unsupported_export_task",
                f"MLX export v1 does not format {example.task_type.value}",
            )
        row = _chat_row(example)
        if example.split is TrainingSplit.TRAIN:
            train_rows.append(row)
        elif example.split is TrainingSplit.VALIDATION:
            validation_rows.append(row)
        else:  # defensive against future enum additions
            raise TrainingDataError("unsupported_split", f"unsupported split: {example.split.value}")
    if not train_rows or not validation_rows:
        raise TrainingDataError("missing_development_split", "train and validation exports must be non-empty")

    train_text = "".join(row + "\n" for row in train_rows)
    validation_text = "".join(row + "\n" for row in validation_rows)
    try:
        output.mkdir(parents=True, exist_ok=True)
        (output / "train.jsonl").write_text(train_text, encoding="utf-8")
        (output / "valid.jsonl").write_text(validation_text, encoding="utf-8")
        if validation_evaluation_directory is not None:
            evaluation = Path(validation_evaluation_directory)
            evaluation.mkdir(parents=True, exist_ok=True)
            (evaluation / "test.jsonl").write_text(validation_text, encoding="utf-8")
            (evaluation / "README.txt").write_text(
                "This test.jsonl is an MLX-LM filename adapter containing the validation split.\n"
                "It is not the sealed-test split and must not be reported as final test evidence.\n",
                encoding="utf-8",
            )
    except OSError as exc:
        raise TrainingDataError("export_write", f"could not write MLX export under {output}") from exc
    return MlxExportSummary(
        source_examples=len(records),
        train_examples=len(train_rows),
        validation_examples=len(validation_rows),
        sealed_examples_withheld=sealed_count,
        sealed_examples_exported=0,
        train_sha256=hashlib.sha256(train_text.encode("utf-8")).hexdigest(),
        validation_sha256=hashlib.sha256(validation_text.encode("utf-8")).hexdigest(),
        task_counts=tuple(sorted(task_counts.items())),
    )


def _chat_row(example: TrainingExample) -> str:
    path = example.changed_paths[0]
    user_content = (
        f"Instruction:\n{example.instruction}\n\n"
        f"File: {path}\n\n"
        f"Broken file contents:\n{example.input_text}"
    )
    document = {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
            {"role": "assistant", "content": example.target_text},
        ]
    }
    return json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
