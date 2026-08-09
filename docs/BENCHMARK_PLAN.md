# Benchmark plan

## Evaluation ladder

Use three layers so failures have a clear owner:

1. **Unit and protocol tests** — tools, validation, policies, and state machine.
2. **Micro-repository suite** — 8–12 tiny issues whose intended behavior we own.
3. **Real issues** — one harness control, a 3-task pilot, then the frozen 20.

Never use real benchmark failures to debug basic JSON parsing or path handling.

## Dataset choice

Prefer a pinned subset of SWE-bench Verified because each issue was reviewed for
solvability. SWE-bench Lite remains an alternative if its repository mix and
local image support are materially easier. Record exact dataset repository,
revision, split, and row hashes; names and advertised counts are insufficient.

The official harness evaluates a JSONL prediction with:

```json
{
  "instance_id": "owner__repo-issue",
  "model_name_or_path": "localcode/config-name",
  "model_patch": "diff --git ..."
}
```

It applies the patch and runs tests inside a container. Our agent must not use
the official gold patch, `test_patch`, post-fix commit, or evaluator logs from a
prior run as context.

## Selecting the 20

Selection happens once, before any scored agent run.

Registered selection algorithm:

1. Start from the pinned dataset rows compatible with the proven local harness.
2. Restrict Version 1 to Python repositories and exclude tasks whose containers
   cannot pass the gold control on this host.
3. Group by repository and coarse issue properties available without gold:
   issue length, failing-test hints, and repository size.
4. Select with a fixed public seed, cap any one repository at five tasks, and
   save all IDs plus selection metadata.
5. Hash the ordered manifest and never replace a hard task after seeing agent
   behavior.

Environment-incompatible exclusions must happen before scoring and be listed.
Do not call a task incompatible merely because our agent failed it.

## Frozen configurations

| ID | Configuration | What changes |
|---|---|---|
| B0 | single-shot base model | issue + bounded repository map; one patch response; no tools/retry |
| A1 | simple agent | typed tools, basic recent-history context, edit/test/retry loop |
| A2 | retrieval agent | A1 plus deliberate ranked repository context selection |
| A3 | agent + review | A2 plus fresh review and at most one bounded revision |

Your original expectations are recorded as hypotheses:

```text
B0: 0/20   A1: 3/20   A2: 7/20   A3: 9/20
```

They are neither gates nor promised outcomes. We do not change tasks or rules to
make the curve look right.

## Fairness controls

Freeze across configurations:

- exact model checkpoint, quantization, inference backend, sampling policy, and
  seed where deterministic sampling is supported;
- issue text and starting repository commit;
- total generated-token allowance;
- total tool-result/context allowance;
- wall-clock and test-command timeouts;
- maximum patch bytes and files changed;
- network and command policy; and
- independent evaluator and container resources.

Review consumes budget. Compare both equal-total-budget results and a clearly
labeled operational result where review receives extra compute; never mix them.

## Primary and secondary metrics

Primary:

- resolved instances out of 20 under the official evaluator.

Secondary:

- attempted and valid patches;
- targeted and full test execution rates;
- solved transitions between adjacent configurations;
- regressions: previously solved, now failed;
- model tokens, tool calls, test runs, wall time, and peak memory;
- relevant-file recall on development tasks;
- invalid-action and repeated-action rates; and
- failure category per instance.

With only 20 tasks, do not overinterpret percentages. Report raw counts and the
per-instance paired table.

## Failure taxonomy

Assign one primary reason only after reading the trace:

```text
ENVIRONMENT        image/dependency/evaluator failed before a fair attempt
LOCALIZATION       never found the relevant implementation/tests
COMPREHENSION      saw evidence but formed the wrong hypothesis
EDIT_INVALID       patch parse/apply/syntax failure
FIX_INCOMPLETE     improved behavior but missed required cases
REGRESSION         target fixed but other tests broke
VERIFICATION       failed to run or interpret appropriate tests
LOOP_CONTROL       repeated, exhausted budget, or stopped incorrectly
REVIEW_HARM        reviewer damaged an otherwise resolving patch
UNKNOWN            evidence is insufficient; do not guess
```

## Promotion rules

- A1 is still valuable if it solves zero real issues but passes the deterministic
  loop and safety gates. Do not confuse product correctness with benchmark power.
- Promote A2 as the default only if its registered retrieval metric improves and
  it does not reduce resolved tasks under the equal budget.
- Promote A3 only if net resolved tasks improve without an unacceptable compute
  increase; always show review harms.
- Never open a different 20-task subset to choose the winning configuration.

## Platform risk

Official guidance recommends at least roughly 120 GB free storage, x86_64, and
substantial CPU/RAM for SWE-bench; Apple ARM support is described as
experimental. On this M2 Max, Milestones 001 and 009 must prove disk capacity,
Docker architecture behavior, and one gold instance before promising a local
20-task run. If the official harness cannot run faithfully, preserve agent
patches and move evaluation to a clearly separated compatible machine later;
do not invent a weaker test and label it SWE-bench resolved.
