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

Milestone 015 will select and baseline a pretrained coding model. Before full
training, one tiny batch must tokenize, run forward and backward, and save a
loadable adapter on this Mac. The sealed test stays unopened until one adapter
is selected on validation.

## Explain-back questions

1. Why must variants of one repair share a lineage split?
2. Why do we deny exact evaluation base revisions as well as issue IDs?
3. Why is a lower training loss not enough to promote an adapter?
4. Which split selects the checkpoint, and when may the sealed test be opened?
5. Why does the builder reject a record that names several forked repositories?
6. Why are commit-derived corrections weaker evidence than executable tests?
