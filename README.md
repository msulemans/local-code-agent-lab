# LocalCode Agent Lab

Build a small, local coding agent from first principles. The agent will inspect
a repository, reason about an issue, search and read code, edit files, run
tests, react to failures, retry, and return a reviewable Git diff.

This is phase 3 of the learning-labs sequence:

1. `open-model-training-lab` taught controlled model experiments.
2. `chess-training-lab` taught adaptation of a capable domain model.
3. `local-code-agent-lab` applies the same evidence discipline to an agent.

The project is not an API wrapper and will not delegate its loop to an existing
agent framework. A replaceable local or hosted model supplies predictions; this repository
owns tool definitions, parsing, context assembly, budgets, retry logic, event
history, safety boundaries, patch production, evaluation, and the terminal UI.

## Start here

Read these documents in order:

1. [Learning path](docs/LEARNING_PATH.md)
2. [Architecture](docs/ARCHITECTURE.md)
3. [Milestones and gates](docs/MILESTONES.md)
4. [Benchmark plan](docs/BENCHMARK_PLAN.md)
5. [Guide for Luna or another low-cost model](docs/LUNA_GUIDE.md)
6. [Canonical project state](AGENT_STATE.md)
7. [Local and online backend lesson](docs/ONLINE_BACKENDS.md)

The trusted/untrusted filesystem boundary is defined in the
[repository contract](docs/REPOSITORY_CONTRACT.md).

## Interactive learning field manual

Open the published field manual:

**https://msulemans.github.io/local-code-agent-lab/**

Or run it locally:

Run the dependency-free learning UI:

```bash
python3.11 scripts/serve_learning_lab.py
```

Then open `http://127.0.0.1:4173`. It teaches system anatomy, tool safety, the
future agent loop, benchmark design, failures, terminology, and explain-back
practice. See [the learning UI guide](docs/LEARNING_UI.md).

Do not start coding from the final architecture diagram. We will implement one
vertical capability at a time and stop at every gate.

## Version 1 definition of done

Version 1 is complete when all of the following are true:

- a pinned local model can emit one validated tool call;
- all repository actions go through our own typed tool layer;
- the loop records every observation and action as structured events;
- edits are confined to a disposable workspace;
- commands are constrained by an explicit execution policy;
- the agent can fix deterministic micro-repository tasks;
- four registered configurations are evaluated on the same pinned 20 issues;
- the final answer includes tests, limitations, and a Git diff;
- the TUI renders live events without owning agent logic; and
- the complete run can be reproduced from recorded configuration and hashes.

## Non-goals for Version 1

- autonomous work on the user's real repositories;
- unrestricted shell or network access;
- a VS Code extension, web IDE, or multi-agent swarm;
- training a coding model from scratch;
- claiming a leaderboard-quality SWE-bench score;
- hiding failures behind a polished UI.

## The scientific question

> With one fixed local model and fixed compute budget, which scaffolding
> capabilities measurably improve real issue resolution: a basic tool loop,
> repository retrieval, or a separate review pass?

The score is useful, but the transition evidence is more educational: which
instances change from failed to solved, and why?

## Current implementation

Milestone 007's offline gate now passes. Eight deterministic fake backends
drive eight distinct repairs through the actual runtime: repository inspection,
strict unified diffs inside disposable Git workspaces, registered tests under a
macOS sandbox, diff review, retry, and final answers. Completion is rejected
until a patch exists and the current patch has passing test evidence; any later
patch invalidates the pass.

The engineering registry exposes exactly six bounded tools: `list_files`,
`search_code`, `read_file`, `apply_patch`, `run_tests`, and `git_diff`. This is
real controller, filesystem, patch, process, and Git behavior driven by fake
model decisions. It is not proof that Qwen can solve the issues. The registered
suite now covers one-file behavior, a boundary regression, tests-first
discovery, syntax failure, cross-file evidence, misleading output, a failed
first patch with retry, and a two-file repair.

The terminal UI shell has been brought forward as a presentation-only observer.
`src/localcode/tui.py` renders immutable events and observations from the same
loop used by headless runs. Tests prove observer failures do not alter the loop
result, and the headless and TUI parser demos produce the exact same trace,
observations, final answer, and diff.

Milestone 008 has started with a deterministic retrieval primitive.
`src/localcode/retrieval.py` builds a repository map, ranks source/test
excerpts, excludes the already-supplied issue file, and reports relevant-file
recall under a fixed context budget. On the registered micro suite, the first
metric recalls all 9 expected changed paths across 8 cases with a 3-file budget.
`src/localcode/context.py` now makes this an explicit context treatment:
default loop context stays unchanged, while `RetrievalContextCompiler` adds
bounded retrieved evidence only when configured.

The experiment layer is now wired to the same frozen micro-suite manifest.
`benchmarks/experiment/manifest_v1.json` registers the benchmark ladder in
order: `B0`, `A1`, `A2`, `A3`. Today the runner measures `B0` as a true
single-shot baseline with one bounded patch attempt, plus the implemented loop
configurations (`A1` simple context and `A2` retrieval context), and `A3` as a
bounded review pass over its own A2-style candidate. This gives one place to compare
solved counts, paired transitions, and case-level evidence as more treatments
land.

