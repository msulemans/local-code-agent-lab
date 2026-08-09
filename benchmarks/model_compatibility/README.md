# Model compatibility development pack

This is a development-only compatibility test, not SWE-bench and not a claim
that a model can repair repositories. It tests whether a local instruct model is
usable as the prediction component of the future LocalCode controller.

## Fixed tool surface

The backend receives the schemas for the four implemented read-only tools:
`list_files`, `search_code`, `read_file`, and `git_diff`. Backend-native chat
templates may differ, so the scorer evaluates Ollama's normalized
`message.tool_calls` rather than comparing raw XML or JSON text.
The exact development schemas are frozen in `tool_schemas.json`; repository
root is injected by the future controller and is never a model argument.

The 20 prompts contain:

- 12 expected tool calls;
- 4 expected no-tool policy decisions; and
- 4 basic code-reasoning controls.

Exact arguments are deliberately simple. A model does not receive repository
contents and no tool is actually executed during this bake-off.

## Measurements

For each candidate, preserve raw requests and responses. Record cold-load time,
time to first streamed token, prompt and output token counts, prompt and output
tokens per second, wall time, errors, model working set, host swap before/after,
and every scored prompt result. Run separate padded context probes at 4,096 and
16,384 input tokens; the 20 semantic prompts themselves are not padded.

Use one warm-up response before timed repetitions. Do not silently retry a
failed prompt. A retry is a new recorded attempt and the first attempt remains
the scored result.

## Scoring vocabulary

- **Schema-valid tool call:** exactly one normalized call names an allowed tool,
  supplies one JSON object, uses only known fields, and passes the tool's type
  constraints.
- **Correct action decision:** the expected tool and exact registered arguments
  match, or a policy prompt correctly produces no tool call and a bounded
  explanation containing one registered concept.
- **Correct reasoning answer:** the stripped response equals the registered
  answer. No semantic grading after seeing model output.

The frozen gates and acquisition order live in
`configs/model_candidates.json`. Candidate 2 is not downloaded merely because
it exists in the manifest.

## Before any download

Run the contract checks from the repository root:

```bash
python3.11 scripts/check_model_bakeoff_contract.py
PYTHONPATH=src python3.11 -m unittest discover -s tests/unit -v
```

Both commands are offline and do not contact Ollama. Candidate 1 was acquired
with explicit permission; candidate 2 remains conditional and absent.

Verify the full manifest and every referenced local blob without running
inference:

```bash
python3.11 scripts/inspect_ollama_artifact.py \
  qwen2.5-coder:7b-instruct-q4_K_M
```

Preserve that JSON with the before/after disk measurements. Do not treat the
short ID printed by `ollama list` as the full artifact hash.

## Candidate-1 measurement

The compatibility runner talks only to a loopback Ollama API, never executes a
proposed tool, snapshots its exact source/contract files, and refuses to reuse a
run directory. It preserves every request, raw NDJSON stream, score, timing,
memory sample, and stop reason.

In a normal Terminal, ensure the model is unloaded and start the first immutable
run:

```bash
ollama stop qwen2.5-coder:7b-instruct-q4_K_M
python3.11 scripts/run_model_compatibility.py \
  --run-id m004c-qwen25-7b-v1
```

An Ollama “not running” response from the stop command only means the cold-load
precondition is already satisfied. The run performs no repository action and
does not acquire candidate 2. Do not reuse the run ID after any failure.
