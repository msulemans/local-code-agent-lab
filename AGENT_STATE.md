# LocalCode Agent Lab — State

Last updated: 2026-08-16 (Australia/Sydney)
Status: The offline runtime, micro ladder, and real harness controls are proven. Real Qwen/DeepSeek pilots (m010–m021) connected the loop to Ollama but produced 0/20 patches; the root cause is now diagnosed and the first half is fixed (content-form JSON tool calls were misread as final answers, translated in the loop backend with new tests), while a strict-argument-schema barrier and a fresh real-model pilot remain

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

Real-model patch producer bridge (Milestone 009 continuation). The loop now
translates content-form JSON tool calls; the next allowed action is a fresh
non-gold pilot after the remaining strict-argument-schema barrier is decided.

### Pilot era summary (m010–m021)

- Real models were connected to the harness on the single pilot instance
  `pallets__flask-5014`; the other 19 manifest instances were skipped by the
  producer scope. Every pilot reported `0/20` resolved with empty patches.
- `qwen3.5:9b-q4_K_M` (m010–m017, m019) executed 3–5 real tool calls then
  terminated with `invalid_action_exhaustion`.
- `qwen2.5-coder:7b-instruct-q4_K_M` (m018) terminated with
  `invalid_action_exhaustion` without executing a tool.
- `deepseek-coder:6.7b` (m021) terminated with `backend_error` in ~2 s with no
  tool calls (Ollama transport/model availability), and m020 was a
  post-restart rerun. None of these runs are yet recorded in the run ledger
  below; they are preserved immutably in `runs/real-benchmark/m01*-*`.

### Diagnosis (confirmed deterministically)

- Preserved m004c streams show the models emit tool calls as plain JSON text in
  `content` (e.g. `{"name": "git_diff", "arguments": {...}}`) instead of a
  native Ollama `tool_calls` entry.
- The loop backend wrapped that short content as a `final` decision; the loop
  (with `require_patch=True`) rejected each premature final, and after
  `max_invalid_actions=4` terminated with `invalid_action_exhaustion`.
- `scripts/verify_pilot_failure.py` reproduces this exact path and now shows
  the translation fix in action plus the remaining strict-schema rejection.

### Implemented fix (this session)

- Added `content_form_tool_call()` in `src/localcode/backends/ollama.py` and
  wired it into both `_protocol_payload` and `_loop_protocol_payload`. A
  content payload that is exactly one `{"name", "arguments"}` JSON object is
  translated into the tool decision envelope; anything else is untouched, so
  narration is never repaired into a tool call.
  - The strict action validator still enforces tool name and argument schema
    after translation; translation cannot weaken validation.
- Added four unit tests in `tests/unit/test_ollama_loop_backend.py` covering
  the translation, strict-schema enforcement after translation, no-repair for
  non-tool JSON, and a full content-form patch→test→final loop. Suite: 174
  tests, all pass.

### Remaining barrier (decision needed)

Even after translation, the model's exact emissions often fail the strict
argument schema (e.g. `path: null` where a string is required, `max_results: 0`
below its minimum). The m004c tool-schema score of 0/12 reflects this. The next
decision is whether to (a) prompt/format the model to emit schema-valid
arguments, (b) relax or normalize specific schema defaults without weakening
safety, or (c) record strict-schema failures as model evidence and try another
candidate. This must be a deliberate decision before a fresh pilot.

### Option (a) implemented 2026-08-16

Decision D-026: a shared `SCHEMA_VALIDITY_RULES` block is now embedded in both
`ONE_TURN_SYSTEM_PROMPT` and `LOOP_SYSTEM_PROMPT`. It states the exact rules the
validator enforces: no `null` on string/integer/boolean fields (only `glob`
and `end_line` may be null), no zero below the schema minimums, exact types,
required fields per tool (`query`, `path`, `patch`, `command_name` =
`python-unittest`), omit unneeded optionals, and a final-answer fallback when a
schema-valid call cannot be formed. Two guard tests assert the rules remain in
each prompt. Suite: 176 tests pass. The next allowed action is a fresh non-gold
pilot; if strict-schema failures persist after the tightened prompt, evaluate
option (b) or (c) as the recorded alternative.

### Smoke proof and progress output 2026-08-16

- One-turn smoke `smoke-qwen35-schema-v1` passed: the real `qwen3.5:9b-q4_K_M`
  produced a schema-valid `search_code` call that was accepted and executed
  (baseline: 0 swap, 68% free, no loaded models). This is the first real-model
  validated tool call through the runtime.
- The first re-run (`m022-pilot-schema-v1`) was Ctrl-C'd during the silent
  flask agent loop, so the runner now accepts a per-instance
  `progress_observer` (CLI prints `PROGRESS <config> <instance> status=...`
  by default, disable with `--no-progress`) and a new run ID must be used for
  the next pilot. One new test; suite: 177 tests pass.

### m023 trace diagnosis and context-budget fix 2026-08-16

`m023-pilot-schema-v1` completed with the trace enabled. The model made five
valid native tool calls (list_files, read_file, run_tests, git_diff) and one
schema-rejected apply_patch (max_bytes 1048576 over the 65536 maximum), then
hit `invalid_action_exhaustion`. The preserved trace shows the decisive
failure: on the apply_patch turn the model's context was `"history":[]`,
`"truncated":true` — the 16,000-char budget was too small to hold the Flask
file listing plus the read_file content, so `_compile_payload` popped the
entire history. The model explicitly said it could not see repository files and
hallucinated diffs (wrong paths, fake index hashes, Blender file paths), then
regressed to bash-style code blocks. Decision D-027 raises the producer
context budget (32,768 tokens / 32,000 chars, tunable) and forbids
shell/bash/code-block output in the loop prompt. Suite: 177 tests pass.

Lesson: a model cannot patch what it cannot see; when a trace shows the model
claiming it lacks file context, check the compiled context envelope before
blaming model quality.

### m024 diagnosis 2026-08-16

`m024-pilot-context-v1` proved the D-027 context fix (history is present in
every turn) and that the loop mechanics are now working end-to-end with a real
model: native tool calls translate, the strict validator rejects bad arguments,
repeated-action detection fires, and controller guidance is emitted. The
residual failure is model discipline on `qwen3.5:9b`: it emits
`"max_results": "30"` (quoted string) so `search_code` is rejected as
`invalid_arguments`, and it repeats the same call with a 0-match regex instead
of following the controller's read_file guidance. D-028 adds an explicit
integer-example rule; the recorded next step is the stronger
`qwen3-coder:30b-a3b` candidate (already installed) with the resource guard
watching memory, since the 9B model appears to be at its tool-calling
capability ceiling.

