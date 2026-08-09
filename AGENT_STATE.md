# LocalCode Agent Lab — State

Last updated: 2026-08-09 (Australia/Sydney)
Status: Milestone 005 offline gate passed; real-model smoke deferred by learner

This is the canonical chronological record. A command is not complete evidence
until its observed result is written here. Future assistants must read this file
before suggesting or executing the next step.

## Objective

Build and understand a local coding agent that can turn a repository issue into
a tested Git patch using a local open-weight model and tools implemented in this
repository.

## Fixed constraints

- Hardware: Apple M2 Max with 32 GiB unified memory; reverify before model work.
- Local inference only for the agent under study; no hosted inference API.
- Start from a capable pretrained coding model; do not train from scratch.
- Own the agent loop and tool protocol; do not wrap Claude Code, Codex, Aider,
  OpenHands, SWE-agent, or another complete agent.
- Use deterministic micro-repositories before real benchmark repositories.
- Benchmark configurations on an identical, pinned 20-instance manifest.
- Run untrusted repository code only in a disposable constrained environment.
- Keep gold patches, gold test patches, and post-fix repository state hidden
  from the agent.
- Preserve failed runs and their traces. Never overwrite a run directory.
- Implement and verify one milestone at a time.

## Current phase

Phase 3 — Build the local coding-agent runtime while preserving the model
compatibility evidence boundary.

## Current milestone

Milestone 005 — Protocol and one-turn controller. The fake-backend/offline gate
passes; the bounded Qwen3.5 smoke test remains pending a learner-approved clean
restart.

### Completed

- Registered exactly two Qwen coding instruct candidates, smallest first.
- Frozen one backend, sampling policy, two context probes, metrics, gates, stop
  rules, and sequential acquisition policy.
- Added 20 development prompts and exact schemas for the four implemented
  read-only tools.
- Added offline validation and unit coverage for the bake-off contract.
- Acquired only candidate 1 and independently verified its full manifest and
  all five referenced local blobs without inference.
- Built the loopback-only compatibility runner, deterministic scorer, immutable
  evidence layout, resource stop checks, and injected fake Ollama stream tests.

### Decisions

- Use the already installed Ollama 0.32.0 backend for both candidates so model
  size is the main changed variable.
- Candidate 1 is Qwen2.5-Coder-7B-Instruct Q4_K_M (published 4.7 GB).
- Candidate 2 is the conditional Qwen3-Coder-30B-A3B-Instruct Q4_K_M
  (published 19 GB); do not acquire it if candidate 1 passes every gate.
- The existing Qwen 1.5B base model remains unselected because it is not an
  instruction-tuned tool-use candidate.
- Published digest prefixes establish planning provenance only. Full local
  manifest/blob SHA-256 values must be recorded after an approved pull.

### Evidence

- `python3.11 scripts/check_model_bakeoff_contract.py` reports 2 candidates,
  20 prompts, 1 verified download, and candidate 2 still absent.
- The complete unit suite now runs 37 tests; all pass.
- JavaScript syntax, the 50-ID learning UI contract, Python compilation, and
  `git diff --check` passed.
- Candidate 1 is the only model downloaded. No package, data, image, benchmark
  repository, or candidate-2 artifact was added. Run v1 now provides one
  preserved inference result and an environmental stop.

## Milestone 001 — Read-only environment verification

Status: complete

### Question

Can this Mac support local model inference and controlled agent development,
and can it safely support the planned SWE-bench work without changing the
environment first?

### Prediction

- Apple Silicon and Python 3.11 would be suitable.
- MLX would probably exist only in a sibling lab environment.
- Docker would be installed, but its daemon resources and existing storage
  would determine benchmark feasibility.
- Existing Ollama artifacts might avoid an immediate model download, but they
  might not be appropriate instruct checkpoints.

### Capability matrix

| Capability | Observed result | Decision |
|---|---|---|
| Host architecture | `arm64`; MacBook Pro `Mac14,5`; Apple M2 Max; 12 CPU cores | Suitable for MLX/MPS; do not assume CUDA or x86 |
| Host memory | 32 GB unified memory | Suitable for bounded quantized local-model experiments |
| macOS | 27.0, build `26A5388g` | Record as provenance because it is a prerelease/new environment |
| Host disk | 926 GiB filesystem; 662 GiB used; 207 GiB available; 77% capacity | Enough for development and a cautious benchmark pilot; monitor before image builds |
| Default Python | `/opt/homebrew/bin/python3`, Python 3.14.6 | Do not use for the project environment |
| Project Python | `/Users/suleman/.pyenv/shims/python3.11`, Python 3.11.9 | Selected interpreter for the future isolated environment |
| Python 3.12 | No command available | Not required while supported 3.11 is available |
| Git | 2.50.1 | Available |
| ripgrep | 15.1.0 with PCRE2/JIT and ARM NEON | Available; use as the initial search engine |
| MLX | 0.32.0 in `chess-training-lab/.venv`; real Metal matrix result `54.0` outside the sandbox | Hardware/runtime compatibility proven; do not reuse the sibling environment as this project's environment |
| MLX-LM | Not installed in the inspected environments; no `mlx_lm` command | A future backend dependency decision, not a current blocker |
| PyTorch MPS | PyTorch 2.13.0 in `chess-training-lab/.venv-maia3`; MPS built and available; matrix result `54.0` outside the sandbox | Alternative backend capability proven; sibling environment remains isolated |
| Ollama | Client 0.32.0 at `/usr/local/bin/ollama`; no active loaded model | Installed local inference option; compatibility must still be measured |
| Existing Ollama model 1 | `qwen2.5-coder:1.5b-base`, 986 MB, Q4_K_M | Base rather than instruct model; retain only as a possible control, not an automatic agent choice |
| Existing Ollama model 2 | `deepseek-coder:6.7b`, 3.8 GB, Q4_0 | Existing alternative artifact; outside the preferred Qwen bake-off unless the plan is revised explicitly |
| Existing Ollama storage | Approximately 4.5 GB | No cleanup needed; no new download authorized |
| llama.cpp CLI/server | `llama-cli` and `llama-server` not found | Not currently available |
| Docker client/server | Docker 29.6.2; Docker Desktop 4.84.0; Linux `arm64` daemon | Working outside the agent sandbox |
| Docker allocation | 12 CPUs; 8,321,232,896 bytes memory (approximately 7.75 GiB) | Below the 16 GB SWE-bench recommendation; sufficient only for a cautious control/pilot until reconfigured and proven |
| Docker current use | 35 images/24.47 GB; containers/80 MB; volumes/3.67 GB; build cache/19.91 GB | Roughly 48 GB already represented; do not clean unrelated user assets and forecast every benchmark build |
| Local lab artifacts | 14 MB open-model adapters, 20 MB chess models, 112 MB chess checkpoints, 404 KB Hugging Face cache | No reusable modern coding instruct checkpoint found outside Ollama |

