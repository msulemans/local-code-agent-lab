# Milestones and gates

Only the current milestone may be implemented. A future assistant must not
bundle later milestones merely because their design is already documented.

## 001 — Read-only environment verification

Learn: what the host can support before selecting dependencies or weights.

Inspect: architecture, macOS, memory, free disk, Python 3.11/3.12 availability,
Git, `rg`, Docker engine/architecture/storage, MLX/MLX-LM, llama.cpp/Ollama if
already present, and current local model artifacts.

Gate: record an exact capability matrix in `AGENT_STATE.md`. No installation or
download. Decide which missing pieces need user approval and whether local
SWE-bench evaluation is feasible without endangering disk space.

## 002 — Repository contract and deterministic test skeleton

Learn: trusted runtime versus untrusted workspace.

Build only the package skeleton, configuration loader, event schema, a tiny
fixture repository, and tests that do not need an LLM.

Gate: unit tests pass; run directories and model/data artifacts are ignored;
one event round-trips through JSON; no executable tool yet.

## 003 — Read-only tool layer

Implement `list_files`, `search_code`, `read_file`, and `git_diff` with path,
size, result, and secret boundaries.

Gate: deterministic unit tests cover valid use, `..` traversal, absolute paths,
symlink escape, binary/large files, excluded secrets, and truncated output.

## 004 — Local model compatibility bake-off

Compare no more than two quantized instruct coding checkpoints from the chosen
Qwen family. Pin repository revision and artifact hashes. Measure cold load,
peak memory, tokens/second at two realistic context sizes, schema-valid action
rate, and basic code reasoning on a development-only prompt pack.

Registration is a separate stop point: freeze the candidate order, storage
forecast, prompt pack, metrics, gates, and stop rules before acquiring either
artifact. A published manifest prefix is planning provenance; record the full
local manifest and blob SHA-256 hashes only after the approved pull.

Gate: choose the smallest model that meets the registered action-validity and
latency floor. If neither passes, diagnose prompting/backend compatibility
before downloading additional models. Preserve an untouched single-shot model
baseline.

## 005 — Protocol and one-turn controller

Connect the local backend to the versioned action validator and one read-only
tool call. Use a fake backend in most tests and the real model in a bounded
smoke test.

Gate: valid call succeeds, invalid JSON and unknown tools become observations,
and identical fake-backend inputs produce identical event sequences.

## 006 — Bounded read-only agent loop

Add multiple turns, state transitions, budgets, repeated-action detection,
context construction, and final-answer termination. Use repository question
tasks; do not edit yet.

Gate: the loop terminates correctly for success, invalid-action exhaustion,
tool exhaustion, repeated action, backend error, and wall-clock timeout.

## 007 — Guarded editing and tests

Add `apply_patch` and constrained `run_tests`. Create 8–12 deterministic
micro-repository issues covering one-file bugs, tests-first discovery, syntax
failure, regression, and misleading failure output.

Gate: the agent solves a registered minimum on the micro suite; every successful
run has an applied diff and exact passing command. Failed patches remain
diagnosable and cannot escape the workspace.

## 008 — Retrieval treatment

Add repository map, query planning, symbol/caller/test proximity, excerpt
ranking, deduplication, and context token allocation. Do not change the model,
tool/time budget, edit policy, or task set.

Gate: retrieval improves a registered development metric such as relevant-file
recall under a fixed context budget. If it does not, keep the simple agent and
record the negative result.

Current first slice: deterministic repository map, source/test excerpt ranking,
and relevant changed-file recall metric. The registered micro-suite development
metric is 9/9 expected changed paths recalled under a fixed 3-file budget. This
does not yet prove solve-rate improvement.

## 009 — Benchmark harness proof

Pin the SWE-bench package, dataset revision, 20-instance manifest, and container
configuration. First run the official gold patch for one instance and confirm
the independent evaluator resolves it. Then run an empty patch and confirm it
does not falsely resolve.

Gate: gold/empty controls behave correctly; disk forecast and cleanup policy are
recorded; the agent never sees gold or evaluator-only tests.

## 010 — Frozen four-way benchmark

Run the configurations in registered order with identical task and compute
budgets. No prompt, parser, subset, or timeout changes after the first scored
run unless every configuration is rerun under a new experiment version.

Gate: produce per-instance results, aggregate solved counts, paired transitions,
resource use, and failure taxonomy. The score is reported even if all are zero.

## 011 — Reviewer treatment

If review was not included in the frozen run, add it as the final registered
treatment and rerun all required controls. Permit at most one revision.

Gate: report fixes, harms, unchanged outcomes, and marginal compute. Promote
review only if its registered criterion is met.

## 012 — Terminal UI and final learning lab

Build the event-driven TUI, failure explorer, run comparison, glossary,
flashcards, and reproduction guide.

Gate: headless and TUI modes share the same runtime and patch result; a new
learner can complete one micro issue and explain the architecture.

The static HTML learning field manual was brought forward after Milestone 003
at the learner's request. It teaches the current architecture and progress but
does not replace this milestone's larger failure explorer, run comparison,
glossary, or reproduction guide. A small terminal shell and
headless-versus-TUI equivalence test were brought forward during Milestone 007.

## Phase 4 — Train a coding model