### Completed (earlier)

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

Status: offline gate and guarded smoke command passed; real-model run deferred.

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
- Added a loopback-only Ollama backend adapter with deterministic sampling,
  bounded context/output, hidden-thinking exclusion, exact native-call
  translation, and `keep_alive=0` for the future smoke path.
- The adapter preserves proposed tool names and arguments exactly. Unknown,
  malformed, or multiple calls are not repaired into executable actions.
- Added a pure smoke preflight that requires zero used swap and an empty Ollama
  process list before inference is reachable. It also captures a parseable
  host free-memory percentage as baseline evidence.
- Added `scripts/smoke_one_turn_ollama.py`, fixed to the registered Qwen3.5 9B
  model, one fixture issue, one backend request, and one controller turn. The
  command exists but has not been run against Ollama.
- Added a smoke evidence recorder that reserves a unique ignored run directory,
  rejects unsafe or reused run IDs, enforces valid state transitions, validates
  event identity/sequence, and atomically records baseline plus outcome.
- Added command-level fake tests for blocked preflight, backend failure after an
  accepted baseline, rejected model action, successful tool result, and
  duplicate-run refusal before the smoke runner is invoked.

### Evidence

- `PYTHONPATH=src python3.11 -m unittest discover -s tests/unit -v` passes all
  82 tests in the current worktree.
- The learner independently ran the final 69-test suite in normal Terminal on
  2026-08-10 after separately reproducing the five focused preflight tests and
  three focused smoke-orchestration tests; every command reported `OK`.
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
- A fake Ollama-shaped native call crosses the complete offline path—backend,
  protocol validator, registry, and real fixture search—and produces the
  expected accepted/result event sequence with exactly one backend request.
- Retained swap and a non-empty Ollama process list each stop the smoke
  orchestrator before `stream_chat`; both tests assert zero captured payloads.
- A zero-swap, unloaded fake baseline permits exactly one backend request and
  produces the expected accepted/result event sequence.
- The smoke CLI records every fake outcome in a unique `run.json`. A backend
  failure retains the already accepted baseline, and an existing run directory
  stops before the injected smoke runner receives a call.
- No Ollama request, model load, download, test execution inside an untrusted
  repository, or edit capability occurred in this offline work.

### Deferred gate

The Milestone 005 real-model run is not complete. The learner chose not
to restart macOS while about 2.21 GiB of retained swap remained. This is a
valid pause: continue using fake backends, but do not run Qwen3.5 or claim model
integration until a clean unloaded baseline is captured later.

### Sequencing update

The earlier rule blocked all Milestone 006 engineering behind the deferred
real-model run. On 2026-08-10 the learner explicitly prioritized faster actual
engineering while retaining the no-restart decision. Offline fake-backend
development may therefore advance independently; this does not authorize
Qwen3.5 inference or count as model-integration evidence.

## Milestone 006 — Bounded read-only agent loop

Status: offline gate passed; local-model integration remains deferred.

### Implemented

- Added a separate versioned loop-decision protocol with exactly two kinds:
  one validated read-only tool proposal or one bounded final answer.
- Reused `ActionValidator` for tool decisions, preserving all schema, default,
  unknown-field, duplicate-key, and no-semantic-repair guarantees.
- Added `ReadOnlyAgentLoop` using a finite `range(max_turns)`, with budgets for
  turns, invalid actions, tool calls, identical actions, wall time, and context.
- Added deterministic JSON context construction that marks truncation, drops
  oldest history first, and labels issue/history as untrusted data.
- Added canonical repeated-action signatures and blocked a repeated action
  before a second execution when the configured allowance is one.
- Added explicit final-answer, invalid-action exhaustion, tool exhaustion,
  repeated-action, backend-error, wall-clock-timeout, and turn-exhaustion
  results with immutable events and remaining-budget snapshots.
- Added an offline three-turn demonstration: search, read, then final answer.

### Evidence

- The 12 focused decision/loop tests pass.
- The complete offline suite passes 94 tests.
- The required Milestone 006 cases all terminate explicitly: success, invalid
  action exhaustion, tool exhaustion, repeated action, backend error, and wall
  timeout. An additional test covers turn exhaustion through the implementation
  contract, and context/budget visibility is verified.
- No model, edit tool, repository test command, or untrusted subprocess ran.

### Next allowed action

This historical gate is complete. Milestone 007 added the disposable workspace,
guarded patch contract, named test-command allowlist, timeout, process-group
control, output bounds, and macOS sandbox described below.

## Milestone 007 — Guarded editing and tests

Status: offline gate passed with 8 of 8 registered micro-repository issues.

### Implemented

- Added a disposable workspace builder that copies only allowed regular files,
  rejects symlinks and source/destination overlap, enforces file/byte limits,
  and creates a private clean Git baseline without consulting global config.
- Added strict unified-diff application for existing tracked UTF-8 files.
  Path escape, secret paths, file creation/deletion/rename/copy/mode changes,
  binary patches, staged/untracked state, malformed hunks, and excessive scope
  are rejected before application.
- Permitted a later guarded patch to revise prior unstaged edits so a failed
  solution can be diagnosed and corrected without recreating the workspace.
- Added a named-command test runner. The model can select
  `python-unittest`, but cannot supply shell text or arbitrary arguments.
- Added timeout, output caps, process-group termination, minimal environment,
  dedicated temporary storage, and a macOS sandbox that denies network, child
  processes, workspace writes, and reads outside approved runtime roots.
- Added a six-tool `EngineeringToolRegistry`: `list_files`, `search_code`,
  `read_file`, `apply_patch`, `run_tests`, and `git_diff`.
- Generalized the bounded loop to capability registries. A final answer can be
  rejected until a patch exists and the current patch has passing test
  evidence. Applying a later patch invalidates the earlier passing result and
  permits the same registered test to run again.
- Added a registered eight-case suite and reusable runner. It covers one-file
  behavior, a boundary regression, tests-first discovery, syntax failure,
  cross-file evidence, misleading output, a failed first patch with revision,
  and a two-file repair.

### Evidence

- The complete unit suite now contains 143 tests after the retrieval-context
  retrieval slice, including patch-policy, workspace,
  sandbox canary, engineering-registry, completion, and revision tests.