### Evidence and caveats

- The initial restricted checks could not access the Docker socket or local
  Ollama service. Read-only checks outside the sandbox confirmed Docker and
  listed the local Ollama inventory; this was an access-boundary result rather
  than a missing-service diagnosis.
- MLX initially reported no Metal device and PyTorch reported MPS unavailable
  inside the headless sandbox. The approved outside-sandbox probes completed
  real matrix multiplication through both MLX and PyTorch MPS and returned
  `54.0`. Hardware acceleration is therefore confirmed.
- `sysctl -n hw.memsize` was denied by the sandbox, while `system_profiler`
  independently reported 32 GB. No serial number or host identifier is retained
  in this state file.
- No dependency, model, dataset, repository, image, or package was downloaded.
  No Docker or Ollama asset was removed or modified.

### Decision

Proceed to Milestone 002 using Python 3.11.9. The machine is suitable for the
LocalCode runtime and later quantized local-model work.

Treat local SWE-bench as **pilot-feasible, not full-run proven**. Before the
20-instance experiment, Milestone 009 must verify a gold instance on ARM,
increase or otherwise justify Docker's 8.32 GB allocation, forecast image
storage against current Docker use, and preserve at least the registered host
disk safety margin. The official ARM and resource risks remain real even though
the host currently has 207 GiB available.

### Future actions requiring a deliberate decision

- Create a dedicated Python 3.11 environment and install project dependencies.
- Choose between MLX-LM and Ollama only after the registered backend needs are
  clear.
- Download an instruct coding checkpoint only during the bounded Milestone 004
  bake-off; do not treat the existing 1.5B base model as selected.
- Change Docker Desktop memory or build benchmark images only during the
  benchmark preparation milestone.

### Explain-back questions

1. Why does an MLX failure inside the sandbox not prove that the Mac lacks GPU
   support?
2. Why is the existing `qwen2.5-coder:1.5b-base` artifact not automatically the
   right agent model?
3. Why is 207 GiB of free host disk not enough by itself to declare the full
   SWE-bench experiment ready?

### Next allowed action

Execute only Milestone 002 from `docs/MILESTONES.md`: create the repository
contract and deterministic test skeleton. This handoff is now complete; see the
Milestone 002 record below.

## Milestone 002 — Repository contract and deterministic test skeleton

Status: complete

### Question

Can we establish a deterministic trusted runtime boundary, strict configuration
and event contracts, and an inert untrusted repository fixture before adding
any model or executable tool?

### Prediction

- Python 3.11's standard library would be sufficient.
- Configuration would reject missing, unknown, malformed, and escaping values.
- A frozen event would survive canonical JSON serialization exactly.
- Git could ignore local evidence and weight/data artifacts while retaining
  empty directory placeholders.
- No model, subprocess, network, repository tool, or controller module would be
  needed.

### Work completed

- Initialized an empty Git repository on branch `main`; no commit was created.
- Pinned the project interpreter contract to Python 3.11.9 in
  `.python-version`; `pyproject.toml` declares Python `>=3.11,<3.13` and zero
  dependencies.
- Added `docs/REPOSITORY_CONTRACT.md`, separating trusted runtime/tests/config
  from untrusted fixture repositories and ignored local artifacts.
- Added strict JSON configuration loading in `src/localcode/config.py` with
  schema versioning, exact-field checks, and repository-relative path checks.
- Added the immutable, versioned `Event` value in `src/localcode/events.py` with
  strict field validation, timezone-aware timestamps, canonical JSON, artifact
  references, and non-negative budget snapshots.
- Runtime immutability is enforced, not merely type-hinted: artifact and budget
  collections must be tuples, and the dataclass is frozen.
- Added `configs/runtime.json` and one deliberately failing untrusted fixture at
  `tests/fixtures/micro_repos/parser_none` for future tool-layer exercises.
- Added standard-library unit tests under `tests/unit`.
- Added ignored local directories for runs, weights, adapters, checkpoints, raw
  and processed data, evaluator output, and logs, with tracked `.gitkeep`
  placeholders where appropriate.

### Evidence

Command:

```bash
PYTHONPATH=src python3.11 -m unittest discover -s tests/unit -v
```

Observed result: 12 tests ran in 0.002 seconds; all passed; exit code 0.

The suite covers:

- repository configuration loading;
- unknown configuration keys;
- parent-path rejection;
- malformed JSON wrapping;
- exact event JSON round-trip;
- frozen dataclass behavior;
- rejection of mutable collections;
- negative-budget rejection;
- canonical JSON encoding;
- unknown event keys;
- fixture presence without fixture execution; and
- explicit absence of controller, workspace, tool, model, and TUI modules.

Focused round-trip evidence:

```text
{"artifact_refs":[],"budgets_remaining":{"steps":12},"event_type":"run_created","run_id":"gate-002","schema_version":1,"sequence":0,"state":"created","summary":"Round-trip gate","timestamp":"2026-08-08T10:00:00+10:00"}
roundtrip_equal True
```

Additional checks:

- `python3.11 -m compileall -q src tests/unit` passed with exit code 0.
- `git check-ignore -v --no-index` confirmed ignore coverage for example run
  JSONL, GGUF, PyTorch, Safetensors, raw/processed data, and evaluator results.
- Separate checks confirmed `runs/.gitkeep`, `models/.gitkeep`, and
  `data/raw/.gitkeep` are not ignored.
- Source inspection found only `__init__.py`, `config.py`, and `events.py` under
  `src/localcode`; no executable agent module exists.
- No dependency, model, data, image, or package was downloaded. The failing
  fixture test was deliberately not executed by this milestone's trusted unit
  suite.

