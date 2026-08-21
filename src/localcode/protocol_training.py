"""Build MLX chat rows whose targets are LocalCode decision envelopes."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable


PROTOCOL_SYSTEM_PROMPT = (
    "You are LocalCode, a bounded coding agent. Return exactly one JSON object "
    "and nothing else. Choose one provided tool and use this exact shape: "
    '{"protocol_version":"1","thought_summary":"short reason",'
    '"decision":{"kind":"tool","tool":"apply_patch",'
    '"arguments":{"patch":"..."}}}. Do not emit Markdown or explanations. '
    "The controller validates and executes the decision."
)


class ProtocolTrainingError(ValueError):
    """Raised when a repair-diff row cannot become a safe protocol example."""


def build_protocol_row(row: dict[str, Any]) -> dict[str, Any]:
    """Convert one existing repair-diff chat row without changing its evidence."""
    messages = row.get("messages")
    if not isinstance(messages, list) or len(messages) != 3:
        raise ProtocolTrainingError("source row must contain exactly three messages")
    if [message.get("role") for message in messages] != ["system", "user", "assistant"]:
        raise ProtocolTrainingError("source row roles must be system, user, assistant")
    user = messages[1].get("content")
    patch = messages[2].get("content")
    if not isinstance(user, str) or not user.strip():
        raise ProtocolTrainingError("source user content must be non-empty text")
    if not isinstance(patch, str) or not patch.startswith("diff --git "):
        raise ProtocolTrainingError("source target must be one unified diff")
    if patch.count("diff --git ") != 1:
        raise ProtocolTrainingError("source target must modify exactly one file")
    if "```" in patch or "\x00" in patch:
        raise ProtocolTrainingError("source target contains forbidden wrapper or NUL")
    if not patch.endswith("\n"):
        patch += "\n"
    decision = {
        "protocol_version": "1",
        "thought_summary": "Apply the minimal repair patch.",
        "decision": {
            "kind": "tool",
            "tool": "apply_patch",
            "arguments": {"patch": patch},
        },
    }
    return {
        "messages": [
            {"role": "system", "content": PROTOCOL_SYSTEM_PROMPT},
            {"role": "user", "content": user},
            {
                "role": "assistant",
                "content": json.dumps(decision, sort_keys=True, separators=(",", ":")),
            },
        ]
    }


def build_protocol_dataset(
    *,
    source_directory: str | Path,
    output_directory: str | Path,
    tokenizer: Any | None = None,
    max_sequence_tokens: int = 768,
) -> dict[str, Any]:
    """Build train/valid rows, dropping only rows over the frozen token bound."""
    if isinstance(max_sequence_tokens, bool) or not isinstance(max_sequence_tokens, int) or max_sequence_tokens < 1:
        raise ProtocolTrainingError("max_sequence_tokens must be a positive integer")
    source = Path(source_directory)
    output = Path(output_directory)
    output.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "schema_version": 1,
        "treatment": "repair_diff_to_apply_patch_protocol",
        "max_sequence_tokens": max_sequence_tokens,
        "sealed_examples_loaded": 0,
        "splits": {},
    }
    for split in ("train", "valid"):
        source_path = source / f"{split}.jsonl"
        if not source_path.is_file():
            raise ProtocolTrainingError(f"missing source split: {source_path}")
        kept: list[str] = []
        source_count = 0
        dropped = 0
        max_tokens = 0
        for line_number, line in enumerate(source_path.read_text(encoding="utf-8").splitlines(), 1):
            source_count += 1
            try:
                row = json.loads(line)
                converted = build_protocol_row(row)
            except (json.JSONDecodeError, ProtocolTrainingError) as exc:
                raise ProtocolTrainingError(f"{source_path}:{line_number}: {exc}") from exc
            token_count = _token_count(converted, tokenizer)
            max_tokens = max(max_tokens, token_count)
            if tokenizer is not None and token_count > max_sequence_tokens:
                dropped += 1
                continue
            kept.append(json.dumps(converted, sort_keys=True, separators=(",", ":")))
        destination = output / f"{split}.jsonl"
        destination.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
        report["splits"][split] = {
            "source_examples": source_count,
            "examples": len(kept),
            "dropped_overlength": dropped,
            "maximum_observed_tokens": max_tokens,
            "sha256": _sha256(destination),
        }
    (output / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def _token_count(row: dict[str, Any], tokenizer: Any | None) -> int:
    if tokenizer is None:
        return 0
    encoded = tokenizer.apply_chat_template(row["messages"], tokenize=True, add_generation_prompt=False)
    try:
        return len(encoded["input_ids"])
    except (TypeError, KeyError):
        return len(encoded)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