- The five test-runner cases pass in normal host execution. Canary commands
  cannot read an outside secret, open loopback networking, modify workspace
  source, or execute a child program. Timeout and output limits kill the whole
  process group and remain visible in observation metadata.
- `scripts/demo_engineering_agent.py` reaches `final_answer`; the registered
  `python-unittest` observation has exit code 0 and `sandboxed=true`; the Git
  diff contains the two-line `None` guard; and the source fixture remains
  byte-for-byte unchanged.
- `scripts/run_micro_suite.py` reports 8 registered, 8 solved, and
  `milestone_ready=true`. Three cases first observe failing tests. The retry
  case records exit codes `[1, 0]` around two patches, and the multi-file case
  changes exactly `src/accounts.py` and `src/preview.py`.
- The suite uses fake model decisions. No Qwen inference, SWE-bench task, or
  unrestricted terminal command is part of this evidence.
- Added `OllamaLoopBackend` as the local transport boundary for each bounded
  loop decision. Exactly one native tool call becomes a strict tool decision;
  zero calls with bounded content become a final decision; malformed, multiple,
  and unknown calls remain visible to validation rather than being repaired.
- Six fake-transport tests verify deterministic sampling, unload-after-turn
  smoke behavior, tool-surface equality, bounded backend errors, hidden-thinking
  exclusion, and a three-turn patch/test/final sequence through `AgentLoop`.
- Added `scripts/smoke_engineering_ollama.py`. It reserves a unique immutable
  evidence directory, requires zero initial swap and no loaded Ollama model,
  checks the frozen 2 GiB swap-growth and 5% free-memory limits around every
  inference, runs only in a disposable workspace, and captures the final diff
  independently of the model.
- Fourteen engineering-smoke tests cover a complete fake-Ollama repair,
  retained-swap, loaded-model, low-memory, post-inference swap-growth,
  transport-failure, recorder, and CLI outcomes. The fake repair changes only
  `src/tiny_parser.py`, records exit code 0, preserves the diff after workspace
  deletion, and leaves the source fixture unchanged.
- On 2026-08-12 before the TUI shell work, the complete host-level suite ran
  132 tests in 5.633 seconds; all passed with zero skips. No model inference
  occurred.
- Added a presentation-only `LoopObserver` contract to `AgentLoop`. Events and
  observations are appended to the trusted trace before observer callbacks run,
  observer exceptions are isolated, and the shipped terminal stream queues
  rendering work outside the loop path.
- Added `src/localcode/tui.py` and `scripts/demo_localcode_tui.py`. The terminal
  UI renders live phase, patch, test, diff, and final evidence from immutable
  events and `ToolResult` observations.
- Extracted `src/localcode/demo_repair.py` so the headless engineering demo and
  terminal UI demo share the same fake-backend parser repair runtime.
- New tests prove observer trace order, observer-error isolation, live terminal
  rendering, and exact headless/TUI result plus diff equality.
- On 2026-08-12 in normal Terminal, the learner ran the complete unit suite:
  136 tests in 6.451 seconds, `OK`, zero skips. The sandbox canaries executed
  outside the Codex sandbox; no model inference occurred.
- The learner's current host observation is 3612.62 MiB retained swap, 39% free
  memory, and an empty `ollama ps`. The swap value blocks the real smoke before
  any chat request; offline engineering may continue without a restart.

### Next allowed action

Wait for a zero-swap, unloaded-host baseline before invoking
`scripts/smoke_engineering_ollama.py`. Preserve the scripted 8/8 result as a
control and do not call it a local-model score. While the real run is blocked,
continue offline implementation rather than weakening the resource gate.

## Milestone 008 — Retrieval treatment

Status: deterministic retrieval is implemented, the scripted simple-vs-retrieval
control passed 8/8 in the learner's normal Terminal, and exploratory real-model
comparison exposed prompt/resource failure modes without yet proving a model
win.

### Implemented

- Added `src/localcode/retrieval.py`.
- Added `src/localcode/context.py`.
- `build_repository_map` returns a deterministic allowed-file map with
  repository-relative path, kind, language, byte size, line count, and extracted
  Python symbols.
- `select_retrieval_evidence` ranks source/test excerpts from issue terms,
  path terms, symbols, and content while excluding the already-supplied
  `ISSUE.md` from selected evidence.
- `evaluate_relevant_file_recall` measures expected changed-file recall under a
  fixed file budget.
- `SimpleContextCompiler` preserves the historical issue/history/budget context
  envelope.
- `RetrievalContextCompiler` adds bounded retrieved evidence only when the
  retrieval treatment is explicitly configured on `AgentLoop`.
- Added `context_mode` plumbing to the registered micro-suite runner so the
  same eight scripted repair cases can execute with either `simple` or
  `retrieval` context compilation.
- The micro-suite now records the first compiled context size and the retrieval
  selected paths, making the treatment observable instead of implicit.
- Added `scripts/demo_retrieval_pack.py` to inspect one registered micro-case
  retrieval pack.
- Added `scripts/demo_retrieval_context.py` to inspect the exact loop-ready
  context payload.
- Updated `scripts/run_micro_suite.py` to accept `--context-mode` and print the
  compiled-context evidence and typed observation error codes for each case.
- Extended `run_engineering_smoke` and `scripts/smoke_engineering_ollama.py`
  with the same `simple` vs `retrieval` context-mode switch used by the
  scripted micro-suite harness.
- Real-model smoke evidence now records `context_mode`, the first compiled
  context size, and the first retrieval selected paths so a future Qwen run can
  be compared on the same treatment boundary.

### Evidence

- `PYTHONPATH=src python3.11 -m unittest tests.unit.test_retrieval -v` passes
  4 tests.
- On the registered 8-case micro suite, the first retrieval metric recalls all
  9 expected changed paths under a fixed 3-file budget.
- `scripts/demo_retrieval_pack.py --case parser-none` prints `RECALL 1/1` and
  selects both `tests/test_tiny_parser.py` and `src/tiny_parser.py`.
- `scripts/demo_retrieval_pack.py --case username-consistency --max-files 3`
  prints `RECALL 2/2` and selects both changed files in the multi-file case.
- `scripts/demo_retrieval_context.py --case parser-none --max-files 2
  --max-context-chars 4000` prints `CONTEXT_CHARS 1947` and selects
  `tests/test_tiny_parser.py, src/tiny_parser.py`.