### Decision

Milestone 002 passes. Proceed to the bounded read-only tool layer. Keep JSON as
the dependency-free configuration format for now; a YAML dependency would add
no learning value at this stage.

### Explain-back questions

1. Why is `tests/fixtures/micro_repos/parser_none` treated as untrusted data even
   though we authored it?
2. Why do the event collections need runtime tuple checks when Python already
   has type hints?
3. Why did this milestone avoid running the fixture's intentionally failing
   test?

### Next allowed action

Execute only Milestone 003 from `docs/MILESTONES.md`: implement the bounded
read-only tool layer. This handoff is now complete; see the Milestone 003 record
below.

## Milestone 003 — Bounded read-only repository tool layer

Status: complete

### Question

Can LocalCode inspect useful repository evidence without permitting path escape,
secret disclosure, symlink traversal, unbounded context output, file mutation,
test execution, or a general shell?

### Prediction

- All four tools could share one canonical repository policy.
- Valid fixture listing, reading, and search would succeed deterministically.
- Absolute paths, `..`, symlinks, secrets, binary files, and oversized files
  would fail safely or be excluded.
- Every observation would declare when a configured limit truncated it.
- Git diff could disable external helpers and filter secret paths before
  rendering content.

### Work completed

- Added immutable `ToolResult` values and typed `ToolError` failures.
- Added a canonical `RepositoryPolicy` that rejects absolute/traversing/NUL
  paths, all symlink components, VCS/dependency/runtime/model/generated-data
  directories, credential directories, and secret-like filenames.
- Added deterministic `list_files` with lexical ordering, depth pruning, and a
  hard 1,000-result ceiling.
- Added line-numbered UTF-8 `read_file` with 1 MiB input, 1,000-line, per-line,
  and total-output bounds. Binary and oversized files are rejected explicitly.
- Added literal/regex `search_code` with case and glob controls, plus limits of
  200 matches, 5,000 considered files, and 16 MiB scanned.
- Added staged/unstaged `git_diff` with a fixed no-shell argument vector,
  external diff/text conversion disabled, a 10-second timeout, streamed bounded
  output, exact Git-root alignment, and changed-path filtering through the
  repository policy.
- Added `docs/READ_ONLY_TOOLS.md` explaining tool semantics, error boundaries,
  truncation, secret handling, and the intentionally absent untracked-file diff.
- Tightened the previous event contract so budget names must be canonically
  sorted, preserving exact event round-trip for every accepted event.
- Kept the source free of editing, repository-test, network, model, controller,
  and TUI capabilities.

### First test result and diagnosis

The initial 25-test run produced 24 passes and one failure:

```text
FAIL: test_git_diff_reports_non_repository_as_typed_error
AssertionError: ToolError not raised
```

The test had created `not-a-repository/` *inside* an existing temporary Git
working tree. Git correctly treats nested directories as part of the parent
repository, so the fixture assumption was false. The response was twofold:

- require the declared repository root to equal `git rev-parse
  --show-toplevel`, preventing Git and path-policy roots from diverging; and
- test a truly unrelated temporary directory separately for `git_error`.

This failure changed no tool exposure and is retained as evidence that Git
repository membership is inherited by nested directories.

### Final evidence

Command:

```bash
PYTHONPATH=src python3.11 -m unittest discover -s tests/unit -v
```

Observed result: 28 tests ran in 0.273 seconds; all passed; exit code 0.

The new cases cover:

- valid sorted listing and explicit result truncation;
- real depth pruning;
- bounded line-numbered reading;
- absolute and parent traversal rejection;
- symlink escape rejection;
- `.env`, PEM, and `.git` exclusion;
- binary and 1 MiB-plus file rejection;
- literal, regex, glob, and case-insensitive search;
- invalid regex and secret-search behavior;
- search-result truncation;
- safe Git diff with tracked `.env` filtering;
- streamed Git diff truncation;
- Git top-level mismatch; and
- a genuine non-repository Git error.

Actual fixture proof:

```text
LIST
ISSUE.md
src/tiny_parser.py
tests/test_tiny_parser.py

SEARCH
src/tiny_parser.py:2:     return text.strip()

READ
     1 | def parse_value(text: str | None) -> str:
     2 |     return text.strip()
```

All three observations reported `truncated=False`. Compilation passed. A source
audit found no write/delete/network/test-execution functions in the tool
package. The lab's own `git_diff` returned zero bytes because this new Git
repository still has no tracked baseline commit; temporary committed fixtures
provide the meaningful diff tests.

No dependency, model, data, image, or package was downloaded. No fixture test
was executed and no file tool can modify the fixture.

### Decision

Milestone 003 passes. Keep the simple Python search scanner for the first tool
contract because its byte/file/result accounting is explicit and deterministic.
The verified `rg` executable remains available for a separately measured search
backend optimization during retrieval work; do not swap implementations without
rerunning the same security contract.

### Explain-back questions

1. Why can a read-only tool still be dangerous?
2. Why must `truncated=True` change how a future agent interprets an
   observation?
3. Why does `git_diff` first discover and filter filenames instead of rendering
   one repository-wide diff immediately?

### Next allowed action

Execute only Milestone 004 from `docs/MILESTONES.md`: register and run a bounded
local-model compatibility bake-off between no more than two Qwen coding instruct
checkpoints. Before downloading anything, define candidates, artifact/storage
costs, prompt pack, action-validity gate, context sizes, latency/memory metrics,
and stop rules. Do not implement an agent loop.

## Learning UI v1 — Interactive agent field manual

Status: complete; live localhost and structural verification passed, screenshot
review unavailable in the current session

### Question

Can the evidence-first teaching pattern from the first two sibling labs be
adapted into a dependency-free interactive course that explains LocalCode's
terminology, current implementation, future loop, safety boundaries, and
benchmark method without overstating what exists?

### Sibling patterns reviewed

- The Open Model Training Lab uses first-principles explanations, architecture
  comparisons, an experiment journey, failure cards, deep-note toggles,
  flashcards, quizzes, searchable terminology, resume state, and browser-local
  progress.
- The ChessLM lab sharpens that pattern with a persistent progress card,
  architecture and representation workbenches, controlled-evidence language,
  explicit implemented-versus-rejected paths, reusable failure diagnosis, and
  “what we actually built” explanations.

