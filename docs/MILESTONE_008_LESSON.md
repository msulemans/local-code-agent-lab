# Milestone 008 lesson — deterministic retrieval treatment

## Outcome

Milestone 008 has started with the first trusted retrieval primitive:

```text
issue
  -> repository map
  -> source/test ranking
  -> bounded excerpts
  -> loop context
```

This does not change the model, tools, edit policy, or benchmark task set. It
only changes how trusted Python can choose evidence before the model sees a
context pack.

## Mental model

Naive agents ask the model what to search for on every turn. Retrieval adds a
trusted evidence picker before the model acts:

- map the allowed repository files;
- classify source, tests, issues, and other files;
- extract simple symbols such as Python functions/classes;
- score files against issue terms, paths, symbols, and content;
- return bounded line-numbered excerpts; and
- measure whether expected relevant files appeared under a fixed budget.

Retrieval chooses evidence. It must not silently solve the issue, generate a
patch, or inspect gold/evaluator-only material.

## Implemented slice

`src/localcode/retrieval.py` now provides:

- `build_repository_map(root)` — deterministic allowed-file map with kind,
  language, size, line count, and symbols;
- `select_retrieval_evidence(root, issue, max_files, max_total_chars)` —
  ranked bounded excerpts from source/test/other files, excluding `ISSUE.md`;
- `evaluate_relevant_file_recall(pack, expected_paths)` — a development metric
  for whether expected changed files were selected.

`src/localcode/context.py` now provides:

- `SimpleContextCompiler` — preserves the historical issue/history/budget JSON
  envelope;
- `RetrievalContextCompiler` — adds bounded `retrieved_evidence` only when this
  explicit treatment is configured; and
- `ContextRequest` — the stable input shape used by the loop.

The first metric is intentionally small and honest: relevant changed-file recall
under a 3-file budget on the registered 8-case micro suite.

## Run one retrieval pack

From the repository root:

```bash
PYTHONPATH=src python3.11 scripts/demo_retrieval_pack.py --case parser-none
```

Expected evidence:

```text
CASE parser-none
EXPECTED src/tiny_parser.py
RECALL 1/1
SELECTED
- tests/test_tiny_parser.py ...
- src/tiny_parser.py ...
```

The test file may rank above the implementation if it contains more exact issue
terms. That is acceptable: the metric checks whether the implementation is
present under budget, not whether every case orders files the same way.

For the multi-file case:

```bash
PYTHONPATH=src python3.11 scripts/demo_retrieval_pack.py \
  --case username-consistency \
  --max-files 3
```

Expected evidence:

```text
RECALL 2/2
```

## Run the retrieval tests

```bash
PYTHONPATH=src python3.11 -m unittest tests.unit.test_retrieval -v
```

Current result:

```text
Ran 4 tests
OK
```

The suite-level retrieval test reports 9 expected changed paths across the 8
registered micro cases and recalls all 9 under a fixed 3-file budget.

## Run the loop-ready retrieval context

```bash
PYTHONPATH=src python3.11 scripts/demo_retrieval_context.py \
  --case parser-none \
  --max-files 2 \
  --max-context-chars 4000
```

Expected evidence:

```text
CASE parser-none
CONTEXT_CHARS 1947
SELECTED tests/test_tiny_parser.py, src/tiny_parser.py
```

This is the context shape the model can receive in a retrieval treatment. It
contains selected evidence and retrieval metadata; it does not contain
`expected_changed_paths`, gold patches, or evaluator-only tests.

After the retrieval-context slice, the current Codex-sandbox full unit run
contains 143 tests with `OK (skipped=5)`. The skipped cases are the known nested
macOS sandbox canaries; the learner's normal Terminal run before this retrieval
slice executed the canaries with zero skips.

## What this proves

It proves that LocalCode can build a deterministic evidence pack and a concrete
retrieval development metric without model inference.

It does not prove that Qwen will use the pack correctly, that retrieval improves
solve rate, or that SWE-bench is ready.

## Read the implementation in this order

1. `src/localcode/retrieval.py` — map, ranking, excerpts, recall metric.
2. `src/localcode/context.py` — default and retrieval context compilers.
3. `tests/unit/test_context.py` — simple-context preservation and
   retrieval-context loop integration.
4. `tests/unit/test_retrieval.py` — deterministic map, policy, bounds, and
   micro-suite recall.
5. `scripts/demo_retrieval_pack.py` — inspect one retrieval pack by case ID.
6. `scripts/demo_retrieval_context.py` — inspect the loop-ready context.
7. `benchmarks/micro_agent/suite_v1.json` — expected changed paths used only
   for development metrics, not model context.

## Explain-back check

1. Why should retrieval exclude `ISSUE.md` from selected evidence?
2. Why is relevant-file recall a development metric rather than a solve score?
3. Why can a test file legitimately rank above the implementation?
4. Why must retrieval avoid gold patches and evaluator-only tests?
5. What would make this first retrieval slice insufficient for larger repos?