- On 2026-08-12 in the learner's normal Terminal, the complete unit suite ran
  143 tests in 6.161 seconds with `OK` and zero skips, and the retrieval
  context demo matched the Codex-sandbox result for the parser case.
- On 2026-08-12 in the learner's normal Terminal,
  `PYTHONPATH=src python3.11 scripts/run_micro_suite.py --context-mode simple`
  solved 8/8 registered cases, and
  `PYTHONPATH=src python3.11 scripts/run_micro_suite.py --context-mode retrieval`
  also solved 8/8. Retrieval selected the intended source/test evidence and
  increased first-turn context size, but this control did not yet show a solve
  advantage over simple context on the fixed micro suite.
- The comparison harness unit coverage now includes the new `context_mode`
  switch, retrieval selected-path recording, and invalid-mode rejection.
- Focused real-model smoke coverage now includes 17 tests. It verifies that
  retrieval mode reaches the actual Ollama chat payload, that the real-model
  smoke CLI forwards `--context-mode`, and that immutable smoke records reject
  context-mode mismatches.
- In the Codex sandbox, the complete unit suite now runs 143 tests with
  `OK (skipped=5)`. After the comparison-harness additions, the complete
  Codex-sandbox unit suite now runs 148 tests with `OK (skipped=6)`. The skips
  remain the known nested macOS sandbox canary/boundary cases.
- In the Codex sandbox, `scripts/run_micro_suite.py --context-mode simple` and
  `--context-mode retrieval` both terminate without solved cases because the
  nested macOS sandbox denies the registered test command. The printed
  observation codes are `sandbox_unavailable` followed by `incomplete_work`.
  That is an execution-boundary result, not a retrieval-quality comparison.
- An exploratory retained-swap override was added only so real-model
  engineering could continue without a forced reboot. With that override,
  `scripts/smoke_engineering_ollama.py --context-mode simple
  --allow-retained-swap` terminated with `backend_error` after swap grew by
  4,867,416,392 bytes beyond the registered 2 GiB inference gate.
- Under the same exploratory override,
  `scripts/smoke_engineering_ollama.py --context-mode retrieval
  --allow-retained-swap` survived the resource gate longer but produced two
  consecutive non-JSON model outputs, exhausted the invalid-action budget, and
  terminated without any tool execution. The first compiled retrieval context
  was 1,948 characters and selected `tests/test_tiny_parser.py` plus
  `src/tiny_parser.py`.
- These exploratory Qwen results are diagnostic only. They justify moving work
  to the experiment/evaluation layer instead of continuing unproductive reruns
  of the same configuration.
- After the experiment-layer additions, the complete Codex-sandbox unit suite
  now runs 155 tests with `OK (skipped=6)`.
- In the Codex sandbox,
  `PYTHONPATH=src python3.11 scripts/run_experiment.py` executes successfully
  but reports `A1=0/8` and `A2=0/8` because the outer sandbox blocks the
  registered nested macOS test sandbox. The case-level observation codes are
  `sandbox_unavailable` and `incomplete_work`; this is an execution-boundary
  result, not an experiment regression.
- This is a development metric only. It is not Qwen evidence, a solve-rate
  improvement, or SWE-bench readiness proof.

### Next allowed action

Use the new frozen comparison entry point,
`PYTHONPATH=src python3.11 scripts/run_experiment.py`, in the learner's normal
Terminal to preserve one canonical A1-vs-A2 artifact on the registered micro
suite. Do not treat the Codex-sandbox `0/8` output as model quality evidence.

Real-model work may resume later, but only as exploratory engineering until a
backend produces valid actions under the registered resource gates.

## Milestone 010 — Frozen four-way benchmark scaffold

Status: B0, A1, A2, and A3 are implemented on the deterministic micro suite.

### Implemented

- Added `src/localcode/experiment.py`.
- Added `benchmarks/experiment/manifest_v1.json`.
- Added `scripts/run_experiment.py`.
- Added `tests/unit/test_experiment.py`.
- The experiment manifest freezes one ordered ladder:
  `B0 -> A1 -> A2 -> A3`.
- `B0` is the implemented single-shot base with no tool loop or retry.
- `A1` is the implemented simple-context repair loop.
- `A2` is the implemented retrieval-context repair loop.
- Added `src/localcode/review.py`.
- `A3` is the implemented agent-plus-review treatment.
- The runner now measures all four configurations and reports review
  dispositions at case level instead of leaving `A3` as an unavailable stub.
- Adjacent comparisons are computed in order, so the scaffold already reports
  `B0->A1`, `A1->A2`, and `A2->A3` transitions on the same suite.

### Evidence

- `PYTHONPATH=src python3.11 -m unittest tests.unit.test_experiment
  tests.unit.test_repository_contract -v` passed after the experiment-layer
  additions.
- `PYTHONPATH=src python3.11 -m compileall -q src scripts tests/unit` passed.
- In the Codex sandbox,
  `PYTHONPATH=src python3.11 scripts/run_experiment.py` completes and prints
  the four configuration records plus adjacent deltas. The measured `0/8`
  outcomes for `B0`, `A1`, `A2`, and `A3` there are caused by the outer
  sandbox denying the registered nested test sandbox, matching the known
  micro-suite boundary. The reviewer therefore requests revision on every case
  instead of accepting missing test evidence.
- In normal Terminal, this runner is now the correct entry point for comparing
  implemented treatments on the same micro-suite manifest before any model is
  replaced.
- On 2026-08-12 in the learner's normal Terminal,
  `PYTHONPATH=src python3.11 scripts/run_experiment.py` produced the first
  full canonical four-configuration ladder result on `localcode-micro-v1`:
  `B0` 7/8, `A1` 8/8, `A2` 8/8, and `A3` 8/8.
- The paired `B0->A1` comparison showed exactly one gained case:
  `ratio-retry`. This is the registered failed-first-patch case, so the current
  micro suite now demonstrates concrete value from retry/tool-loop behavior
  rather than only raw solve counts.
- The paired `A1->A2` comparison showed no gains or losses; all eight cases
  were `solved_both`. Retrieval therefore changed selected evidence and context
  size, but not solved count on the current fixed micro suite.
- The paired `A2->A3` comparison also showed no gains or losses; all eight
  cases were `solved_both`. Under the current deterministic reviewer, every
  reviewed case recorded `review_disposition=accept` because the underlying A2
  patch, diff, and current passing test evidence were already complete.
