# LocalCode Agent Lab

Build a small, local coding agent from first principles. The agent will inspect
a repository, reason about an issue, search and read code, edit files, run
tests, react to failures, retry, and return a reviewable Git diff.

This is phase 3 of the learning-labs sequence:

1. `open-model-training-lab` taught controlled model experiments.
2. `chess-training-lab` taught adaptation of a capable domain model.
3. `local-code-agent-lab` applies the same evidence discipline to an agent.

The project is not an API wrapper and will not delegate its loop to an existing
agent framework. A local open-weight model supplies predictions; this repository
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
bounded review pass over the `A2` result. This gives one place to compare
solved counts, paired transitions, and case-level evidence as more treatments
land.

The real-benchmark layer is now wired to a pinned 20-instance SWE-bench
Verified manifest in `benchmarks/real_benchmark/manifest_v1.json`. It resolves
issue statements from an ignored local dataset snapshot, writes the official
prediction JSONL shape, and calls the official Docker evaluator through
`src/localcode/real_benchmark_adapters.py`. The empty control measured `0/20`
for B0/A1/A2/A3, and the gold Flask control resolved
`pallets__flask-5014` under B0. This proves the evaluation boundary; it is not
yet a real-model solve score because a disposable real-repository patch
producer remains to be connected. See [the Milestone 009 lesson](docs/MILESTONE_009_LESSON.md).

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
