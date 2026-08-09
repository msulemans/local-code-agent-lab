#!/usr/bin/env python3
"""Validate the frozen Milestone 004 planning artifacts without model access."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "configs/model_candidates.json"
PROMPTS = ROOT / "benchmarks/model_compatibility/prompt_pack.jsonl"
TOOL_SCHEMAS = ROOT / "benchmarks/model_compatibility/tool_schemas.json"
SYSTEM_PROMPT = ROOT / "benchmarks/model_compatibility/system_prompt.txt"
EXPECTED_CATEGORIES = {
    "tool_selection": 7,
    "argument_fidelity": 5,
    "policy_judgment": 4,
    "code_reasoning": 4,
}
ALLOWED_TOOLS = {"list_files", "search_code", "read_file", "git_diff"}


def load_json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain one JSON object")
    return value


def load_prompts(path: Path) -> list[dict[str, Any]]:
    prompts: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"{path}:{line_number}: invalid JSON: {error.msg}") from error
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{line_number}: prompt must be an object")
        prompts.append(value)
    return prompts


def validate_contract() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    manifest = load_json_object(MANIFEST)
    prompts = load_prompts(PROMPTS)
    tool_schema_document = load_json_object(TOOL_SCHEMAS)

    if manifest.get("schema_version") != 1:
        raise ValueError("manifest schema_version must equal 1")
    if manifest.get("context_probe_repetitions") != 3:
        raise ValueError("context probes must have exactly three repetitions")
    if manifest.get("context_probe_token_tolerance_fraction") != 0.05:
        raise ValueError("context probe token tolerance must equal 0.05")
    candidates = manifest.get("candidates")
    if not isinstance(candidates, list) or len(candidates) != 2:
        raise ValueError("exactly two candidates must be registered")
    if [candidate.get("order") for candidate in candidates] != [1, 2]:
        raise ValueError("candidate order must be [1, 2]")
    for index, candidate in enumerate(candidates):
        revision = candidate.get("upstream_revision")
        if not isinstance(revision, str) or len(revision) != 40:
            raise ValueError("each upstream revision must be a full 40-character hash")
        if candidate.get("quantization") != "Q4_K_M":
            raise ValueError("both candidates must use Q4_K_M")
        local_hash = candidate.get("local_artifact_sha256")
        if local_hash is not None and (
            not isinstance(local_hash, str)
            or len(local_hash) != 64
            or any(character not in "0123456789abcdef" for character in local_hash)
        ):
            raise ValueError("local artifact hashes must be full lowercase SHA-256 values")
        verified_statuses = {
            "downloaded_verified_not_run",
            "downloaded_verified_run_incomplete",
            "downloaded_verified_failed_quality",
            "downloaded_verified_failed_stability",
        }
        if candidate.get("status") in verified_statuses:
            blobs = candidate.get("local_blob_sha256")
            if not isinstance(blobs, list) or len(blobs) != candidate.get("local_blob_count"):
                raise ValueError("verified candidate must record every local blob hash")
            if not isinstance(local_hash, str) or not local_hash.startswith(
                candidate.get("ollama_manifest_digest_prefix", "")
            ):
                raise ValueError("local manifest hash does not match the registered prefix")
        elif local_hash is not None:
            raise ValueError("unverified candidate cannot record a local artifact hash")

    if len(prompts) != 20:
        raise ValueError("prompt pack must contain exactly 20 prompts")
    if tool_schema_document.get("schema_version") != 1:
        raise ValueError("tool schema_version must equal 1")
    tool_schemas = tool_schema_document.get("tools")
    if not isinstance(tool_schemas, list) or len(tool_schemas) != 4:
        raise ValueError("exactly four tool schemas must be registered")
    schema_properties: dict[str, set[str]] = {}
    for tool in tool_schemas:
        function = tool.get("function") if isinstance(tool, dict) else None
        parameters = function.get("parameters") if isinstance(function, dict) else None
        properties = parameters.get("properties") if isinstance(parameters, dict) else None
        name = function.get("name") if isinstance(function, dict) else None
        if tool.get("type") != "function" or not isinstance(name, str) or not isinstance(properties, dict):
            raise ValueError("each tool schema must be an Ollama-compatible function object")
        if parameters.get("additionalProperties") is not False:
            raise ValueError(f"{name}: additionalProperties must be false")
        schema_properties[name] = set(properties)
    if set(schema_properties) != ALLOWED_TOOLS:
        raise ValueError("tool schema names do not match the allowed tools")
    ids = [prompt.get("id") for prompt in prompts]
    if len(set(ids)) != len(ids) or any(not isinstance(item, str) for item in ids):
        raise ValueError("prompt IDs must be unique strings")
    counts = Counter(prompt.get("category") for prompt in prompts)
    if counts != Counter(EXPECTED_CATEGORIES):
        raise ValueError(f"unexpected prompt categories: {dict(counts)}")

    expected_kinds = Counter()
    for prompt in prompts:
        if set(prompt) != {"id", "category", "user", "expected"}:
            raise ValueError(f"{prompt.get('id')}: unknown or missing top-level field")
        expected = prompt["expected"]
        if not isinstance(expected, dict):
            raise ValueError(f"{prompt['id']}: expected must be an object")
        kind = expected.get("kind")
        expected_kinds[kind] += 1
        if kind == "tool":
            tool_name = expected.get("name")
            if tool_name not in ALLOWED_TOOLS:
                raise ValueError(f"{prompt['id']}: unknown expected tool")
            arguments = expected.get("arguments")
            if not isinstance(arguments, dict):
                raise ValueError(f"{prompt['id']}: arguments must be an object")
            unknown_arguments = set(arguments) - schema_properties[tool_name]
            if unknown_arguments:
                raise ValueError(f"{prompt['id']}: unknown arguments {sorted(unknown_arguments)}")
        elif kind == "no_tool":
            terms = expected.get("must_mention_any")
            if not isinstance(terms, list) or not terms:
                raise ValueError(f"{prompt['id']}: policy terms must be a non-empty list")
        elif kind == "answer":
            if expected.get("exact") not in {"A", "B", "C"}:
                raise ValueError(f"{prompt['id']}: reasoning answer must be A, B, or C")
        else:
            raise ValueError(f"{prompt['id']}: unsupported expected kind {kind!r}")

    if expected_kinds != Counter({"tool": 12, "no_tool": 4, "answer": 4}):
        raise ValueError(f"unexpected expected-kind counts: {dict(expected_kinds)}")
    if manifest.get("prompt_pack") != str(PROMPTS.relative_to(ROOT)):
        raise ValueError("manifest prompt_pack does not identify the validated file")
    if manifest.get("tool_schemas") != str(TOOL_SCHEMAS.relative_to(ROOT)):
        raise ValueError("manifest tool_schemas does not identify the validated file")
    if manifest.get("system_prompt") != str(SYSTEM_PROMPT.relative_to(ROOT)):
        raise ValueError("manifest system_prompt does not identify the validated file")
    system_prompt = SYSTEM_PROMPT.read_text(encoding="utf-8").strip()
    if "never executes it" not in system_prompt or "exactly that single letter" not in system_prompt:
        raise ValueError("system prompt must preserve the no-execution and reasoning contracts")
    return manifest, prompts


def main() -> int:
    manifest, prompts = validate_contract()
    candidates = manifest["candidates"]
    print(f"PASS {manifest['experiment_id']}")
    downloaded = sum(candidate.get("local_artifact_sha256") is not None for candidate in candidates)
    print(f"candidates={len(candidates)} prompts={len(prompts)}")
    print(f"downloads={downloaded} candidate_1={candidates[0]['status']} candidate_2={candidates[1]['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