- The normal-Terminal single-shot control,
  `PYTHONPATH=src python3.11 scripts/run_micro_suite.py --context-mode single_shot`,
  independently measured the same `B0` boundary: 7 solved, 1 failed, with the
  only failure again being `ratio-retry`. The first single-shot test exits were
  `[0]` for seven cases and `[1]` for `ratio-retry`, with no selected retrieval
  paths and unchanged source fixtures.
- Later on 2026-08-12, `B0` was implemented as a true single-shot path using a
  bounded repository map, one derived patch attempt, one bounded test run, and
  no retry/tool loop. The complete Codex-sandbox unit suite then ran 157 tests
  with `OK (skipped=7)`, and `PYTHONPATH=src python3.11 scripts/run_experiment.py`
  measured `B0`, `A1`, and `A2` together under the known outer-sandbox test
  boundary.
- Later on 2026-08-12, `A3` was implemented as a bounded review pass over the
  `A2` result. The reviewer sees the issue, current diff, test exit codes,
  selected retrieval evidence, and recorded error codes, then returns one of
  `accept`, `revise`, or `reject`. In the Codex sandbox, where nested test
  execution is blocked, every `A3` case records `review_disposition=revise`
  because the underlying `A2` run lacks current passing test evidence.
- After the review-layer additions, the complete Codex-sandbox unit suite ran
  162 tests with `OK (skipped=7)`.

### Decision

Keep the experiment layer even if Qwen is replaced. The measurement contract is
now separated from any one backend choice.

### Next allowed action

The frozen ladder is now measured end-to-end on the micro suite:
`B0=7/8`, `A1=8/8`, `A2=8/8`, `A3=8/8`.

Do not spend more time rerunning this micro benchmark. The next meaningful
engineering step is to move up one layer: either make the reviewer materially
more discriminating on deterministic development cases, or start the benchmark
harness proof for real issues while preserving this micro-suite result as the
control.

## Milestone 009 — Real benchmark runner scaffold

Status: the pinned real-subset runner contract now exists, but the actual
20-instance manifest and official gold/empty harness proof remain unverified.

### Implemented

- Added `src/localcode/real_benchmark.py`.
- Added `tests/unit/test_real_benchmark.py`.
- The new layer is separate from `src/localcode/experiment.py` so the
  deterministic micro-suite ladder remains intact while real-issue evaluation
  grows as a distinct boundary.
- The real-benchmark manifest now has a strict contract:
  one pinned subset ID, dataset name/split/revision, selection seed,
  per-repository cap, fairness controls, frozen `B0/A1/A2/A3` order, and
  exactly 20 unique instances with `instance_id`, repository, and base commit.
- `prepare_real_benchmark_run(...)` now creates immutable run evidence under
  `runs/real-benchmark/<run_id>/`, snapshots the manifest, resolves the pinned
  issues through a trusted resolver, records per-configuration patch attempts,
  and writes the official prediction JSONL shape
  `{instance_id, model_name_or_path, model_patch}` for each configuration.
- `run_real_benchmark(...)` now layers evaluator results on top of those
  prediction artifacts and reports per-configuration resolved counts, adjacent
  `B0->A1->A2->A3` gains/losses, aggregate token/tool/wall-time usage, and one
  primary failure category per instance.
- Failure categories are now frozen in this layer as:
  `ENVIRONMENT`, `LOCALIZATION`, `COMPREHENSION`, `EDIT_INVALID`,
  `FIX_INCOMPLETE`, `REGRESSION`, `VERIFICATION`, `LOOP_CONTROL`,
  `REVIEW_HARM`, and `UNKNOWN`.

### Evidence

- `PYTHONPATH=src python3.11 -m unittest tests.unit.test_real_benchmark
  tests.unit.test_repository_contract -v` passed on 2026-08-12.
- The added tests prove:
  - non-20-instance manifests are rejected;
  - the per-repository cap is enforced at manifest load time;
  - prepared prediction artifacts use the official JSONL field names and write
    an empty patch for `no_patch` attempts; and
  - the final runner computes resolved counts, adjacent gains, and primary
    failure categories such as `ENVIRONMENT`, `LOOP_CONTROL`, and
    `FIX_INCOMPLETE`.
- After adding this layer, the full Codex-sandbox unit suite ran
  166 tests with `OK (skipped=7)` on 2026-08-12.

### Decision

Keep this runner separate from the micro-suite scaffold. Real-issue evaluation
must remain a manifest/evidence/evaluator layer, not a hidden mode inside the
deterministic development suite.

### Next allowed action

Do not claim Milestone 009 complete yet. The next required work is external to
this scaffold:

