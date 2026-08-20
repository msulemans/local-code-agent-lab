# Phase 4 — train the model component

## Goal

Improve LocalCode's repair decisions with a small adapter trained on executable
coding-repair examples. The controller, tools, safety boundaries, test runner,
and evaluator remain unchanged. This isolates model improvement from agent
scaffolding improvement.

```text
public repair sources
        |
        v
provenance + licence gate
        |
        v
schema-v1 normalization -----> reject report
        |
        v
lineage-group hash split
   |         |          |
 train   validation   sealed test
   |         |          |
   v         v          | opened once
 adapter  selection ----+
        |
        v
Base model vs CodeLM inside the same LocalCode runtime
```

## Why the contract comes first

A training loss can decrease even when the dataset is duplicated, leaked,
unlicensed, or contaminated with evaluation answers. That produces a better
memorizer, not trustworthy evidence of a better coding model. Milestone 013
therefore freezes the data semantics before acquisition or training.

The four registered tasks are:

| Task | Input | Target |
|---|---|---|
| `issue_to_diff` | issue and bounded repository evidence | unified diff |
| `broken_to_corrected` | broken code and behavior contract | corrected code |
| `test_failure_to_patch` | failing command/output and relevant code | unified diff |
| `function_to_implementation` | signature, description, and local context | implementation |

Every example records a stable ID, repair lineage, source ID, repository,
revision, reviewed licence, instruction, input, target, changed paths, optional
test evidence, and its deterministic split.

## Leakage boundary

Related variants share one `lineage_id`, so SHA-256 splitting sends all of them
to the same partition. Exact input and target hashes are also checked across
partitions. The registered SWE-bench manifest is a denylist: its 20 instance
IDs and 20 exact base commits cannot enter training, validation, or the Phase 4
sealed test.

This matters because a gold patch used as training data would make later
"resolution" a memorization result. The validator rejects that boundary before
model code is reachable.

## Current evidence

Milestone 013 implements:

- immutable, canonical schema-v1 records;
- strict unknown/duplicate-field rejection;
- safe repository-relative changed paths;
- target-diff path agreement;
- deterministic 80/10/10 lineage splitting with seed `20260820`;
- exact input/target cross-split overlap detection;
- explicit source revision and reviewed-licence requirements;
- automatic pinned evaluation ID/revision denial;
- stable corpus SHA-256 summaries; and
- an offline contract/corpus validation CLI.

Run the contract gate:

```bash
PYTHONPATH=src python3.11 scripts/check_training_data_contract.py
```

The expected status before acquisition is
`contract_ready_no_corpus`. This is intentional: schema readiness is not a
claim that training data exists.

## Pinned seed corpus

Milestone 014 registers the CommitPackFT Python shard at revision
`fc56fe33c030c6daa414c2b112c932b8eed085e6`. The source manifest freezes the
exact 135,858,935-byte artifact and its SHA-256. Although the dataset card uses
MIT, every code record retains a repository licence; the seed builder accepts
only its reviewed permissive allowlist and preserves that licence per example.

Reconstruct the ignored local artifacts:

```bash
curl -fL -o data/raw/commitpackft-python-v1.jsonl \
  https://huggingface.co/datasets/bigcode/commitpackft/resolve/fc56fe33c030c6daa414c2b112c932b8eed085e6/data/python/data.jsonl
PYTHONPATH=src python3.11 scripts/build_training_corpus.py
PYTHONPATH=src python3.11 scripts/check_training_data_contract.py \
  --corpus data/processed/repair-training-v1.jsonl
```

The observed build reduced 56,025 raw rows to 25,989 eligible candidates, then
selected the stable lowest-hash 2,000. The corpus hash is
`4d7629c1a026559859abc3c28c596a18e21cc478b7ea8c6f7a65ccf99d53fafb`,
with 1,594 train, 211 validation, and 195 sealed-test examples. The rejection
report is evidence, not noise: ambiguous fork provenance, unapproved licences,
oversized inputs, duplicates, and the selection cap are counted separately.

