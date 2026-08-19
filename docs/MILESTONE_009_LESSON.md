# Milestone 009 lesson — real benchmark harness proof

## Outcome

LocalCode now has a real, pinned evaluation boundary separate from the
micro-repository suite. The frozen manifest is `benchmarks/real_benchmark/manifest_v1.json`:

- dataset: `SWE-bench/SWE-bench_Verified`, `test` split;
- dataset revision: `hf-main-03e151cf5560b1af6a4363c6a9d766deaaea6b56`;
- fixed selection seed: `20260813`;
- exactly 20 unique instance IDs and exact base commits;
- maximum five instances per repository; and
- configurations kept in `B0`, `A1`, `A2`, `A3` order.

The runner writes the official prediction shape:

```json
{"instance_id":"owner__repo-123","model_name_or_path":"localcode/config","model_patch":"diff --git ..."}
```

Gold patches are available only to the explicit harness-control adapter. The
issue resolver passes the problem statement, repository, and base commit to an
agent producer; it does not expose `patch`, `test_patch`, or evaluator logs.

## Reproduce the controls

The dataset snapshot is local and ignored by Git. From the repository root:

```bash
PYTHONPATH=src .venv-realbench/bin/python scripts/run_real_benchmark.py \
  --dataset data/raw/swebench_verified_test.jsonl \
  --run-id m009-empty-vN \
  --runs-root runs \
  --evaluation-root . \
  --python .venv-realbench/bin/python \
  --control empty \
  --max-workers 1 \
  --cache-level base
```

The empty control measured `0/20` for every configuration. Its per-instance
failure category is `LOOP_CONTROL` because no patch was supplied.

The first gold control measured one pinned Flask task under B0:

```bash
--control gold --control-id pallets__flask-5014 --configuration-id B0
```

The official Docker evaluator applied the gold patch and reported `resolved: 1`.
Docker built an x86 base/environment image under ARM emulation; this is real
harness evidence, not a micro-suite substitute. Both Ollama and OpenAI patch
producers are now connected, but the frozen 20 remains pending until the pilot
protocol is stable.

## Agent-visible public tests

Real repositories cannot reliably use the Mac host's Python environment.
Model-backed runs therefore default to `--agent-test-environment
swebench-docker`. The runner prepares only the selected instance images,
mounts only the candidate diff into `/testbed`, disables network access, runs
the repository's pinned public `test_cmd`, and preserves the bounded output
tail plus true exit status. It never exposes the gold patch, hidden test patch,
`FAIL_TO_PASS`, or evaluator script.

This public result guides the loop; it is not the benchmark verdict. The
official evaluator still runs separately and exclusively decides resolution.

## Read the implementation in this order

1. `benchmarks/real_benchmark/manifest_v1.json` — the frozen task contract.
2. `src/localcode/real_benchmark.py` — preparation, evaluation, comparisons,
   evidence files, and failure taxonomy.
3. `src/localcode/real_benchmark_adapters.py` — dataset resolver, agent/control
   producers, image preparation, and official evaluator.
4. `src/localcode/swebench_public_tests.py` — isolated public-test execution.
5. `scripts/run_real_benchmark.py` — CLI and one-instance control narrowing.
6. `tests/unit/test_real_benchmark.py` and
   `tests/unit/test_real_benchmark_adapters.py` — contract tests.

## What this proves

It proves that a pinned real-subset manifest, official prediction JSONL, Docker
harness, gold control, and empty control can be connected reproducibly.

It does not establish a representative B0/A1/A2/A3 solve rate. A hosted
three-repository ladder measured 0/3 in every treatment and diagnosed the map,
test-environment, and review-evidence defects fixed afterward. Every changed
protocol must use fresh run IDs and matched treatments.

The first post-repair gate is now complete: Luna A3 run
`m-luna-requests-a3-fixed-v1` produced the correct two-site Requests patch and
the official evaluator resolved 1/1. The run observed two public test executions
inside the pinned image before independent evaluation. This closes pathway
correctness, not generalization or the frozen-20 experiment.

The first A3 generalization gate is now complete at **1/3**. Flask resolved;
Pylint and Sphinx remained `FIX_INCOMPLETE`, and same-instance gold controls
resolved both. The Sphinx-only retry proved the corrected tool budget reaches
automatic testing and review. Its broad `class` to `obj` change still failed
the target test; the gold patch showed the required narrow `None` special case.
This is model/reviewer evidence, not an evaluator or controller failure.

## Explain-back check

1. Why is a gold control allowed to read `patch` while an agent resolver is not?
2. Why must the empty control be evaluated through the same prediction and
   evaluator path?
3. Why does a resolved gold Flask task not prove the selected 20 are all
   environment-compatible?
4. Which artifact contains the exact per-configuration predictions?