- freeze the actual 20-instance manifest;
- wire a real issue resolver against the pinned dataset snapshot;
- connect the official SWE-bench evaluator; and
- prove one gold instance resolves while one empty-patch control does not.

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
| D-016 | Defer Qwen3.5 inference while retained swap remains | Preserves the registered clean-baseline evidence boundary at the learner's request | pending zero-swap baseline |
| D-017 | Publish only `learning/` to GitHub Pages | The browser curriculum is static; repository tools, models, and local evidence must remain outside the web artifact | fixed |
| D-018 | Advance offline milestones independently of the deferred Qwen run | Fake-backend engineering does not consume model resources or claim model compatibility; the learner prioritized faster implementation without restarting | fixed for offline work |
| D-019 | Permit edits and tests only in disposable workspaces through strict patches and named sandboxed commands | The agent needs hands and executable feedback without gaining arbitrary filesystem, shell, process, or network authority | fixed for Milestone 007 |
| D-020 | Close the Milestone 007 offline gate at eight varied scripted cases | Eight is the registered minimum and includes failure observation, retry, misleading output, and multi-file scope without conflating runtime proof with model quality | fixed |
| D-021 | Translate Ollama transport shapes without repairing model intent | Native tool calls and plain finals need protocol envelopes, while malformed, multiple, or unknown calls must remain attributable to the model | fixed for local-model loop |
| D-022 | Capture resource evidence around every real-model turn and capture the final diff in trusted code | A clean start alone cannot detect mid-run memory instability, and patch evidence must not depend on the model remembering a review tool | fixed for engineering smoke |
| D-023 | Keep the terminal UI as an observer over immutable loop facts | Headless and TUI runs must measure the same runtime, patch, and termination behavior | fixed for TUI shell |
| D-024 | Measure retrieval first with relevant-file recall | Retrieval must show deterministic evidence-selection value before being credited with solve-rate improvement | fixed for first Milestone 008 slice |
| D-025 | Translate content-form JSON tool calls (exactly one `{"name","arguments"}` object) into tool decisions without weakening the strict validator | Real Qwen checkpoints emit tool intent as JSON text in `content`; misreading it as a final answer caused every pilot to end in `invalid_action_exhaustion` | fixed 2026-08-16 |
| D-026 | Tighten both Ollama system prompts with explicit schema-validity rules (no nulls on string/integer/boolean fields except `glob`/`end_line`, no zero below minimums, exact types, required fields, omit unneeded optionals, final-answer fallback) | The m004c tool-schema score of 0/12 shows models emit nulls and zero bounds that the strict validator rejects; the registered prompt did not state these rules | fixed 2026-08-16 |
| D-027 | Raise the real-producer context budget (context_tokens 16,384 to 32,768 and max_context_chars 16,000 to 32,000, now a tunable) and forbid shell/bash/code-block output in the loop prompt | The m023 trace showed `history:[]` and `truncated:true` on the apply_patch turn: the 16K-char budget dropped the read_file content entirely, so the model hallucinated diffs and emitted bash code blocks; a model cannot patch what it cannot see | fixed 2026-08-16 |
| D-028 | Add an explicit quoted-integer example to the schema rules and treat residual tool-call discipline failures as model-capability evidence | The m024 trace shows `qwen3.5:9b` emitting `"max_results": "30"` (quoted string) despite the rules, plus repeating a 0-match search against controller guidance; prompting has diminishing returns on this 9B model | fixed 2026-08-16; next action is the stronger qwen3-coder:30b candidate |
| D-029 | Make an unavailable evaluator non-fatal (record each case as environment_error) and expose a deliberate `--allow-retained-swap` lever on the real producer | m026 showed a Docker-down evaluator crashing the whole run and destroying producer evidence; macOS retains ~4 GiB swap that only a restart clears, so the learner needs a recorded way to proceed with retained swap while the per-turn growth guard still protects the host | fixed 2026-08-16 |
| D-030 | Keep the model resident across real-loop turns (`keep_alive` configurable, default 300 s on the producer; loop backend default stays 0) | The first m027 flask turn was mid-generation when Ctrl-C'd; `keep_alive: 0` reloaded the 9 GB model every turn, making each loop turn slow and the run look stuck | fixed 2026-08-16 |
| D-031 | Run the next real pilot with the A2 retrieval treatment | m028's trace shows the 14B guessed the wrong path (`flask/blueprints.py` instead of `src/flask/blueprints.py`), never saw the real file, and hallucinated the diff; the A2 repository map + ranked excerpts exist precisely to fix path finding, and this is the benchmark's core hypothesis | pending m029 |
| D-032 | Bound the rendered retrieval repository map to 40 files with a `map_truncated` flag | m029's trace shows `MAX_RETRIEVAL_FILES = 1,000` made the A2 payload (~100 KB for Flask) exceed the 32K context budget, so the truncator dropped history and all `retrieved_evidence` every turn, leaving the model blind; the map must fit in budget for A2 to work at all | fixed 2026-08-16 |
| D-033 | Strip one surrounding markdown code fence before parsing content-form JSON tool calls | m031's trace shows the 14B found the correct paths via retrieval but wrapped its content-form JSON in ` ```json ... ``` `, which the exact-shape translator rejected as narration; the fence is presentation, not intent, and the strict validator still enforces the schema | fixed 2026-08-16 |
| D-034 | Accept the `tool` key as an alias for `name` in content-form JSON tool calls, still requiring exactly two keys | m032's trace shows the 14B naming the tool field `tool` instead of `name` near the end of the loop; it is a transport alias, while echoed-history JSON (extra keys) must stay untranslated | fixed 2026-08-16 |

## Run ledger

