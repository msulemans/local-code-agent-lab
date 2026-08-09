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
does not replace this milestone's future terminal UI, live runtime event stream,
or headless-versus-TUI equivalence gate.

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
