# Architecture

## System boundary

```text
                          LocalCode

 Issue + repo ──> Run controller ──> Context compiler ──> Local model backend
                        ^                                      |
                        |                                      v
                 Structured event <── Tool result <── Action validator
                        |                              |
                        v                              v
                  JSONL run trace                 Tool registry
                        |                 list/search/read/edit/test/diff/shell
                        v                              |
                  Terminal UI <───────────────────────┘

 Evaluation harness is outside this boundary. It receives only the final patch
 and independently decides whether the benchmark task is resolved.
```

## Components and ownership

### `ModelBackend`

Owns tokenization and local inference only. It accepts messages plus registered
tool schemas and returns model text/tool calls plus token counts. It does not
read files, execute commands, manage retries, or decide benchmark success.

Initial adapters may use MLX-LM or llama.cpp as inference engines. That does not
make the project a wrapper: they replace matrix kernels and token generation,
not our agent behavior.

### `RunController`

Owns the state machine, budgets, repeated-action detection, tool dispatch,
termination, and final result. Suggested states:

```text
CREATED -> INSPECTING -> EDITING -> VERIFYING -> REVIEWING -> COMPLETED
              |            |           |             |
              +------------+-----------+-------------+-> FAILED/BUDGET_EXHAUSTED
```

Do not encode the loop as an unbounded `while True`. Every transition must
consume a declared budget and produce an event.

### `ContextCompiler`

Constructs the next model input from the issue, repository summary, recent
events, selected file excerpts, test failures, and remaining budgets. It owns:

- per-item and total token limits;
- line-numbered excerpts;
- deduplication by content hash;
- truncation notices;
- old-history summarization; and
- separation of instructions from untrusted repository text.

Repository files and issue text are data, not trusted instructions.

### `RetrievalPlanner`

Builds a deterministic repository map and selects bounded source/test excerpts
before the next model request. It may score paths, symbols, tests, callers, and
content proximity, but it must not generate patches, inspect gold/evaluator
material, or change tool/edit budgets. Its first development metric is
relevant-file recall under a fixed evidence budget.

### `ActionValidator`

Parses a versioned JSON action envelope, rejects unknown fields/tools, checks
types and sizes, applies declared defaults, and canonicalizes harmless path
syntax. Repository policy is then enforced independently by the selected tool
before it reads anything. Invalid actions and tool-policy failures become
observations; they are never executed optimistically.

Proposed envelope:

```json
{
  "protocol_version": "1",
  "thought_summary": "Need to find parser entry points and failing tests.",
  "action": {
    "tool": "search_code",
    "arguments": {
      "query": "parse(",
      "path": ".",
      "glob": "*.py",
      "max_results": 40
    }
  }
}
```

Store concise rationale, not hidden chain-of-thought. The useful evidence is
the hypothesis, chosen action, observation, and next decision.

### `ToolRegistry`

Version 1 tools:

| Tool | Purpose | Important boundary |
|---|---|---|
| `list_files` | bounded repository map | ignores VCS, artifacts, secrets |
| `search_code` | literal/regex text search | result and file caps |
| `read_file` | line-numbered excerpt | repository-relative regular files only |
| `apply_patch` | guarded unified diff | no path escape; size cap; dry validation |
| `run_tests` | approved commands | timeout, output cap, isolated process |
| `git_diff` | current patch/status | read-only and bounded |
| `terminal` | exceptional approved command | disabled initially; strict policy |

Prefer semantic tools over a general terminal. `terminal` is not a shortcut for
missing tool design.

### `WorkspaceManager`

Creates a disposable copy/worktree, records the starting commit, rejects paths
outside its root, snapshots status, and removes or archives the workspace after
the run according to policy. Benchmark test execution belongs in its container,
not on the user's host checkout.

### `EventStore`

Appends immutable JSONL events. Minimum event fields:

```text
schema_version, run_id, sequence, timestamp, event_type, state,
tool/action summary, observation summary, artifact references, budgets_remaining
```

Large outputs live as hashed artifacts; the event stores a bounded preview and
path. Never log tokens, environment secrets, private keys, or entire `.env`
files.

### `Reviewer`

The reviewer is optional and disabled in earlier configurations. It receives a
fresh compact context: issue, relevant evidence, patch, and tests. It returns
`accept`, `revise` with bounded findings, or `reject`. At most one revision loop
is allowed in Version 1.

### TUI

The TUI subscribes to structured events. It can render phase, file, test result,
elapsed time, and diff statistics, but cannot call tools directly.

The brought-forward shell implements that boundary with `LoopObserver` and
`TerminalEventStream`. The loop records immutable `Event` and `ToolResult`
values first, then notifies the observer. Observer exceptions are isolated, and
the shipped terminal stream queues rendering work outside the loop path. The
terminal renderer is therefore a view over the run, not a second controller.

## Security model

There are two different threats:

1. The model may propose unsafe actions.
2. The repository and its tests may contain hostile code or prompt injection.

Version 1 controls:

- disposable benchmark workspace/container;
- network off by default during agent execution;
- no host credentials mounted into the workspace;
- canonical repository-relative paths and symlink checks;
- command allowlist, argument validation, timeout, and output cap;
- process and total-run budgets;
- secret/path filtering in file tools and logs;
- explicit user approval for host-side or destructive actions; and
- independent evaluation after the agent stops.

Docker is a reproducibility and containment layer, not a proof of perfect
security. Do not run unknown benchmark tests with valuable host mounts.

## Suggested source layout

```text
src/localcode/
  cli.py
  config.py
  events.py
  controller.py
  context.py
  protocol.py
  policy.py
  workspace.py
  models/base.py
  models/mlx_backend.py
  tools/base.py
  tools/files.py
  tools/search.py
  tools/patch.py
  tools/tests.py
  tools/git.py
  review.py
  tui.py
tests/
  fixtures/micro_repos/
  unit/
  integration/
configs/
  base-model.yaml
  simple-agent.yaml
  retrieval-agent.yaml
  review-agent.yaml
runs/                 # ignored; immutable local evidence
benchmarks/manifests/ # IDs and metadata, never gold patches
```

This layout is a design target, not permission to scaffold everything at once.
