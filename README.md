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

Milestone 004A also freezes
the two-candidate model compatibility plan, exact tool schemas, 20-prompt
development pack, metrics, gates, and stop rules. Candidate 1 is downloaded and
verified. Its first compatibility run stopped safely after one prompt because
swap grew beyond the registered limit; the remaining gates are unevaluated. No
editing, repository test execution, or multi-turn agent loop exists yet. See
[the bake-off plan](docs/MODEL_BAKEOFF_PLAN.md).

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

## Current development commands

The runtime and offline bake-off contract use only Python 3.11's standard
library:

```bash
python3.11 scripts/check_model_bakeoff_contract.py
python3.11 scripts/check_model_extension_contract.py
PYTHONPATH=src python3.11 -m unittest discover -s tests/unit -v
```

These test configuration, events, adversarial read-only tool boundaries, the
two-candidate manifest, exact tool schemas, and the 20-prompt composition. They
do not load a model, edit the fixture, run the fixture's failing test, or start
an agent loop.
