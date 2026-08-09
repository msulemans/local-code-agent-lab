# Milestone 004 local-model compatibility plan

## The question

What is the smallest quantized Qwen coding instruct model that is stable,
responsive, and reliable enough to produce bounded LocalCode actions on this
32 GiB M2 Max?

This is like auditioning an engine before building the gearbox around it. A
large model may know more, but if it exhausts unified memory or emits actions we
cannot validate, it is not the better engine for this machine.

## Why these two candidates

Candidate 1 is Qwen2.5-Coder-7B-Instruct Q4_K_M. It is instruction-tuned,
small enough to leave generous memory headroom, and its upstream chat template
supports tool descriptions. The registered Ollama artifact is 4.7 GB.

Candidate 2 is Qwen3-Coder-30B-A3B-Instruct Q4_K_M. It has 30.53 billion total
parameters but activates about 3.3 billion per token, and upstream explicitly
targets agentic coding and tool calling. Its 19 GB artifact is plausible on a
32 GiB unified-memory Mac but leaves much less room for KV cache, the runtime,
and macOS. It is therefore conditional, not the default.

The already present `qwen2.5-coder:1.5b-base` is not a candidate. It is a base
completion model rather than an instruction-tuned tool user. Reusing a file
because it is already downloaded would optimize storage convenience instead of
the capability being tested.

## Backend decision

Use the installed Ollama 0.32.0 backend for both candidates. This avoids adding
a Python inference dependency during the comparison and gives both model chat
templates the same normalized response interface. MLX remains a proven future
option, but changing both model and backend would confound this experiment.

This does not turn LocalCode into an Ollama wrapper. Ollama is only the local
inference engine. This repository will still own action validation, tools,
context, budgets, events, retries, patches, and evaluation.

## Frozen experiment

The machine-readable contract is `configs/model_candidates.json`; the 20
development prompts are in
`benchmarks/model_compatibility/prompt_pack.jsonl`.

Candidate 1 is acquired and measured first. If it passes every gate, select it
and stop. Candidate 2 may be acquired only when candidate 1 is technically
healthy but misses a quality gate. If candidate 1 crashes, swaps heavily, or is
too slow, a 19 GB candidate is not a rational automatic escalation; diagnose
the backend or lower-level cause first.

The registered gates require:

- successful cold load and both 4K/16K context probes;
- at least 11/12 schema-valid expected tool calls;
- at least 14/16 correct tool-or-no-tool decisions;
- at least 3/4 exact code-reasoning controls;
- median output speed of at least 8 tokens/second at each context size;
- median time to first token no worse than 15 seconds at 4K or 45 seconds at
  16K;
- peak model working set at most 24 GiB; and
- no more than 2 GiB host swap growth.

These are engineering usability gates, not claims of general intelligence.
They are frozen before observing candidate output so a disappointing model
cannot be promoted by changing the test afterward.

## Stop rules

Stop the current candidate immediately and preserve evidence if inference
crashes, the host enters critical memory pressure, working set exceeds 24 GiB,
swap grows by more than 2 GiB, a context probe fails, or three consecutive
requests fail. Do not pull a third model in Milestone 004.

If both registered candidates miss quality gates while remaining technically
healthy, inspect chat-template/tool-schema compatibility and one fixed prompt
revision on this development pack. Do not browse more checkpoints until that
diagnosis is recorded. Any prompt revision creates a new experiment ID and
requires rerunning every acquired candidate.

## Reproducibility and untouched baseline

The upstream repository revisions and published Ollama manifest digest prefixes
are registered now. After a pull, record the full local manifest and blob
SHA-256 digests; a web page prefix is not a sufficient local artifact hash.
Store requests, raw responses, timings, resource samples, scorer output, and
the final decision in a new immutable run directory.

The first response for every prompt is the scored response. Preserve it
unchanged as the single-shot compatibility baseline. Prompt repair, retries,
or manual cleanup cannot replace it.

## What is deliberately not being built

This milestone does not execute repository tools, implement the controller,
edit files, run fixture tests, use SWE-bench, or download a model without a new
explicit approval. Those capabilities belong to later gates.

## Official planning sources

- [Qwen2.5-Coder-7B-Instruct model card](https://huggingface.co/Qwen/Qwen2.5-Coder-7B-Instruct)
- [Qwen3-Coder-30B-A3B-Instruct model card](https://huggingface.co/Qwen/Qwen3-Coder-30B-A3B-Instruct)
- [Ollama Qwen2.5-Coder tags](https://ollama.com/library/qwen2.5-coder/tags)
- [Ollama Qwen3-Coder tags](https://ollama.com/library/qwen3-coder/tags)
- [Ollama chat API and timing fields](https://docs.ollama.com/api/chat)
- [Ollama normalized tool calling](https://docs.ollama.com/capabilities/tool-calling)
- [Ollama loaded-model memory fields](https://docs.ollama.com/api/ps)

Candidate facts were refreshed on 2026-08-08. Recheck the tag manifests before
acquisition because remote artifacts can change.