### Design decision

The LocalCode interface uses an **agent flight recorder** rather than copying
either sibling's visual treatment. Its signature is a live trace rail that
connects issue, action, observation, state, event JSON, budgets, and termination.
The palette uses blueprint blue, instrument cyan, warning amber, and error coral
on a cool technical-paper surface. Display, reading, and code roles use separate
local system type stacks, with no remote font or asset dependency.

### Work completed

- Added `learning/index.html`, `learning/styles.css`, and `learning/app.js` as a
  framework-free static interface.
- Added eight progress-tracked areas: anatomy, tool contracts, agent loop,
  verified milestones, benchmark science, failure laboratory, practice, and
  glossary.
- Added an anatomy workbench for issue, controller, context compiler, model,
  validator, registry, event store, and independent evaluator ownership.
- Added a simulated four-tool console with safe, traversal, secret, symlink, and
  truncation cases. The page explicitly states that it does not call Python or
  touch the filesystem.
- Added a step-through future run where every step renders a structured event
  and clearly labels Milestones 001–003 foundations versus planned editing,
  test, review, and completion capabilities.
- Added the actual Milestone 001–003 evidence and Milestone 004 next state.
- Added B0/A1/A2/A3 explanations, the `0/20 → 3/20 → 7/20 → 9/20`
  hypothesis, interactive fairness controls, and agent-versus-evaluator data
  separation.
- Added six real failure cards, ten explain-back cards, an eight-question quiz,
  and 36 searchable agent/repository/SWE-bench terms.
- Added browser-local completion, deep-note, resume, and best-quiz state under
  `localcode-learning-state-v1` while retaining `AGENT_STATE.md` as canonical
  engineering state.
- Added keyboard focus styling, a skip link, live regions, responsive layouts,
  and reduced-motion behavior.
- Added `scripts/serve_learning_lab.py` and `docs/LEARNING_UI.md`.
- Added a local SVG favicon so the field manual has no missing asset request.
- Clarified in `docs/MILESTONES.md` that this early HTML field manual does not
  replace Milestone 012's future live terminal UI equivalence gate.

### Evidence

Commands:

```bash
node --check learning/app.js
node tests/ui/rendered-html.test.mjs
PYTHONPATH=src python3.11 -m unittest discover -s tests/unit -v
python3.11 -m compileall -q src scripts tests/unit
```

Observed results:

- JavaScript syntax passed with exit code 0.
- The HTML contract reported `50 unique static IDs` and passed internal-anchor,
  remote-asset, accessibility-hook, responsive, reduced-motion, content-array,
  and milestone-evidence checks.
- All 28 Python runtime tests still passed; the learning UI changed no agent
  runtime semantics.
- Python compilation passed.
- The localhost server returned HTTP 200, `Content-type: text/html`, and the
  expected field-manual document; stylesheet and JavaScript requests also
  returned successfully. The final local SVG favicon parsed as valid XML.
- The current session exposed no in-app or connected browser instance, so a
  screenshot-based desktop/mobile review could not be performed. This is
  recorded as an uncompleted visual QA method, not disguised as a pass.

### Decision

Retain the static, zero-dependency format. It matches the current runtime
boundary, opens immediately on localhost, and lets the learner study without a
frontend build pipeline. Continue to Milestone 004 only after the learner has
used the field manual or explicitly chooses to proceed.

### Run command

```bash
python3.11 scripts/serve_learning_lab.py
```

Open `http://127.0.0.1:4173` and stop with `Ctrl-C`.

### Next allowed action

Milestone 004 remains unchanged: register the local-model compatibility bake-off
before installing a backend or downloading an instruct checkpoint.

## Milestone 004A — Bake-off registration

Status: complete; stopped before acquisition

### Question

Can the model choice be turned into a reproducible, resource-safe experiment
before storage cost or observed outputs bias the criteria?

### Prediction

- A 7B Q4_K_M instruct checkpoint would be the rational first candidate.
- A 30B-total sparse model might fit but would consume enough of 32 GiB unified
  memory to require strict context, working-set, and swap gates.
- Existing model artifacts and mutable remote tags would not be sufficient
  provenance for a scored run.

### Work completed

- Added `configs/model_candidates.json` with exact upstream revisions, Ollama
  tags/digest prefixes, artifact forecasts, sequential acquisition, fixed
  sampling, context probes, metrics, gates, and stop rules.
- Registered Qwen2.5-Coder-7B-Instruct Q4_K_M first and
  Qwen3-Coder-30B-A3B-Instruct Q4_K_M as conditional candidate 2.
- Added `benchmarks/model_compatibility/tool_schemas.json`, mirroring the four
  implemented read-only model-facing signatures without exposing repository
  root as an argument.
- Added a 20-item development prompt pack: 12 tool calls, 4 no-tool policy
  decisions, and 4 exact code-reasoning controls.
- Added an offline contract checker, documentation, and two unit tests.
- Updated the learning field manual with the registered candidates, current
  evidence, model-artifact terminology, and candidate-1 next action.
- Verified current candidate specifications and artifact forecasts against
  official Qwen model metadata and Ollama tag pages.

### Evidence

Commands:

```bash
python3.11 scripts/check_model_bakeoff_contract.py
PYTHONPATH=src python3.11 -m unittest discover -s tests/unit -v
python3.11 -m compileall -q src scripts tests/unit
git diff --check
```

Observed results:

- Contract check: `PASS model-compatibility-v1`, 2 candidates, 20 prompts,
  zero downloads, local artifact hashes pending.
- Unit suite: 30 tests ran in 0.276 seconds; all passed.
- JavaScript syntax and the learning UI contract passed with 50 unique static
  IDs; compilation and whitespace checks exited successfully.
- No package, model, dataset, image, or repository was downloaded and no local
  Ollama artifact was changed.

### Decision

Registration passes. Candidate 1 is the only next rational acquisition. The
19 GB candidate remains conditional because active parameter count does not
erase the memory cost of storing all quantized weights and KV/runtime state.

### Explain-back questions

1. Why do we score normalized tool calls instead of raw XML emitted by each
   model family?
2. Why must full local blob hashes remain pending until after the pull?
3. If candidate 1 passes every gate, why do we stop without downloading
   candidate 2?