The real-benchmark layer is wired to a pinned 20-instance SWE-bench Verified
manifest in `benchmarks/real_benchmark/manifest_v1.json`. It resolves issue
statements from an ignored local dataset snapshot, writes the official
prediction JSONL shape, and calls the official Docker evaluator through
`src/localcode/real_benchmark_adapters.py`. The real producer now implements
four distinct treatments: B0 is one mapped single-shot patch, A1 is the simple
tool loop, A2 adds retrieval, and A3 adds a fresh test-read-only review. Hosted
A3 run `m-online-terra-requests-a3-v2` officially resolved
`psf__requests-2931` (1/1), proving the complete issue-to-evaluator path with a
real model. This is one pilot solve, not a 20-issue score. See
[the dual-backend lesson](docs/ONLINE_BACKENDS.md).

After the three-repository ladder exposed harness defects, post-repair Luna A3
run `m-luna-requests-a3-fixed-v1` repeated the Requests pathway with compatible
Docker public tests and officially resolved 1/1. It used 14 total tool calls, 2
test executions, 2,528 generated tokens, and about 60.4 seconds. This validates
the repaired pathway; it still does not constitute a representative score.

The subsequent Flask/Pylint/Sphinx A3 generalization gate finished at **1/3**.
Flask resolved; Pylint and Sphinx were valid patches but `FIX_INCOMPLETE`.
Resolving gold controls cleared both evaluator environments. The Sphinx retry
also proved the automatic-test budget repair: it completed agent and review
phases without negative budgets, but Luna globally weakened annotation roles
where the required fix narrowly special-cased `None`. The reviewer is now
explicitly allowed to replace a wrong core idea and must compare patch scope
with the exact issue and existing public-test evidence.

A fresh matched Matplotlib/xarray/pytest ladder then measured the complete
`B0 → A1 → A2 → A3` sequence in one run. Gold controls resolved 3/3, while Luna
resolved **0/3 in every treatment**. A2 increased valid patches from 0 (B0) and
1 (A1) to 3, but none passed the official target behavior. A3 produced only 2
valid patches, added compute, and introduced regression failures. This is a
useful negative result: the runtime and evaluator work, retrieval improves
localization, and the remaining limit is repair comprehension/review quality.
Hosted runs freeze the same sampling settings, but seed equality is claimed
only when the backend supports deterministic seeding.

Phase 4 now begins with a leakage-safe training-data contract rather than a
model download. `src/localcode/training_data.py` defines four repair task types,
canonical immutable records, deterministic lineage-group splits, licence and
source-revision provenance, exact-content overlap detection, corpus hashes, and
automatic denial of every pinned SWE-bench evaluation ID and base revision.
The registered policy lives in
`benchmarks/training_data/manifest_v1.json`. Milestone 014 also pins and verifies
the CommitPackFT Python shard, normalizes 2,000 deterministic
`broken_to_corrected` examples, and writes a rejection report. Bulk raw and
processed data remain ignored and reconstructable; no trained adapter is
claimed yet. Milestone 015 has now pinned Qwen2.5-Coder-1.5B-Instruct and the
MLX environment, recorded an untouched validation-loss baseline, and passed a
two-update LoRA save/reload probe at 4.046 GB peak active memory. Full training
was gated on a six-case executable base-model baseline. The untouched model
solved 4/6 at 3.286 GB peak active memory; it preserved zero sealed examples.
Milestone 016 now freezes one bounded command for the overfit diagnostic,
train-only LoRA run, complete-validation checkpoint selection, and unchanged
six-case comparison. Run it in normal Terminal:

```bash
PYTHONPATH=src .venv-mlx/bin/python scripts/run_m016_training.py \
  --run-id m016-lora-v1
```

See
[the Phase 4 lesson](docs/PHASE_4_TRAINING.md).

Real agent runs now execute repository-owned public tests in the pinned
SWE-bench instance image by default. The runner prepares selected images,
mounts only the candidate diff, disables container networking, and retains a
bounded output tail. Gold patches, hidden tests, and evaluator scripts stay
outside the agent; only the official evaluator may set `resolved=true`.

Milestone 006 provides the bounded multi-turn foundation. A strict decision
protocol distinguishes tool proposals from final answers; explicit budgets
bound turns, invalid actions, tool calls, repeated actions, wall time, and
context. Fake-backend tests cover every registered termination reason.

Milestone 005 now has an offline one-turn controller proof built on the four
bounded read-only functions from Milestone 003:
`src/localcode/tools/`:

- `list_files`;
- `read_file`;
- `search_code`; and
- `git_diff`.

They share one repository path and exclusion policy. A strict version-1 action
validator accepts one JSON envelope, rejects malformed or unknown actions as
observations, and dispatches at most one validated read-only call through an
exact registry. A fake backend proves deterministic event sequences without
loading Ollama.