These are commit-derived repair labels, not executable proof that every change
fixes a bug. They are useful for the first adapter experiment, while executable
tests remain authoritative for model promotion and LocalCode evaluation.

## What comes next

Milestone 015 selected the Apache-2.0 Qwen2.5-Coder-1.5B-Instruct checkpoint at
revision `cc932d8a05bf5a3dcd700f50584714d17fc4d03a`. MLX-LM 0.31.3 with MLX
0.32.1 passed a real Metal calculation, an untouched 211-row validation-loss
baseline (`1.383`, perplexity `3.988`), and a two-update LoRA probe. The probe
used 2.638M trainable parameters, finite losses `0.512 → 0.491`, 4.046 GB peak
active memory, and produced a loadable 10.56 MB adapter.

The development export contains 1,594 train and 211 validation rows; all 195
sealed rows are withheld. No development row exceeds 849 model tokens, so the
1,024-token ceiling loses no development example. The adapter probe is a
feasibility artifact, not a trained CodeLM and not a promotion result.

The executable baseline is now frozen as six development-only, one-file Python
repairs. Every case pins the issue, broken source, and evaluator test by
SHA-256. The model prompt contains the behavior report and broken file only;
the test source is never included. Greedy generation must produce one strict
`corrected_file` envelope, which trusted code writes into a disposable Git
copy before running the registered sandboxed test command. Raw output, diff,
test evidence, model identity, token counts, peak memory, and zero sealed rows
are preserved under an immutable run ID.

The untouched normal-Terminal run completed all six cases and solved 4/6 in
7.56 seconds at 3.286 GB peak active memory. It preserved trimming incorrectly
in `parser-none` and normalized only double spaces in `display-whitespace`;
those failures are frozen evidence rather than prompts to tune the suite.

Milestone 016 now runs a tiny overfit diagnostic before allowing the 1,600-
update train-only treatment. It evaluates every 200-update checkpoint against
all 211 validation rows, selects the lowest validation loss, and compares that
adapter against the unchanged 4/6 executable baseline. A non-improving adapter
is preserved as a valid negative result. Run it in normal Terminal:

```bash
PYTHONPATH=src .venv-mlx/bin/python scripts/run_m016_training.py \
  --run-id m016-lora-v2
```

The command streams progress and has a two-hour hard ceiling; approximately
45–70 minutes is expected on the verified M2 Max path. The sealed test stays
unavailable until this command selects one adapter using validation evidence.

The first diagnostic attempt stopped before full training because its gate
compared two different shuffled mini-batches. That was a runner error, not a
model failure: validation on the same eight rows improved `0.208 → 0.010`,
training reached `0.009`, and peak memory was 4.377 GB. The corrected v2 gate
requires same-row validation improvement and at least one lower observed train
loss; it does not pretend that the final random mini-batch equals the first.

The v2 full run then reached update 980 before macOS Metal stopped one command
buffer with `Impacting Interactivity`. This was not an out-of-memory failure:
peak active memory was 4.739 GB. Four complete checkpoints remain at updates
200, 400, 600, and 800; update 800 represents 171,707 supervised target tokens,
while the last reported training metric at update 980 represents 214,285.

Do not restart training just to recover evidence already on disk. The recovery
runner hashes those four checkpoints, evaluates each against all 211 validation
rows, selects by the same frozen lowest-loss rule, and runs the unchanged six
executable development cases:

```bash
caffeinate -dimsu env PYTHONPATH=src \
  .venv-mlx/bin/python scripts/recover_m016_checkpoints.py \
  --source-run-id m016-lora-v2 \
  --run-id m016-lora-v2-recovery-v1
```

This is a shortened-checkpoint recovery, not completion of the configured
1,600-update treatment. Its record keeps `original_1600_step_treatment_complete`
false and keeps the sealed split closed. It answers the immediate scientific
question—whether any safely saved adapter improves on 4/6—without resetting the
optimizer or silently changing the training treatment.

The recovery completed in 247.64 seconds. Full-validation loss selected update
200 at `1.333`, a small improvement over the untouched model's `1.383`.
Executable evidence contradicted that proxy: the adapter solved only 1/6 while
the untouched model solved 4/6. It retained strict output formatting but lost
repair behavior on the parser, boundary, whitespace, syntax, and fallback
cases. Only the zero-denominator ratio repair passed.

