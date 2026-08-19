# Local and online model backends

## The outcome

LocalCode now supports two inference transports behind the same agent runtime:

```text
                    Ollama local model
                   /                  \
issue -> LocalCode controller          -> one validated decision
                   \                  /
                    OpenAI Responses API

validated decision -> local tool -> local observation -> next bounded turn
```

The online backend does **not** turn the project into an API wrapper. The model
can only propose one typed decision. LocalCode still owns repository cloning,
context retrieval, action validation, file access, patching, test execution,
budgets, retries, A3 review, diff export, and official SWE-bench evaluation.

## Why add a hosted model?

The local GPT-OSS pilot proved that the engineering loop works, but the 32 GB
host has model-memory limits and the observed local model is high-variance. A
hosted model lets us separate two questions:

1. **Agent question:** Is LocalCode's loop, retrieval, review, and evaluator
   capable of solving the issue?
2. **Model question:** How much quality do we lose when inference moves from a
   stronger hosted model to an affordable local model?

Both are valuable measurements. We keep Ollama as the local treatment and add
OpenAI as a comparison treatment; we do not hide or replace either result.

## Security and privacy boundary

- Set `OPENAI_API_KEY` only in the shell environment.
- Never paste the key into chat, source code, `.env`, traces, or run artifacts.
- The API receives the issue and the bounded compiled context. Tool execution
  and tool results remain controlled locally.
- Repository exclusion rules still prevent secret-like files from entering
  retrieval and tool observations, but use only public or approved repositories
  for hosted experiments.
- Requests use `store: false`, one tool at a time, and no provider-hosted shell.

## First verified experiment

Use a hidden terminal prompt so the key is not stored in shell history:

```zsh
read -s "OPENAI_API_KEY?OpenAI API key: "; export OPENAI_API_KEY; echo
```

The first hosted comparison used one public SWE-bench issue, matching the
earlier Requests pilot. This produces and evaluates a real patch; it is not a
compatibility smoke test:

```bash
PYTHONPATH=src .venv-realbench/bin/python scripts/run_real_benchmark.py \
  --dataset data/raw/swebench_verified_test.jsonl \
  --run-id m-online-terra-requests-a2-v1 \
  --runs-root runs \
  --evaluation-root . \
  --python .venv-realbench/bin/python \
  --producer openai \
  --model gpt-5.6-terra \
  --configuration-id A2 \
  --instances psf__requests-2931 \
  --reasoning-effort medium \
  --max-workers 1 \
  --cache-level base \
  --tui
```

No Ollama process, zero-swap baseline, model download, or local model restart is
required for this backend. Docker is still required for the official SWE-bench
evaluation after a patch is produced.

Docker is also the default environment for agent-visible public tests on real
issues. The CLI prepares selected instance images before inference, and
`run_tests` exposes only `repository-tests`. The container has no network and
receives only the candidate diff. `--agent-test-environment host` exists for an
explicit diagnostic comparison, not a scored real-issue run.

## How to read the result

- `patch_status=produced` means the agent exported a syntactically valid Git
  diff after observing at least one local test execution.
- `resolved=true` means the official SWE-bench evaluator passed. Only this is a
  solve.
- `FIX_INCOMPLETE` means a valid patch failed one or more evaluator tests.
- `LOOP_CONTROL` means no valid patch crossed the bounded loop.
- Token, tool-call, wall-time, invalid-action, and test-execution evidence is
  recorded in the normal benchmark run directory.

## Observed result

The A2 run produced a valid patch but resolved `0/1`: it fixed the target path
while introducing one peer-to-peer regression. That is useful evidence, not a
transport failure.

A3 then added a fresh review and revision. The first review attempted to change
a test, so the runtime was strengthened to make tests read-only during review.
The corrected run `m-online-terra-requests-a3-v2` produced a two-site patch in
`requests/models.py`; the official evaluator passed the target test and every
peer-to-peer test and reported **resolved `1/1`**.

The successful attempt used about 44.4 seconds, 1,960 generated tokens, and 11
tool calls across agent and review. Phase evidence is now recorded separately,
so review exhaustion cannot be hidden behind the agent's earlier final answer.

## What the four configurations now mean

| ID | Treatment | Real-run contract |
|---|---|---|
| B0 | Single-shot base | Issue plus bounded repository map; only one `apply_patch` decision; no tool loop or retry |
| A1 | Simple agent | Typed tools, recent-history context, edit/test/retry loop |
| A2 | Retrieval agent | A1 plus ranked source and test excerpts |
| A3 | Agent plus review | A2 plus one fresh, bounded, test-read-only critique/revision phase |

Running `--configuration-id A3` intentionally reports B0/A1/A2 as unavailable:
the command measured only A3. A comparable ladder requires four runs over the
same instance IDs, model, budgets, and evaluator conditions, then a combined
summary. The first three-repository ladder measured 0/3 for every treatment and
revealed three harness defects: B0 omitted relevant late-map paths, host Python
gave incompatible test evidence, and A3 lost prior test evidence. Those
capabilities are now repaired. The next paid gate is one fresh matched pilot
with new run IDs, not a rerun of the unchanged experiment.

## Post-repair Luna result

The fresh gate passed. `m-luna-requests-a3-fixed-v1` ran `gpt-5.6-luna` on
`psf__requests-2931` under A3 with `swebench-docker` public tests. The agent
changed `_encode_params`; the reviewer added the related URL call-site
conversion. Both phases finished normally, the run recorded 0 invalid actions,
2 tests, 14 tools, 2,528 generated tokens, and 60.448844 seconds, and the
official evaluator reported **resolved 1/1**.

This closes the repaired single-issue pathway gate. Do not repeat this Requests
run. The next benchmark question is whether the same fixed treatment generalizes
across a small matched multi-repository subset.

## First generalization result

`m-luna-generalization-a3-v1` measured Flask, Pylint, and Sphinx under A3:

- Flask resolved with a focused patch.
- Pylint remained unresolved with a valid but incomplete patch. A same-instance
  gold control resolved, proving the environment was sound and the missing
  dependency/configuration plus migration behavior belonged to the fix.
- Sphinx reached the correct file and an edit, but automatic testing exceeded
  the 12-call tool budget and crashed event construction before export.

The controller now reserves the automatic-test slot and uses 14 tool slots for
real agent phases. Sphinx-only retry `m-luna-sphinx-a3-budget-fixed-v1` then
completed agent execution and A3 review without a negative budget, proving the
repair. The official target test still failed: Luna changed every annotation
reference from `class` to `obj`, while resolving gold control
`m-luna-sphinx-gold-v1` changed only the `None` special case. The final A3
generalization result is therefore **1/3**: Flask resolved, while Pylint and
Sphinx were `FIX_INCOMPLETE` under sound evaluator controls.

The accepting Sphinx review exposed a general instruction flaw: it had been
told never to undo the candidate's core fix. Review now treats that idea as
untrusted, checks narrow named behavior against broad semantic changes, and
must acknowledge supplied public-test evidence. Do not rerun the same three
paid issues merely to tune against their gold answers.
