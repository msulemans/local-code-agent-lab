# Milestone 007 lesson — guarded editing and sandboxed tests

## Outcome

LocalCode has completed its first full offline coding-agent repair:

```text
issue
  -> search_code
  -> read_file
  -> apply_patch
  -> run_tests
  -> git_diff
  -> final answer
```

The decisions come from a deterministic fake backend. The repository search,
file read, patch application, test subprocess, Git diff, budgets, observations,
and events are real runtime behavior. This proves our agent machinery; it does
not prove that Qwen can choose the same successful sequence.

Milestone 007's offline gate now passes. The registered suite contains eight
distinct micro-repository issues and solves all eight through the guarded
runtime while leaving every source fixture unchanged.

## Why use a disposable workspace?

Running an agent directly against a source fixture would mix three things:

- the immutable problem definition;
- the agent's experimental edits; and
- later evaluator evidence.

`src/localcode/workspace.py` copies only allowed regular files into a new
directory, rejects symlinks and source/destination overlap, enforces file and
byte caps, and creates a private clean Git baseline. The original fixture is
never the patch target.

This gives every attempt a known starting point and makes failed patches safe
to inspect and discard.

## What makes `apply_patch` guarded?

`src/localcode/patches.py` accepts a strict, bounded unified diff rather than a
general file-writing command. Before Git applies anything, trusted Python
checks that the patch:

- stays inside the workspace;
- targets existing tracked UTF-8 files;
- contains no symlink, secret, binary, create, delete, rename, copy, or mode
  change;
- stays within patch-byte, file-count, changed-line, and editable-file limits;
- contains valid file and hunk headers; and
- does not coexist with staged or untracked changes.

`git apply --check` then verifies that the diff matches the current file before
the actual apply. A second patch may revise existing unstaged edits, which is
necessary for the observe-failure-fix-retry loop.

## Why `run_tests` is not a terminal

The model selects a registered name such as `python-unittest`; it never supplies
an arbitrary shell command. `src/localcode/test_runner.py` expands that name to
an exact argument tuple owned by trusted code.

The runner adds five independent bounds:

1. a maximum wall-clock timeout;
2. a maximum captured-output size;
3. a dedicated process group that is killed on either limit;
4. a minimal environment and dedicated temporary directory; and
5. a macOS sandbox profile that denies network, child-process execution,
   workspace writes, and reads outside the workspace and Python runtime.

Tests are therefore observers of a prepared workspace, not another editing or
exfiltration tool. The test result records the registered command name, exit
code, duration, timeout flag, output-limit flag, and `sandboxed=true`.

When this command is itself launched inside another restrictive sandbox,
macOS may refuse to nest `sandbox-exec`. LocalCode reports the typed
`sandbox_unavailable` error instead of quietly running without isolation. Run
the demonstration from normal Terminal.

## Completion is trusted policy

The model may claim success too early. `CompletionRequirements` lets the loop
reject a final answer until:

- at least one guarded patch was applied; and
- the current patch has a passing registered test result.

Applying another patch resets the passing-test flag. The agent must test the
new code again. Successful patch application also clears repeated-action
signatures so a revised patch can legitimately rerun the same named tests.

The model describes completion; trusted Python decides whether the evidence is
current enough to permit it.

## Run one complete repair

From the repository root in normal Terminal:

```bash
PYTHONPATH=src python3.11 scripts/demo_engineering_agent.py
```

The important evidence is:

```text
editing    tool_result  Tool apply_patch completed.
verifying  tool_result  Tool run_tests completed.
reviewing  tool_result  Tool git_diff completed.
completed  final_answer Model returned a final answer.
```

The printed test metadata must show exit code 0 and `sandboxed: true`. The diff
must add the `None` guard, termination must be `final_answer`, and `SOURCE
FIXTURE UNCHANGED` must be `True`.

## Run the live terminal UI shell

From the repository root in normal Terminal:

```bash
PYTHONPATH=src python3.11 scripts/demo_localcode_tui.py
```

This command uses the same fake repair runtime as the headless demo, but passes
a `TerminalEventStream` observer into `AgentLoop`. The UI should show searching,
reading, editing, running tests, reviewing the diff, and final completion.

The important boundary is not the box drawing. The important boundary is that
the TUI receives immutable `Event` and `ToolResult` values after trusted runtime
code records them. It cannot validate model output, call tools, retry actions,
approve completion, or change the final diff.

## Run the registered eight-case suite

From normal Terminal:

```bash
PYTHONPATH=src python3.11 scripts/run_micro_suite.py
```

The suite covers:

| Case | Engineering behavior |
|---|---|
| `parser-none` | one-file behavior fix |
| `discount-boundary` | exact-boundary regression |
| `display-whitespace` | tests-first discovery |
| `label-syntax` | observe import failure, patch, retest |
| `catalog-sku` | trace behavior across collaborating files |
| `fallback-port` | ignore misleading warning and fix the assertion cause |
| `ratio-retry` | wrong first patch, failed test, revised patch, passing retest |
| `username-consistency` | one guarded patch across two existing files |

The required summary is:

```text
SUMMARY {"milestone_ready": true, "minimum_solved": 8, "registered": 8, "solved": 8, ...}
```

The plans are scripted model-shaped decisions. Gold patches stay in the trusted
suite manifest and are never copied into the target workspace or supplied in
the issue/context. A future local-model treatment must receive only the issue
and runtime observations.

## Executable proof

```bash
PYTHONPATH=src python3.11 -m unittest discover -s tests/unit -v
node tests/ui/rendered-html.test.mjs
```

The last normal-Terminal gate before Milestone 008 retrieval was 136 tests in
6.451 seconds with `OK` and zero skips. After the first retrieval slice, the
current project suite contains 140 tests. In the Codex sandbox, nested macOS
sandbox canaries may be skipped; normal Terminal is the stronger evidence for
the test-runner isolation claims. The UI contract verifies that this lesson is
represented without remote assets or inline scripts.

## Read the implementation in this order

1. `src/localcode/workspace.py` — copy and Git-baseline isolation.
2. `src/localcode/patches.py` — strict diff policy and application.
3. `src/localcode/test_runner.py` — named commands and process sandbox.
4. `benchmarks/micro_agent/tool_schemas.json` — exact six-tool surface.
5. `src/localcode/engineering_registry.py` — one workspace-bound dispatcher.
6. `src/localcode/loop.py` — completion evidence and retry invalidation.
7. `src/localcode/demo_repair.py` — shared deterministic repair runtime.
8. `scripts/demo_engineering_agent.py` — headless repair formatter.
9. `src/localcode/tui.py` and `scripts/demo_localcode_tui.py` — event-driven
   terminal view.
10. `src/localcode/micro_suite.py` and
   `benchmarks/micro_agent/suite_v1.json` — registered suite and scoring gate.
11. `src/localcode/backends/ollama_loop.py` — local-model loop transport.
12. `tests/unit/test_workspace_and_patches.py` and
   `tests/unit/test_test_runner.py` — adversarial safety claims.
13. `tests/unit/test_engineering_loop.py` — completion and revision claims.
14. `tests/unit/test_loop_observers.py` and `tests/unit/test_tui.py` —
    observer isolation and headless/TUI equivalence.
15. `tests/unit/test_micro_suite.py` and
    `tests/unit/test_ollama_loop_backend.py` — suite and model-boundary claims.
16. `src/localcode/engineering_smoke.py` — clean-host preflight, per-turn
    resource gates, disposable repair run, and trusted final-diff capture.
17. `src/localcode/engineering_smoke_records.py` — unique atomic evidence for
    baseline, resources, events, observations, tests, diff, and termination.
18. `scripts/smoke_engineering_ollama.py` — the single registered real-model
    parser repair entry point.

## Explain-back check

1. Why must the fixture and the edited workspace be different directories?
2. Why is a strict patch safer and more measurable than a general write tool?
3. Why does a named test command still need a sandbox?
4. Why must a later patch invalidate an earlier passing test result?
5. Why must the TUI observe the loop instead of calling tools?
6. What does the fake backend prove, and what does it leave unproven?

Good answers mention reproducibility, capability limits, hostile repository
code, evidence freshness, presentation-only observers, and the separation
between runtime correctness and model quality.

## The real-model repair gate

The multi-turn Ollama adapter and repair harness are now implemented. A fake
Ollama sequence crosses real search, read, guarded patch, registered tests, and
final termination in a disposable workspace. Trusted code then captures the
final Git diff even if the model never requests `git_diff`.

The real command is intentionally narrow:

```bash
PYTHONPATH=src python3.11 scripts/smoke_engineering_ollama.py \
  --run-id m007-qwen35-parser-v1
```

Do not run it from a retained-swap session. Before any chat request, it requires
zero used swap and an empty Ollama process list. Around every later inference,
it stops before tool execution if swap growth exceeds 2 GiB or free memory
falls below 5%. Each attempt owns a new
`runs/engineering-smoke/<run-id>/run.json`; a run ID is never reused.

The current host observation is 3612.62 MiB retained swap, 39% free memory, and
no loaded Ollama model. That means offline engineering is safe to continue, but
the real Qwen repair is not scientifically attributable yet. Keep the scripted
`8/8` as the controller/runtime control; never report it as Qwen's score.
Retrieval begins only after the simple local-model agent has an independently
recorded baseline.