Phase 4 improves the model component without changing the trusted LocalCode
runtime. It starts from a capable pretrained coding checkpoint and trains a
small adapter; it does not train a language model from scratch.

## 013 — Leakage-safe training-data contract

Freeze versioned records for `issue_to_diff`, `broken_to_corrected`,
`test_failure_to_patch`, and `function_to_implementation`. Require source
revision and reviewed licence provenance, deterministic lineage-group splits,
canonical hashes, exact-content overlap checks, and automatic exclusion of all
pinned evaluation IDs and base revisions.

Gate: malformed records, unsafe paths, unreviewed licences, split drift,
cross-split duplicates, and evaluation leakage are rejected deterministically;
the contract CLI passes before any corpus is downloaded.

## 014 — Pinned source acquisition and corpus build

Select legally usable public repair sources, pin source revisions and file
checksums, stream or download only the registered shards, normalize them into
schema v1, and publish counts/rejection reasons without committing bulk data.

Gate: reconstruction is deterministic; every accepted record has provenance;
train/validation/sealed-test lineage and exact-content overlap are zero; no
Milestone 009 evaluation instance or exact base revision appears.

## 015 — Untouched pretrained baseline

Choose the smallest instruction-tuned coding checkpoint that passes format and
memory gates. Evaluate it once on validation tasks using executable tests and
save the untouched checkpoint identity, prompt, decoding settings, and result.

Gate: baseline evaluation is reproducible and no training begins unless one
tiny batch can tokenize, forward, backward, and save an adapter on this Mac.

## 016 — Controlled adapter training

Fine-tune with LoRA/QLoRA or the Apple-Silicon equivalent using train only.
Select checkpoint and stopping point using validation only. Preserve loss,
throughput, memory, checkpoints, configuration, and source hashes.

Gate: a tiny overfit diagnostic passes, the full run stays within the declared
resource ceiling, and the selected adapter improves the registered validation
metric over the untouched base. Otherwise preserve the negative result.

An interrupted run may evaluate its fully written checkpoints in a separate
immutable recovery record, but it must not be reported as completion of the
configured training length. Adapter-only continuation also resets Adam state,
so it is a new treatment rather than an exact resume.

Observed v1 recovery result: update 200 reduced full-validation loss from
`1.383` to `1.333`, but executable development solves regressed from 4/6 to
1/6. The adapter is not promoted and the sealed split remains closed. Further
work must change the data/evidence treatment rather than merely extending this
run.

## 017 — One sealed evaluation and LocalCode comparison

Open the sealed test exactly once after configuration selection. Compare the
base checkpoint and selected adapter both as direct repair models and inside
the same frozen LocalCode treatment. Executable tests remain authoritative.

Gate: report raw solves, valid patches, regressions, compute, and confidence
limits. Do not tune after sealed-test inspection or mix these tasks with the
pinned SWE-bench evaluation set.

## 018 — Package the adapter and learning lab

Record base-model licence, adapter licence, hashes, training manifest, hardware,
limitations, load command, and a small reproducible demo. Extend the learning
UI with data lineage, loss curves, baseline-versus-adapter evidence, and honest
failed experiments.

Gate: a clean environment can verify the manifest, load the base plus adapter,
run the demo, and reproduce the reported small evaluation without secrets or
untracked source data.

## 019–020 — Training negatives and protocol diagnosis

The Qwen 7B LoRA checkpoints were selected by validation loss and then tested
through the unchanged executable loop. Both the diff-target treatment and the
single-shot protocol-envelope treatment solved `0/6`, so neither adapter is
promoted. These are preserved negative results, not unfinished claims.

Gate: do not continue either recipe. Any future training data must contain
multi-turn context, typed decisions, observations, and successful revisions.

## 021 — One-shot CLI and BYOK backends

Expose the real bounded runtime through a one-shot CLI with local MLX, OpenAI
Responses, and OpenAI-compatible transports. Keep the model replaceable while
the controller, tools, disposable workspace, test gate, and final diff remain
trusted LocalCode code.

Gate: local and hosted transports cross the same validator; secrets never enter
the repository; `--apply` requires `git apply --check` and remains unstaged.

## 022 — Interactive chat and visible reasoning

Add a persistent-session chat REPL, live event/reasoning rendering, cumulative
diff/status/context commands, and explicit apply delivery. Extend workspace
exclusions for build output and secret directories, and keep chat exploration
free from the rigid one-shot phase policy.

Gate: a real repository can be inspected safely, follow-up requests reuse the
disposable workspace, and headless/TUI behavior remains owned by the same loop.

## Proposed 3–5 day prototype sprint

This schedule is for a working teaching prototype, not a credible completed
SWE-bench study:

| Day | Focus | Honest deliverable |
|---|---|---|
| 1 | Milestones 001–003 | safe deterministic repository tools |
| 2 | Milestones 004–006 | local model plus bounded read-only loop |
| 3 | Milestone 007 | tested editing on micro-repositories |
| 4 | Milestone 008 and TUI shell | retrieval experiment and live event view |
| 5 | Milestone 009 on 1–3 tasks | benchmark harness proof and documented blockers |

A full 20-task, four-configuration benchmark may take longer because model
inference, image builds, test execution, and failed-environment diagnosis are
real experimental work. We will report elapsed time rather than forcing it into
the estimate.