A loopback-only Ollama backend adapter now converts exactly one native tool
proposal into the same protocol envelope without repairing its tool name or
arguments. Fake-client tests cover the complete backend-to-fixture path; the
real Qwen3.5 smoke remains deferred until a clean host baseline is available.
A separate multi-turn Ollama adapter now maps native calls into strict loop tool
decisions and bounded plain content into final decisions. A three-response fake
transport crosses patch, test, and final turns; this still does not count as a
real-model run. The corresponding engineering smoke harness now connects that
adapter to a disposable workspace, all six tools, completion requirements,
per-turn resource checks, trusted final-diff capture, and a unique atomic run
record. Fake Ollama tests prove the full connection without claiming model
quality.
A parallel OpenAI Responses adapter now exposes the same phase-limited function
tools and returns the same protocol-v1 decisions. It deliberately skips local
Ollama memory gates while preserving every controller, workspace, test, review,
diff, and evaluator boundary. See [the dual-backend lesson](docs/ONLINE_BACKENDS.md).
A dedicated smoke preflight parses the macOS swap and memory evidence and the
Ollama process list before inference is reachable. Retained swap or any loaded
model blocks the run with a typed error and zero chat requests.

Milestone 004A also freezes
the two-candidate model compatibility plan, exact tool schemas, 20-prompt
development pack, metrics, gates, and stop rules. Candidate 1 is downloaded and
verified. Its first compatibility run stopped safely after one prompt because
swap grew beyond the registered limit; the remaining gates are unevaluated.
That model evidence is historical and separate from the newer offline runtime.
See [the bake-off plan](docs/MODEL_BAKEOFF_PLAN.md).

The unloaded-host check then showed healthy current memory pressure but about
36.1 GiB of retained swap. The next experiment must start after a clean macOS
restart and a new baseline capture; run v1 remains immutable.

After restart, the approved baseline was 0 MiB swap, 91% free memory, and an
empty `ollama ps`. Run ID `m004c-qwen25-7b-v2` is registered for the unchanged
candidate-1 compatibility rerun. That run completed all prompts and context
probes with zero swap and healthy latency, but failed tool schema (0/12) and
action-decision (1/16) gates while passing reasoning (3/4). Candidate 2 is now
downloaded and independently hash-verified. Its official config descriptor has
a recorded three-byte size metadata inconsistency, but all four content hashes
match. Its approved pre-run baseline is zero swap, 73% free memory, and no
loaded Ollama model.

Candidate 2's first guarded run then stopped after one prompt: it produced a
native schema-valid tool call, but grew swap by about 2.53 GiB from a clean
zero-swap baseline. Neither candidate passes compatibility, so the next step is
an offline review—not a rerun or relaxed safety gate.

That offline review shows a strict candidate-1 JSON adapter would reach only
10/12 schema-valid calls and 6/16 correct decisions, still below both gates.
See [the compatibility review](docs/COMPATIBILITY_REVIEW.md). The next model, if
approved, is registered in a separate experiment extension as
`qwen3.5:9b-q4_K_M`. Its manifest, all four blob hashes, and descriptor sizes
verify; it has not been run. A clean post-restart host baseline is required
before inference. The learner chose not to restart yet, so the real-model
Milestone 005 smoke test is explicitly deferred; the fake-backend protocol
gate passes offline.

The one-turn smoke entry point is `scripts/smoke_one_turn_ollama.py`. Do not run
it in a retained-swap session. Its offline tests prove that only zero swap and
an empty Ollama process list can reach the single controller turn. Every CLI
attempt reserves a unique `runs/one-turn-smoke/<run-id>/` directory and updates
its `run.json` atomically with the baseline, events, observation or typed
failure, and exit code. Existing run directories are never reused.

The current repair-level entry point is
`scripts/smoke_engineering_ollama.py`. It targets only the registered
`parser-none` fixture, permits at most ten model turns and eight tool calls,
requires an applied patch plus current passing tests, and captures the final
diff itself. It also checks the frozen 2 GiB swap-growth and 5% free-memory
limits before and after every inference. Do not run it unless `vm.swapusage`
shows zero used swap and `ollama ps` is empty.

## Current development commands

The runtime and offline bake-off contract use only Python 3.11's standard
library:

```bash
python3.11 scripts/check_model_bakeoff_contract.py
python3.11 scripts/check_model_extension_contract.py
PYTHONPATH=src python3.11 -m unittest discover -s tests/unit -v
PYTHONPATH=src python3.11 scripts/run_micro_suite.py
PYTHONPATH=src python3.11 scripts/run_experiment.py
# after installing the ignored benchmark environment and downloading the
# ignored local dataset snapshot:
PYTHONPATH=src .venv-realbench/bin/python scripts/run_real_benchmark.py \
  --dataset data/raw/swebench_verified_test.jsonl \
  --run-id m009-empty-vN --control empty --max-workers 1
```

These test configuration, events, adversarial tool boundaries, the bounded
agent loop, disposable workspace, patch policy, sandboxed test execution, the
two-candidate manifest, exact tool schemas, and the 20-prompt composition. They
do not load a model; fixture tests execute only in disposable workspaces.

Run the complete offline repair in normal Terminal because a restrictive outer
sandbox may prevent macOS from applying a nested test sandbox:

```bash
PYTHONPATH=src python3.11 scripts/demo_engineering_agent.py
```