This is the key M016 result: lower commit-imitation loss did not imply better
executable repair. The selected adapter is not promoted, the sealed split stays
closed, and a longer run of the same treatment is not justified. The next
training treatment must improve data/metric alignment using executable repair
evidence rather than tuning the learning rate against these six development
cases. The concise versioned evidence is
`benchmarks/training/m016_recovery_result_v1.json`.

## M016b: executable-aligned correction

M016b changes the evidence, not merely the learning rate. It pins the official
SWE-smith Python dataset at revision `77cab905…`, then downloads only shard
`00000` (16,852,671 bytes; SHA-256 `302a383b…833d`). SWE-smith retains tasks
whose synthetic mutation breaks one or more unit tests and supplies an
executable environment. LocalCode accepts only one-file Python modifications
from ten explicitly reviewed permissive repositories.

The normalizer mechanically reverses each test-breaking mutation into its gold
repair. Model input contains the generated issue, FAIL_TO_PASS names, and
post-mutation broken hunk context. Original correct removed lines are excluded
from input, so the answer is not copied into the prompt. Repository-plus-file
lineages stay in one deterministic split, and a 300-example repository cap
prevents large projects from dominating.

The pinned shard produced 4,628 raw rows, 2,530 quality candidates, and 1,553
selected examples across ten repositories. Before tokenizer filtering the
split is 1,252 train, 235 validation, and 66 sealed. The pinned Qwen tokenizer
then keeps 755 train and 131 validation rows that fit completely within 1,024
tokens; it skips sealed rows before rendering or tokenization. No truncation is
silently treated as full supervision.

Checkpoint loss remains a selection aid, but promotion is executable. The
unchanged six development fixtures are forbidden from training. The untouched
model and future adapter receive the issue, an actually observed failing-test
output, and the broken file; they must return one strict unified diff. Trusted
code applies it in a disposable workspace and reruns the registered tests.
Run the new untouched baseline in normal Terminal:

```bash
caffeinate -dimsu env PYTHONPATH=src \
  .venv-mlx/bin/python scripts/run_m016b_patch_baseline.py \
  --run-id m016b-patch-base-v1
```

The frozen data evidence is `benchmarks/training/m016b_data_v1.json`. The
untouched strict issue-to-diff baseline measured `0/6`: all six responses were
rejected because they were not bare valid unified diffs. This is a protocol and
repair-quality baseline, not a runtime failure. Its immutable record is
`runs/training/m016b-patch-base-v1/run.json`.

The M016b LoRA treatment is frozen in
`benchmarks/training/m016b_lora_v1.json`. It trains for at most 800 updates,
selects among eight 100-update checkpoints using only the 131-row validation
split, and then runs the selected adapter on the unchanged six executable
development cases. Promotion requires at least one strict diff that applies,
changes the disposable fixture, and passes its registered test command.

Validate the contract without training:

```bash
PYTHONPATH=src .venv-mlx/bin/python scripts/run_m016b_training.py \
  --run-id m016b-lora-v1 --validate-only
```

Run the bounded training treatment in a normal macOS Terminal:

```bash
caffeinate -dimsu env PYTHONPATH=src \
  .venv-mlx/bin/python scripts/run_m016b_training.py \
  --run-id m016b-lora-v1
```

The command first runs a 40-update diagnostic and stops if loss or memory gates
fail. The full treatment has a two-hour wall limit and preserves every
100-update checkpoint plus its streamed metrics for diagnosis or recovery.

The first v1 diagnostic produced healthy early loss and memory evidence but
macOS stopped its Metal command buffer after update 5 as `Impacting
Interactivity`. It is retained as a failed systems result, not retried
unchanged. The v2 treatment keeps the target and executable promotion gate,
but caps sequences at 768 tokens and trains four LoRA layers. This retains 468
train and 80 validation examples while shortening each GPU backward step.