### Next allowed action

With explicit approval, execute only Milestone 004B candidate-1 acquisition:
reverify free disk and Ollama version, pull
`qwen2.5-coder:7b-instruct-q4_K_M`, record the full manifest/blob hashes and
actual storage delta, then stop before inference. Do not acquire candidate 2,
run the prompt pack, or implement a controller in the same step.

## Milestone 004B — Candidate-1 acquisition

Status: complete; candidate 1 verified, not loaded or prompted

### Question

Can the first registered artifact be acquired without crossing the disk floor,
changing candidates, running inference, or losing exact artifact provenance?

### Evidence before acquisition

- The offline contract still reports 2 candidates, 20 prompts, 0 downloads, and
  pending local artifact hashes.
- The host reports 207 GiB free, above the registered 120 GiB floor.
- Ollama model storage before the pull is 4,701,104 KiB according to `du -sk`;
  use this as the acquisition-delta baseline.
- `/usr/local/bin/ollama` reports client version 0.32.0. Its service is not
  visible inside the restricted sandbox, matching Milestone 001's known access
  boundary; the pull must run in the learner's normal Terminal.
- Added `scripts/inspect_ollama_artifact.py` to calculate the full manifest hash
  and verify the size and SHA-256 of every referenced local blob without
  inference.
- Added three unit tests covering valid verification, corrupt blobs, and unsafe
  or unpinned model names.
- The full suite now runs 33 tests in 0.262 seconds; all passed. Compilation and
  `git diff --check` also passed.

### Acquisition evidence

- Learner command:
  `ollama pull qwen2.5-coder:7b-instruct-q4_K_M`.
- Ollama completed all five layers, verified its digest, wrote the manifest,
  and reported `success`.
- Full manifest SHA-256:
  `dae161e27b0e90dd1856c8bb3209201fd6736d8eb66298e75ed87571486f4364`.
- The independent verifier hashed all five referenced blobs; every size and
  SHA-256 matched the manifest. Total referenced blob bytes: 4,683,087,561.
- Ollama storage changed from 4,701,104 KiB to 9,274,436 KiB: an actual delta
  of 4,573,332 KiB (about 4.36 GiB including filesystem accounting).
- Host free disk after acquisition is 202 GiB, still 82 GiB above the
  registered 120 GiB floor.
- Final contract, learning UI, 33-unit-test, compilation, and whitespace checks
  all passed. No inference request was made.

### Decision

Milestone 004B passes. The downloaded bytes match the candidate registered in
004A. Candidate 2 remains absent and unjustified until candidate 1 is measured.

### Explain-back questions

1. Why is the tag `qwen2.5-coder:7b-instruct-q4_K_M` not sufficient evidence
   of the exact bytes we acquired?
2. What does verifying every manifest-referenced blob rule out?
3. Why have we still not learned whether this model is suitable for LocalCode?

### Next allowed action

Execute only Milestone 004C: implement a fake-server-tested, compatibility-only
Ollama runner and scorer, then run candidate 1 against the frozen cold-load,
4K/16K context, latency, memory, action-validity, and reasoning gates. Do not
execute repository tools, implement the agent loop, or acquire candidate 2.

## Milestone 004C — Candidate-1 compatibility measurement

Status: failed safely after one scored prompt; remaining gates unevaluated

### Question

Can the verified 7B candidate satisfy the frozen tool-action, reasoning,
context, latency, and resource gates on the actual M2 Max?

### Prediction

- The 7B Q4_K_M artifact should load comfortably below the 24 GiB model-size
  ceiling and complete both context probes without swap growth above 2 GiB.
- Tool-call syntax should be strong, while exact explicit argument matching is
  the most likely quality failure.
- The 16K probe should be slower to first output than 4K but remain above the
  registered 8 output-tokens/second floor.

### Work completed before inference

- Added `src/localcode/compatibility.py` with a loopback-only Ollama client,
  NDJSON streaming accumulation, official timing metrics, normalized tool-call
  handling, schema validation, and deterministic prompt scoring.
- Added `scripts/run_model_compatibility.py`. It refuses an existing run ID or
  a preloaded model, never executes tool proposals, snapshots all source and
  contract inputs, preserves raw request/stream evidence, and records 0 tools
  executed.
- The runner measures the first scored prompt as the cold load, all 20 frozen
  semantic prompts once, and three measured repetitions at calibrated 4,096
  and 16,384 input-token targets.
- It records Ollama `/api/ps` model allocation, host swap, and macOS free-memory
  percentage after requests; it stops on the registered memory, swap, pressure,
  or consecutive-failure boundaries.
- Added four tests using an injected byte-for-byte fake Ollama stream. Tests
  cover loopback restriction, request/NDJSON/tool/timing handling, schema
  rejection, and exact tool/policy/reasoning scoring.
- A literal loopback test server could not bind inside the restricted sandbox;
  the injected stream removed that environmental dependency while exercising
  the HTTP client contract deterministically.

### Evidence

- `PYTHONPATH=src python3.11 -m unittest discover -s tests/unit -v`: 37 tests
  ran in 0.259 seconds; all passed.
- Contract check: 2 candidates, 20 prompts, candidate 1 verified, candidate 2
  absent.
- JavaScript syntax, the 50-ID learning UI contract, Python compilation, and
  `git diff --check` passed.
- Before the real run, no Ollama chat request had been sent; that statement is
  superseded by the run-v1 evidence below.

### Run v1 evidence

- The learner unloaded the model and ran
  `python3.11 scripts/run_model_compatibility.py --run-id m004c-qwen25-7b-v1`.
- `tool-01` completed in 6.56 seconds. Ollama reported a 4.999-second model
  load, 483 prompt tokens at 439.94 tokens/second, and 25 output tokens at
  56.97 tokens/second.
- Ollama `/api/ps` reported 4,740,716,952 bytes for both model allocation and
  Metal/VRAM allocation, below the 24 GiB ceiling. Host free-memory percentage
  remained 29%, above the 5% critical-pressure floor.
- System swap was already 34,338,242,560 bytes before loading and rose to
  38,798,622,720 bytes: growth of 4,460,380,160 bytes (about 4.15 GiB), above
  the frozen 2 GiB stop rule.
