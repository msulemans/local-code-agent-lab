# Learning path

## What you are really learning

A coding agent is not just a model with shell access. It is a controlled system
that repeatedly turns state into action:

```text
issue + repository + history
              |
              v
       context compiler
              |
              v
        local model
              |
              v
   validated action or answer
              |
              v
 tool executes -> observation -> history -> retry
```

The model proposes. The runtime decides whether the proposal is valid, executes
safe actions, records facts, enforces budgets, and determines when the run ends.

By the end, you should be able to explain all of these without memorized jargon:

- why a language model alone cannot inspect a repository;
- why a tool schema is an interface contract, not a prompt decoration;
- why observations must be bounded before returning to the context window;
- why test output is new evidence for the next iteration;
- why an agent loop needs explicit success, failure, and budget termination;
- why retrieval quality and model intelligence are different variables;
- why a valid-looking patch is not a solved software issue;
- why benchmark infrastructure must be isolated from the agent workspace; and
- why a reviewer can help, harm, or merely consume more budget.

## Course modules

### Module 1 — The model/runtime boundary

Learn the difference between inference, orchestration, tools, and evaluation.
Build nothing yet. Draw the data flowing through one turn and identify which
component is trusted to enforce each rule.

Checkpoint question: if the model prints `rm -rf .`, which component prevents
execution, and why is “the prompt told it not to” insufficient?

### Module 2 — Typed repository tools without an LLM

Implement and test file listing, bounded reading, search, diff, and constrained
test execution. Drive them from fixtures or a scripted fake model.

Checkpoint question: can the complete tool layer be tested deterministically
when no model is installed? The answer must be yes.

### Module 3 — One local generation

Load one pinned quantized coding model, measure memory and tokens/second, and
require it to produce one schema-valid call. Do not add a loop yet.

Checkpoint question: did we prove the exact checkpoint and quantization work,
or merely that a model family is supposed to work?

### Module 4 — The first agent loop

Implement observe → decide → validate → act → observe. Start with read-only
tasks, then a tiny repository where one obvious edit fixes one test.

Checkpoint question: can the loop stop for success, invalid output, repeated
action, tool failure, and exhausted budget?

### Module 5 — Editing and repair

Add guarded patch application, targeted test runs, full verification, rollback
on invalid patches, and a final diff. Learn why “tests passed” must include the
exact command, exit code, and scoped limitations.

Checkpoint question: if the edit breaks syntax before tests begin, what event
does the model receive and what retry budget remains?

### Module 6 — Repository retrieval

Compare naive history with deliberate context selection: tree summaries, exact
symbol search, imports/callers, test proximity, deduplication, and token budgets.
Retrieval chooses evidence; it must not silently solve the issue itself.

Checkpoint question: why can adding more files reduce the solution rate?

### Module 7 — Evaluation science

Freeze model, prompts, tools, budgets, and 20 tasks. Run the base, simple-agent,
retrieval-agent, and review-agent configurations. Preserve every trace and
classify failures.

Checkpoint question: if retrieval gets more tokens or retries, have we measured
retrieval or simply spent more compute?

### Module 8 — Review and presentation

Add a clean reviewer pass that sees the issue, current diff, and test evidence.
It may accept, request one bounded revision, or reject. Then build the TUI as a
consumer of the same event stream used by tests and JSONL logs.

Checkpoint question: can the headless agent and TUI produce exactly the same
patch from the same recorded decisions?

## The recurring lesson format

Every milestone must be taught in this order:

1. **Mental model** — explain the concept in plain language.
2. **Prediction** — write what we expect before running anything.
3. **Small implementation** — change one capability only.
4. **Exact command** — provide a copyable command from the repository root.
5. **Observed evidence** — record output, exit code, timings, and artifacts.
6. **Explain-back** — answer three questions without looking at the code.
7. **Gate** — proceed, diagnose, or stop; never silently weaken the gate.
8. **State update** — append the decision to `AGENT_STATE.md`.

## Failure laboratory

Preserve at least one trace for each of these categories:

- invalid JSON or unknown tool;
- path escape attempt;
- oversized file or command output;
- search loop with no new information;
- patch does not apply;
- syntax or compilation failure;
- targeted tests pass but broader tests fail;
- model claims success without test evidence;
- tool budget exhausted;
- context budget exhausted;
- environment/build failure unrelated to the proposed patch; and
- reviewer changes a correct patch into a failure.

These are not embarrassing leftovers. They are the material that teaches how
agents actually fail.

## Interview-sized explanation

> I built a local coding agent around an open-weight coding model, but the main
> work was the runtime: typed repository tools, bounded context, safe patching,
> test feedback, termination rules, trace logging, and reproducible evaluation.
> I first proved each component on deterministic micro-repositories, then held
> the model and compute budget fixed across a pinned real-issue subset to measure
> the marginal value of the loop, retrieval, and a reviewer pass.