If Metal stops after saving one or more declared checkpoints, do not restart
the optimizer. Validate and executable-test the preserved weights with:

```bash
caffeinate -dimsu env PYTHONPATH=src \
  .venv-mlx/bin/python scripts/recover_m016b_checkpoint.py \
  --source-run-id m016b-lora-v2 \
  --run-id m016b-lora-v2-recovery-v1
```

Checkpoint 100 was a recovered negative (`0/6`): it emitted bare diffs, but
all six were rejected as malformed patches. V3 therefore continues those
hashed weights in seven separate 100-update MLX processes. MLX restores adapter
weights but not optimizer state, so the frozen treatment explicitly records an
optimizer reset between stages. This keeps each Metal process bounded and does
not mislabel the result as uninterrupted V2 training.

```bash
caffeinate -dimsu env PYTHONPATH=src \
  .venv-mlx/bin/python scripts/run_m016b_staged_training.py \
  --run-id m016b-lora-v3
```

The same recovery command also accepts a failed V3 run and compares every
cumulative checkpoint it actually preserved. This prevents a later Metal stop
from forcing either a restart or an arbitrary last-checkpoint choice.

The recovered V3 result is negative. Full validation selected checkpoint 100
(`1.754`) over checkpoint 200 (`1.794`), and the selected adapter solved `0/6`.
It learned bare diff syntax, but all six outputs were still invalid patches and
never reached test execution. Do not promote it, continue the same recipe, or
open the sealed split. The frozen verdict is
`benchmarks/training/m016b_recovery_result_v1.json`.

## M017: stronger untouched coding base

M017 changes only the base checkpoint first. The exact MLX-community
Qwen2.5-Coder-7B-Instruct 4-bit snapshot is pinned by revision, byte counts,
and SHA-256 in `benchmarks/training/m017_7b_baseline_v1.json`. It receives the
same six prompts and strict executable gate as the 1.5B model; no adapter or
sealed training example is loaded.

```bash
caffeinate -dimsu env PYTHONPATH=src \
  .venv-mlx/bin/python scripts/run_m017_7b_baseline.py \
  --run-id m017-qwen25-7b-base-v1
```

Do not start QLoRA until this run distinguishes base-model capacity from the
previous training recipe. A valid positive result requires an applicable diff
and passing registered tests, not merely plausible text.

The first 7B run exposed a conversion mismatch: `config.json` declared EOS
151643, while the tokenizer's `<|im_end|>` is 151645. Five useful-looking
repairs therefore included a literal `<|im_end|>` suffix and were correctly
rejected. M017 v2 explicitly registers tokenizer token 151645 as a generation
stop and reruns under a new immutable run ID; it does not strip model output
after generation.

Because the 7B responses contained correct repair intent but unreliable hunk
counts, the next controlled treatment changes only the action representation.
The model returns a complete corrected file; trusted code validates the
envelope, writes only the registered source path in a disposable workspace,
produces the Git diff, and runs the same tests. This matches LocalCode's
`edit_file` architecture without repairing model semantics.

```bash
caffeinate -dimsu env PYTHONPATH=src \
  .venv-mlx/bin/python scripts/run_m017_7b_edit_baseline.py \
  --run-id m017-qwen25-7b-edit-v1
```

Edit V1 solved `4/6`. Both failures contained the correct code but copied the
prompt's `File: path` label into Python source. V2 separates path metadata from
delimited file content and states that corrected-file tags contain Python only.
This is a prompt-boundary correction; the controller still performs no output
repair.

The source dataset is documented by the official
[`SWE-smith-py` dataset card](https://huggingface.co/datasets/SWE-bench/SWE-smith-py)
and [SWE-smith repository](https://github.com/SWE-bench/SWE-smith).

## Explain-back questions

1. Why must variants of one repair share a lineage split?
2. Why do we deny exact evaluation base revisions as well as issue IDs?
3. Why is a lower training loss not enough to promote an adapter?
4. Which split selects the checkpoint, and when may the sealed test be opened?
5. Why does the builder reject a record that names several forked repositories?
6. Why are commit-derived corrections weaker evidence than executable tests?