| Run ID | Model and artifact | Result | Evidence |
|---|---|---|---|
| `m004c-qwen25-7b-v1` | Qwen2.5-Coder-7B-Instruct Q4_K_M; manifest `dae161e27b0e90dd1856c8bb3209201fd6736d8eb66298e75ed87571486f4364` | stopped after 1/20; `swap_growth_limit`; exit 1; no compatibility score; 0 tools executed | immutable run directory; prompt/config/source hashes; raw request/stream; 4.15 GiB swap growth; 4.42 GiB allocation; tool-format near-miss |
| `m004c-qwen25-7b-v2` | Qwen2.5-Coder-7B-Instruct Q4_K_M; manifest `dae161e27b0e90dd1856c8bb3209201fd6736d8eb66298e75ed87571486f4364` | complete; failed quality; tool schema 0/12, decisions 1/16, reasoning 3/4; exit 1; 0 tools executed | immutable 836 KiB run; all 20 prompts and 4K/16K probes; zero swap; 5.25 GiB peak allocation; 74% minimum free memory |
| `m004c-qwen3-30b-v1` | Qwen3-Coder-30B-A3B-Instruct Q4_K_M; manifest `06c1097efce0431c2045fe7b2e5108366e43bee1b4603a7aded8f21689e90bca` | stopped after 1/20; `swap_growth_limit`; schema 1/1 evaluated; decision 0/1 evaluated; exit 1; 0 tools executed | immutable run directory; clean zero-swap baseline; 2.53 GiB swap growth; 17.57 GiB allocation; 14% minimum free memory |
| `m010-agent-flask-a1-v1..v6`, `m010-agent-full-a1-v1` | `qwen3.5:9b-q4_K_M` on `pallets__flask-5014` | 0/20; pilot scope excluded 19 instances; `invalid_action_exhaustion` on the pilot | `runs/real-benchmark/m010-*`; empty-patch summaries |
| `m011..m017-agent-flask-a1-v1` | `qwen3.5:9b-q4_K_M` on `pallets__flask-5014` | 0/20; 3–5 tool calls then `invalid_action_exhaustion` | `runs/real-benchmark/m011..m017-*` |
| `m018-agent-flask-qwen25-a1-v1` | `qwen2.5-coder:7b-instruct-q4_K_M` on `pallets__flask-5014` | 0/20; `invalid_action_exhaustion`, 0 tool calls | `runs/real-benchmark/m018-*` |
| `m019-agent-flask-qwen35-phase-v1` | `qwen3.5:9b-q4_K_M` on `pallets__flask-5014` | 0/20; 5 tool calls, 152.9 s, `invalid_action_exhaustion` | `runs/real-benchmark/m019-*` |
| `m020-postrestart-flask-a1-v1` | `qwen3.5:9b-q4_K_M` after restart | 0/20; `invalid_action_exhaustion` | `runs/real-benchmark/m020-*` |
| `m021-deepseek-flask-a1-v1` | `deepseek-coder:6.7b` on `pallets__flask-5014` | 0/20; `backend_error` after 2.18 s, 0 tool calls | `runs/real-benchmark/m021-*` |
| `m022-pilot-schema-v1` | `qwen3.5:9b-q4_K_M` on `pallets__flask-5014`; tightened prompts active | interrupted by Ctrl-C during the flask agent loop after ~2 min; no patch recorded; run dir immutable and not reusable | `runs/real-benchmark/m022-pilot-schema-v1/` (partial) |
| `m023-pilot-schema-v1` | `qwen3.5:9b-q4_K_M` on `pallets__flask-5014`; tightened prompts; progress output | completed; 0/20; flask 5 tool calls then `invalid_action_exhaustion` in 83.8 s; raw trace preserved at `runs/trace-m023.jsonl` | root cause in trace: context truncation dropped all history before `apply_patch`, so the model worked without file content |
| `m024-pilot-context-v1` | `qwen3.5:9b-q4_K_M` on `pallets__flask-5014`; raised context budget | completed; 0/20; flask 2 tool calls then `invalid_action_exhaustion` in 45.3 s; trace at `runs/trace-m024.jsonl` | context fix proved (history present); new failure is model discipline: `"max_results": "30"` quoted-string integers rejected by the schema, and repeated same search_code with a 0-match regex |
| `m025-pilot-30b-v1` | `qwen3-coder:30b-a3b-q4_K_M` on `pallets__flask-5014` | blocked at preflight before any model call: `real-model smoke requires zero swap; observed 4210619843 bytes` (4.2 GiB); classified `ENVIRONMENT`; smoke `smoke-30b-v1` beforehand passed with zero swap and a schema-valid `search_code` (match_count 1) | loading the 18 GB model in the smoke produced retained swap that the strict zero-swap preflight correctly rejected; rerun needs a clean baseline (restart, close apps) |
| `m026-pilot-30b-clean-v1` | `qwen3-coder:30b-a3b-q4_K_M` on `pallets__flask-5014` | blocked again by the same 4210619843-byte retained swap (host was not actually clean), then the whole run crashed because the Docker evaluator could not connect (`docker.from_env` socket missing) | two findings: (1) macOS retains ~4 GiB swap even with only VS Code open and a restart is required to clear it; (2) an unavailable evaluator must not destroy the run — fixed to record environment errors (D-029) |
| `m027-pilot-14b-v1` | `qwen2.5-coder:14b-instruct-q4_K_M` on `pallets__flask-5014`; retained swap allowed | interrupted by Ctrl-C during the first flask model turn (mid `stream_chat` read, i.e. generation in progress); smoke `smoke-14b-v1` passed with a schema-valid `search_code` (match_count 5) | the loop was working; per-turn `keep_alive: 0` made each 9 GB reload slow, so the run felt stuck — fixed by D-030 (resident keep_alive 300 s); rerun with a new ID |
| `m028-pilot-14b-v1` | `qwen2.5-coder:14b-instruct-q4_K_M` on `pallets__flask-5014`; keep_alive 300 s | completed; 0/20; flask 5 tool calls then `invalid_action_exhaustion` in 100 s; trace at `runs/trace-m028.jsonl`; Docker down recorded as environment_error (D-029 worked, run survived) | the 14B emits content-form JSON tool calls and D-025 translated the exact `{name, arguments}` shape, so 5 calls executed (search, read_file, apply_patch, run_tests, git_diff); the model guessed the wrong path (`flask/blueprints.py` not `src/flask/blueprints.py`), never saw the real file, hallucinated the diff, then emitted markdown-fenced `{tool, arguments}` JSON 4x (correctly not repaired) |
| `m029-pilot-14b-a2-v1` | `qwen2.5-coder:14b-instruct-q4_K_M`, A2 retrieval on `pallets__flask-5014` | completed; 0/20; flask 5 tool calls then `invalid_action_exhaustion` in 41 s; trace at `runs/trace-m029.jsonl` | A2 did not help because the retrieval payload never reached the model: `MAX_RETRIEVAL_FILES = 1,000` renders the full repository map (~100 KB for Flask), which alone blew the 32K context budget; the truncator dropped history AND `retrieved_evidence` on every turn (`"history":[],"truncated":true`), leaving the model blind again — fixed by D-032 |
| `m030-pilot-14b-a2-v2` | `qwen2.5-coder:14b-instruct-q4_K_M`, A2 on `pallets__flask-5014` | blocked at preflight before any model call: `real-model smoke requires an empty Ollama process list; observed ('qwen2.5-coder:14b-instruct-q4_K_M',)` | the D-030 keep_alive=300 kept the model resident from m029; the preflight correctly requires an empty `ollama ps` — unload with `ollama stop qwen2.5-coder:14b-instruct-q4_K_M` before rerunning |
| `m031-pilot-14b-a2-v3` | `qwen2.5-coder:14b-instruct-q4_K_M`, A2 on `pallets__flask-5014`; map fix active | completed; 0/20; flask 1 tool call then `invalid_action_exhaustion` in 89.6 s; trace at `runs/trace-m031.jsonl` | D-032 map fix worked: retrieval reached the model and it found the correct paths (`src/flask/blueprints.py`, `src/flask/app.py`); new quirk: it wraps content-form JSON in markdown code fences (` ```json ... ``` `), which the translator rejected — fixed by D-033 (strip one surrounding fence) |
| `m032-pilot-14b-a2-v4` | `qwen2.5-coder:14b-instruct-q4_K_M`, A2 on `pallets__flask-5014`; fence fix active | completed; 0/20; flask 5 tool calls then `invalid_action_exhaustion` in 176 s; trace at `runs/trace-m032.jsonl` | closest run yet: the model read the correct file (`src/flask/blueprints.py` line 117) and attempted a real apply_patch at the correct location with real class context, then run_tests and git_diff; but (a) the patch carried a fake index hash (`abcdef1..abcdef2`) so it did not apply (`git_diff file_count: 0`), and (b) it then emitted `{tool, arguments}` shapes and echoed a full history entry as content — the exact two-key shape guard rejected them, ending in exhaustion. D-034 accepts the `tool` alias; the applying-diff gap is now a model-quality question |

Future entries must record: run ID, Git SHA, model ID and artifact hash,
quantization, prompt version, configuration, task manifest hash, budgets, seed,
start/end time, result, patch hash, test evidence, and failure category.