- The runner stopped immediately after the first response, preserved 92 KiB of
  source snapshots, request, raw NDJSON, resource, score, and summary evidence,
  and exited 1. It executed zero tools.
- Therefore 19/20 semantic prompts, all four reasoning controls, and all 4K/16K
  context probes are **unevaluated**. The displayed `0/12`, `0/16`, and `0/4`
  in the immutable v1 summary are incomplete numerators against planned totals,
  not completed quality scores. Future summaries now report evaluated and
  planned counts separately.
- The one response was a near-miss: the model emitted parseable JSON text for
  `search_code`, but omitted the template-required `<tool_call>` wrapper, so
  Ollama returned no normalized `message.tool_calls`. Its arguments also used
  `path: "**/*.py"` rather than the expected repository path plus `glob` field.
  This remains a failed normalized call under the frozen scorer; it must not be
  silently rescued after observation.

### Decision after run v1

Do not score candidate 1 as 0/20 and do not acquire candidate 2. The primary
result is `ENVIRONMENT / swap_growth_limit` before a fair compatibility run.
The secondary tool-format near-miss warrants later backend/prompt diagnosis,
but only after the host resource baseline is understood.

### Unloaded-host diagnosis

- After explicitly stopping Qwen, `ollama ps` was empty, confirming that no
  Ollama model remained loaded.
- `memory_pressure -Q` reported 60% system-wide memory free, so the machine was
  not under active RAM pressure at observation time.
- `vm.swapusage` still reported 37,888 MiB total, 36,921.25 MiB used, and only
  966.75 MiB free. The large retained swap therefore was not the model's live
  Ollama allocation, but it leaves an unsuitable baseline for a comparable v2
  run.
- A clean macOS restart is required before another compatibility attempt. Save
  work first; do not treat the restart as a model or scorer change.

### Post-restart clean baseline

- On 2026-08-09 Australia/Sydney, before loading a model, `vm.swapusage`
  reported 0 MiB total and 0 MiB used.
- `memory_pressure -Q` reported 91% system-wide memory free.
- `ollama ps` was empty.
- This satisfies the clean-host prerequisite. The next immutable run ID is
  `m004c-qwen25-7b-v2`; v1 remains preserved and must not be overwritten.
- The first v2 command attempt stopped during local preflight before creating a
  run directory or contacting Ollama: the runner still required the obsolete
  `downloaded_verified_not_run` state. The preflight now accepts the registered
  incomplete-run state while explicitly rejecting previously registered run
  IDs. Therefore `m004c-qwen25-7b-v2` remains unused and valid.

### Next allowed action

Capture a clean unloaded-host swap/memory baseline, then run candidate 2 once
with registered run ID `m004c-qwen3-30b-v1` and explicit `--candidate 2`. Do not
change the frozen prompt pack, scorer, or gates.

### Candidate 2 acquisition evidence

- The learner pulled `qwen3-coder:30b-a3b-q4_K_M`; Ollama verified its digest,
  wrote the manifest, reported success, and exited 0.
- Independent hashing verified the manifest SHA-256 as
  `06c1097efce0431c2045fe7b2e5108366e43bee1b4603a7aded8f21689e90bca`
  and all four referenced blob hashes. Total referenced bytes are
  18,556,700,764.
- Ollama storage changed from the prior verified 9,274,436 KiB baseline to
  27,396,228 KiB: 18,121,792 KiB added. Host disk retains about 225 GiB free,
  105 GiB above the frozen floor.
- The official manifest has one explicit metadata anomaly: its config blob
  descriptor says 539 bytes while the authenticated blob is 542 bytes. The
  blob's SHA-256 matches exactly, and the other three sizes match. The verifier
  now reports hash integrity separately from descriptor-size conformance rather
  than hiding or prematurely aborting on this upstream inconsistency.
- The compatibility runner now requires explicit candidate selection for
  candidate 2 and records candidate order and ID in the immutable run state.

### Candidate 2 pre-run baseline

- In normal Terminal with candidate 2 unloaded, `vm.swapusage` reported 0 MiB
  total and 0 MiB used.
- `memory_pressure -Q` reported 73% system-wide memory free.
- `ollama ps` was empty.
- The registered immutable run ID is `m004c-qwen3-30b-v1`. The run must use
  explicit `--candidate 2`; all existing memory, swap, context, latency, and
  quality gates remain unchanged.

### Candidate 2 run result

- The learner ran candidate 2 once as `m004c-qwen3-30b-v1` from the approved
  zero-swap, 73%-free, unloaded baseline. The runner stopped after `tool-01`
  with exit 1 and preserved the incomplete run.
- Cold load completed. Model/Metal allocation reached 18,863,829,810 bytes
  (about 17.57 GiB), below the 24 GiB working-set ceiling, and host free memory
  remained 14%, above the 5% floor.
- Swap grew from zero to 2,720,991,805 bytes (about 2.53 GiB), above the frozen
  2 GiB limit. This is a candidate/hardware stability failure from a clean
  baseline, not a contaminated-host result. Do not rerun or relax the gate.
- Unlike candidate 1, candidate 2 returned one native normalized
  `search_code` call, so schema validity was 1/1 evaluated. The action was
  still incorrect under the frozen exact scorer because it omitted required
  `path: "."` and `glob: "*.py"` arguments and added default flags.
- The remaining 19 semantic prompts, reasoning controls, and both context
  probes are unevaluated. Candidate 2 has no completed quality score.
- Neither registered candidate passes: candidate 1 is stable but fails quality;
  candidate 2 shows native tool calling but fails the hardware swap gate.

### Next allowed action after candidate 2 stop

Explicitly unload candidate 2 and confirm `ollama ps` is empty. Then perform an
offline compatibility review before registering any new model, adapter, prompt,
scorer, or run. Preserve both failed candidates as controls.

### Post-run recovery and offline review

- Candidate 2 was explicitly stopped and `ollama ps` was empty. Host free
  memory recovered to 80%; macOS retained 2,375.81 MiB of the 4,096 MiB swap
  allocation after unloading.
- The strict content-adapter counterfactual read candidate 1 v2 evidence only;
  it made no inference request and left the immutable source run unchanged.
- Strict JSON normalization accepted all 12 tool-shaped content responses, but
  only 10/12 were schema-valid and total action decisions reached 6/16. Both
  remain below the frozen 11/12 and 14/16 gates; reasoning remains 3/4.
- Therefore a strict adapter alone is rejected. Semantic repair of arguments is
  also rejected because it would hide model errors inside controller code.
- Current official model research identifies `qwen3.5:9b-q4_K_M` (6.6 GB,
  native tools) as the leading extension candidate and `qwen3:8b` (5.2 GB,
  native tools) as fallback. Neither is registered or downloaded yet.

### Next allowed action after offline review

Freeze a separate compatibility-extension contract for one smaller native-tool
candidate while keeping the completed two-candidate plan immutable. Verify the
exact upstream revision and Ollama digest prefix before requesting a download.
Do not run another model while retained swap remains relevant to inference.

### Milestone 004D extension registration

- Added separate experiment `model-compatibility-extension-v1`; the completed
  two-candidate manifest remains unchanged as historical evidence.
- Registered official `qwen3.5:9b-q4_K_M`: 9.65B dense-hybrid parameters,
  Apache-2.0, 256K native context, published 6.6 GB Q4_K_M artifact, Ollama
  digest prefix `6488c96fa5fa`, and pinned upstream reference revision
  `cc5442c03a5c0bff0bd4c6888d9a40029c637733`.
- Frozen SHA-256 values for the 20-prompt pack, four tool schemas, system
  prompt, and deterministic scorer. Sampling, context probes, and every quality
  and resource gate exactly equal the parent experiment.
- Registered pre-download Ollama storage at 27,396,228 KiB and host free disk
  at 221 GiB. The planned immutable run ID is `m004d-qwen35-9b-v1`.
- The compatibility runner now selects `--experiment extension-v1` explicitly
  and snapshots that manifest. The unacquired status prevents inference.
- Extension contract, 43 unit tests, JavaScript/UI checks, compilation, and
  `git diff --check` pass. No download or inference occurred in registration.

### Next allowed action for Milestone 004D

Learner may pull exactly `qwen3.5:9b-q4_K_M`. Stop after download and verify the
full manifest, every blob hash, descriptor sizes, storage delta, and remaining
disk before any inference. Retained swap is irrelevant to downloading but a
clean baseline is still mandatory before the planned run.

### Milestone 004D acquisition evidence

- The learner pulled `qwen3.5:9b-q4_K_M`; Ollama verified the digest, wrote the
  manifest, reported success, and exited 0.
- Independent verification produced full manifest SHA-256
  `6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7`,
  matching the registered prefix. All four referenced blob hashes and all four
  descriptor sizes match.
- Total referenced bytes are 6,594,474,711. Ollama storage grew from
  27,396,228 KiB to 33,836,160 KiB: 6,439,932 KiB added.
- Host free disk remains about 216 GiB, 96 GiB above the frozen 120 GiB floor.
- Candidate status is `downloaded_verified_not_run`; no Qwen3.5 inference has
  occurred.

### Next allowed action after extension acquisition

Restart macOS to clear the 30B candidate's retained swap. Before opening
memory-heavy applications, capture `vm.swapusage`, `memory_pressure -Q`, and
`ollama ps`. Do not run Qwen3.5 until that baseline is reviewed.

### First extension baseline check

- `ollama ps` was empty and current host free memory was healthy at 80%.
- Swap still reported 3,072 MiB allocated and 2,221.88 MiB used. This closely
  matches the retained post-30B pressure state and is not an approved clean
  baseline.
- Do not run `m004d-qwen35-9b-v1` from this state. Restart without reopening
  prior windows, then capture the three measurements before launching other
  applications.

### Run v2 result

- All 20 semantic prompts and both context probes completed; exit 1 represents
  failed quality gates, not a crash.
- Candidate 1 passed cold load, both 4K/16K context completion, speed, first
  output latency, working-set, host-pressure, swap, and reasoning gates.
- It used zero swap, never dropped below 74% free host memory, and peaked at
  5,636,211,342 bytes (about 5.25 GiB) model/Metal allocation.
- Median generation was 36.95 tokens/second at 4K and 29.58 tokens/second at
  16K. Median first output was 0.159 and 0.176 seconds respectively.
- It failed normalized tool calls at 0/12 (required 11/12) and correct action
  decisions at 1/16 (required 14/16). It passed code reasoning at 3/4.
- Every tool prompt produced JSON-looking text in `message.content` rather than
  Ollama `message.tool_calls`. Several proposed arguments were also semantically
  wrong, so this is not merely a scorer presentation issue.
- The frozen candidate-2 condition is now met: candidate 1 failed quality while
  passing stability, memory, and latency. Candidate 2 remains unacquired until
  the learner explicitly runs the registered download.

## Milestone 005 — Protocol and one-turn controller

Status: offline gate passed; real-model smoke deferred.

### Question

Can untrusted model text cross a strict protocol boundary and cause at most one
bounded read-only repository action, with every outcome recorded
deterministically?

### Implemented offline

- Added protocol version `1`: exactly `protocol_version`, `thought_summary`,
  and one `action` containing exactly `tool` and `arguments`.
- Added a strict action validator that rejects invalid JSON, unknown fields,
  unsupported versions, unknown tools, and schema-invalid arguments. It applies
  only declared schema defaults and harmless path canonicalization; it does not
  repair semantic model mistakes.
- Added an exact registry for `list_files`, `search_code`, `read_file`, and
  `git_diff`. Repository path and secret policy remains inside the tools as an
  independent execution boundary.
- Added a one-turn controller that calls a backend once and executes at most one
  tool. Rejected actions and tool-policy failures become bounded `ToolResult`
  observations rather than exceptions escaping the run.
- Added immutable event types for accepted/rejected actions and successful or
  failed tool observations.

### Evidence

- `PYTHONPATH=src python3.11 -m unittest discover -s tests/unit -v` passes all
  55 tests.
- The learner independently ran that exact command in normal Terminal on
  2026-08-09; it reported `Ran 53 tests in 0.303s` and `OK`.
- Before the full suite, the learner reproduced all four deterministic demo
  cases: valid search, invalid JSON, unknown tool, and path escape. The observed
  event sequences and typed observation codes matched the registered lesson.
- A fake backend successfully searches the `parser_none` micro repository.
- Invalid JSON and an unknown `terminal` tool produce `action_rejected`
  observations and execute no repository tool.