## Milestone 009 — real harness controls

Status: control proof passed; the real model producer and scored B0/A1/A2/A3
20-task run remain pending.

### Implemented

- Added `src/localcode/real_benchmark_adapters.py` with a file-backed issue
  resolver, an explicit gold/empty control producer, and an official SWE-bench
  subprocess evaluator that reads per-instance Docker reports.
- Added `scripts/pin_real_manifest.py` and
  `scripts/run_real_benchmark.py`.
- Pinned `benchmarks/real_benchmark/manifest_v1.json` to
  `SWE-bench/SWE-bench_Verified`, `test`, revision
  `hf-main-03e151cf5560b1af6a4363c6a9d766deaaea6b56`, seed `20260813`, and 20
  exact instance IDs/base commits across 12 repositories with a five-task cap.
- Added `docs/MILESTONE_009_LESSON.md` and extended the learning ledger with
  the real benchmark boundary and its controls.
- Installed the official `swebench` 4.1.0 harness only in ignored
  `.venv-realbench`; the project runtime remains dependency-free.

### Evidence

- Dataset snapshot downloaded from the official Hugging Face repository and
  retained locally under ignored `data/raw/`; it contains 500 Verified test
  rows. The manifest contains 20 rows and loads through the strict validator.
- `PYTHONPATH=src python3.11 -m unittest discover -s tests/unit -q` passed 169
  tests with `OK (skipped=7)`; targeted adapter tests and compilation also
  passed.
- Empty control run `m009-empty-v4` produced an immutable
  `runs/real-benchmark/m009-empty-v4/run_summary.json`: `B0=0/20`, `A1=0/20`,
  `A2=0/20`, `A3=0/20`; all 80 cases were `LOOP_CONTROL` with empty patches.
- Gold control run `m009-gold-flask-b0-v2` measured `B0=1/20` with only
  `pallets__flask-5014` carrying the official gold patch; that instance
  resolved under the official Docker harness. A direct attached harness run
  recorded `resolved: true`, patch application success, and the target test
  passing in `logs/run_evaluation/direct-flask-gold-v3/.../report.json`.
- Docker Desktop was started after restart; the official x86 base image and
  Flask environment image built under ARM emulation. Docker reports 12 CPUs and
  8,321,232,896 bytes allocated, so this remains a pilot resource boundary.

### Honest boundary

The gold/empty controls prove the evaluator path, not model quality. No claim
of B0/A1/A2/A3 real solve rate is allowed until a trusted patch producer runs
the LocalCode loop in disposable real repositories and supplies four measured
prediction files. Gold patches and evaluator-only fields remain excluded from
the agent context.

### Next allowed action

Implement a real-repository `PatchProducer` adapter (clone at pinned
`base_commit`, run the bounded LocalCode configuration, capture diff/metrics,
and clean the workspace), then run one non-gold pilot before the frozen 20.

## Milestone 009 — real-model pilot runs and transport diagnosis (m010–m021)

Status: pilot evidence recorded; root cause diagnosed and first half fixed;
a fresh pilot is the next allowed action.

### Question

With the real-repository `PatchProducer` in place, can a local open-weight
model drive the bounded loop to a valid patch on one pilot instance
(`pallets__flask-5014`) before the frozen 20?

### What was run (all preserved immutably under `runs/real-benchmark/`)

- The producer scope was deliberately limited to `pallets__flask-5014`; the
  other 19 manifest instances were skipped with `producer scope excludes this
  instance`, so none of these runs is a scored 20-task run.
- `qwen3.5:9b-q4_K_M` — m010 (six variants), m011–m017, m019: the loop called
  the model for real; 3–5 tool calls executed on the pilot, then
  `invalid_action_exhaustion`.
- `qwen2.5-coder:7b-instruct-q4_K_M` — m018: `invalid_action_exhaustion` with
  zero executed tool calls.
- `deepseek-coder:6.7b` — m021: `backend_error` after ~2.2 s with zero tool
  calls (transport/model availability); m020 was a post-restart rerun.
- Every pilot: `resolved=0/20`, `empty_patch=20`. The root-level
  `*.localcode-a1-*.json` files are the same empty-patch summaries.

### Diagnosis (confirmed deterministically)

- Preserved m004c streams (`runs/model-compatibility/m004c-qwen25-7b-v2/
  responses/tool-*.stream.jsonl`) show the models emitting tool calls as plain
  JSON text in `content` — `{"name": "git_diff", "arguments": {...}}` — with no
  native `tool_calls` entry.
- `_loop_protocol_payload` therefore wrapped that short content as a `final`
  decision. With `require_patch=True` and no patch applied, the loop rejected
  each premature final, and after `max_invalid_actions=4` the run terminated
  with `invalid_action_exhaustion` — the model's tool intent never executed.
- `scripts/verify_pilot_failure.py` reproduces the exact path: before the fix
  the payload was a `final` decision; after the fix it is a `tool` decision,
  and the validator still rejects the model's exact emission
  (`path: null`) at the strict argument schema.

### Fix implemented 2026-08-16

- Added `content_form_tool_call()` to `src/localcode/backends/ollama.py` and
  wired it into both `_protocol_payload` and `_loop_protocol_payload`. A
  content payload that is exactly one `{"name", "arguments"}` JSON object is
  translated into the tool decision envelope; all other content is untouched,
  so narration is never repaired into a tool call and the strict validator
  still enforces tool name and argument schema.
- Added four unit tests in `tests/unit/test_ollama_loop_backend.py`:
  content-form translation, strict-schema enforcement after translation,
  no-repair for non-tool JSON content, and a full content-form
  patch→test→final loop. Full suite: 174 tests, all pass.

### Remaining barrier (decision needed)

The model's exact emitted arguments often violate the strict schema
(`path: null` where a string is required; `max_results: 0` below its minimum).
This matches the m004c tool-schema score of 0/12. Before a fresh pilot, choose
deliberately between (a) prompting/formatting the model to emit schema-valid
arguments, (b) relaxing or normalizing specific schema defaults without
weakening safety, or (c) treating strict-schema failures as model evidence and
switching candidate. Record the decision here before running a new pilot.

### Honest boundary

No real-model solve score exists yet. The m010–m021 pilots prove the loop can
call the model on a disposable real repository; they do not prove the model can
produce a valid patch. The frozen 20-run requires a fresh run ID after any
protocol or model change, per the registered fairness controls.