- A `read_file` traversal request passes schema validation but is independently
  rejected by repository policy as a `path_escape` tool observation.
- Two controllers given identical fake responses, issue, run ID, and injected
  timestamp produce identical canonical event JSON and identical observations.
- Model responses above 16,384 characters are rejected as
  `payload_too_large` before JSON parsing.
- Duplicate JSON fields at any nesting depth are rejected as `duplicate_field`
  instead of silently keeping the last value.
- No Ollama request, model load, download, test execution inside an untrusted
  repository, or edit capability occurred in this offline work.

### Deferred gate

The Milestone 005 real-model smoke test is not complete. The learner chose not
to restart macOS while about 2.21 GiB of retained swap remained. This is a
valid pause: continue using fake backends, but do not run Qwen3.5 or claim model
integration until a clean unloaded baseline is captured later.

### Next allowed action

Study and manually inspect the one-turn protocol implementation, or perform
additional fake-backend protocol exercises. Do not begin the multi-turn loop,
editing, or test execution until the bounded real-model smoke closes Milestone
005.

## Public repository and learning site

Status: repository and static learning UI publicly verified.

- GitHub repository: `https://github.com/msulemans/local-code-agent-lab`
- GitHub Pages: `https://msulemans.github.io/local-code-agent-lab/`
- The repository was created public under the authenticated `msulemans`
  account. Local `main` and `origin/main` matched before Pages work.
- Every commit uses `msulemans <53903082+msulemans@users.noreply.github.com>`;
  the company Git identity remains global but is overridden locally.
- Pages publishes only `learning/` through `.github/workflows/pages.yml`.
  Official actions are pinned to immutable commit SHAs.
- The first workflow run, `31305813210`, failed before upload because Pages had
  not yet been enabled; `configure-pages` received HTTP 404. Pages was then
  explicitly enabled with `build_type=workflow` and HTTPS enforcement.
- The unchanged manual run `31306104742` passed validation, configuration,
  upload, and deployment in 17 seconds.
- An independent fetch returned HTTP/2 200, `content-type: text/html`, 15,773
  bytes, and the expected `LocalCode Field Manual` title.
- Model artifacts, checkpoints, compatibility run evidence, and generated data
  remain ignored and were not published by Pages.

## Decision log

| ID | Decision | Reason | Status |
|---|---|---|---|
| D-001 | Build our own controller and tools | The learning goal is agent engineering, not product wrapping | fixed |
| D-002 | Keep model backend replaceable | Compare models without rewriting agent behavior | fixed |
| D-003 | Micro tasks precede SWE-bench | Debug our loop separately from third-party environments | fixed |
| D-004 | Use a frozen 20-task manifest | Prevent subset shopping between configurations | fixed |
| D-005 | TUI consumes events | Presentation cannot alter agent semantics | fixed |
| D-006 | Review is a controlled final treatment | Measures its marginal effect | fixed |
| D-007 | Use standard-library JSON configuration initially | Keeps schema behavior deterministic without installing a parser | fixed |
| D-008 | Treat fixture repositories as untrusted data | Future tools must enforce policy regardless of repository authorship | fixed |
| D-009 | Start with a deterministic Python search scanner | Makes byte, file, result, secret, and truncation accounting explicit before retrieval optimization | fixed for initial tool contract |
| D-010 | Require policy root to equal Git top level | Prevents Git from observing a wider tree than repository policy | fixed |
| D-011 | Use a static dependency-free learning field manual | Keeps teaching available before any frontend or model dependency exists | fixed for learning UI v1 |
| D-012 | Keep learning progress separate from engineering state | Browser completion is personal study state; `AGENT_STATE.md` remains evidence | fixed |
| D-013 | Use Ollama for the two-candidate compatibility gate | It is already installed and gives both candidates one normalized local tool-call interface | fixed for Milestone 004 |
| D-014 | Acquire candidates sequentially, smallest first | Avoid a conditional 19 GB download when the 4.7 GB candidate already meets the frozen gate | fixed for Milestone 004 |
| D-015 | Treat invalid model actions as observations | A future bounded loop needs safe feedback without executing guessed intent | fixed |
| D-016 | Defer Qwen3.5 inference while retained swap remains | Preserves the registered clean-baseline evidence boundary at the learner's request | pending clean restart |
| D-017 | Publish only `learning/` to GitHub Pages | The browser curriculum is static; repository tools, models, and local evidence must remain outside the web artifact | fixed |

## Run ledger

| Run ID | Model and artifact | Result | Evidence |
|---|---|---|---|
| `m004c-qwen25-7b-v1` | Qwen2.5-Coder-7B-Instruct Q4_K_M; manifest `dae161e27b0e90dd1856c8bb3209201fd6736d8eb66298e75ed87571486f4364` | stopped after 1/20; `swap_growth_limit`; exit 1; no compatibility score; 0 tools executed | immutable run directory; prompt/config/source hashes; raw request/stream; 4.15 GiB swap growth; 4.42 GiB allocation; tool-format near-miss |
| `m004c-qwen25-7b-v2` | Qwen2.5-Coder-7B-Instruct Q4_K_M; manifest `dae161e27b0e90dd1856c8bb3209201fd6736d8eb66298e75ed87571486f4364` | complete; failed quality; tool schema 0/12, decisions 1/16, reasoning 3/4; exit 1; 0 tools executed | immutable 836 KiB run; all 20 prompts and 4K/16K probes; zero swap; 5.25 GiB peak allocation; 74% minimum free memory |
| `m004c-qwen3-30b-v1` | Qwen3-Coder-30B-A3B-Instruct Q4_K_M; manifest `06c1097efce0431c2045fe7b2e5108366e43bee1b4603a7aded8f21689e90bca` | stopped after 1/20; `swap_growth_limit`; schema 1/1 evaluated; decision 0/1 evaluated; exit 1; 0 tools executed | immutable run directory; clean zero-swap baseline; 2.53 GiB swap growth; 17.57 GiB allocation; 14% minimum free memory |

Future entries must record: run ID, Git SHA, model ID and artifact hash,
quantization, prompt version, configuration, task manifest hash, budgets, seed,
start/end time, result, patch hash, test evidence, and failure category.
