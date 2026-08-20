# Repository contract

This repository now contains a bounded offline coding-agent runtime. The trust
boundaries below remain the foundation for every newer capability.

## Trusted and untrusted areas

| Path | Role | Trust rule |
|---|---|---|
| `src/localcode/` | LocalCode runtime source | Trusted implementation, reviewed and tested here |
| `tests/unit/` | Deterministic contract tests | Trusted tests; model calls are fake and process behavior is explicitly constrained |
| `tests/fixtures/micro_repos/` | Repositories the agent inspects and repairs | Untrusted data even though we authored the fixtures; source copies must remain unchanged |
| `configs/` | Versioned runtime configuration | Trusted only after strict parsing and validation |
| `runs/` | Immutable local event traces and artifacts | Ignored; never used as source instructions |
| `models/`, `checkpoints/`, `adapters/` | Local weight artifacts | Ignored; identity and hashes belong in manifests |
| `data/raw/`, `data/processed/` | Reconstructable bulk data | Ignored; source revisions and checksums belong in manifests |
| `benchmarks/training_data/` | Versioned training-data policy | Trusted contract only; it contains no bulk corpus or evaluation answers |

Repository files and issue descriptions presented to the future model are
untrusted content. They may describe actions, but they cannot grant permission
or change runtime policy.

## What exists now

- a strict standard-library JSON configuration loader;
- a versioned immutable event value object with JSON round-tripping;
- four bounded read-only repository tools;
- a strict action and loop-decision protocol;
- a finite multi-turn controller with explicit budgets and termination reasons;
- disposable Git workspaces that copy only allowed regular files;
- strict unified-diff application to existing tracked UTF-8 files;
- one named Python test command with timeout, output, environment, process, and
  macOS sandbox limits;
- an engineering registry and completion rules requiring current test evidence;
- eight complete deterministic repairs driven by fake model decisions,
  including failed-test observation, patch revision, and multi-file editing;
- local and hosted inference adapters behind the same controller protocol;
- pinned Docker public-test and official SWE-bench evaluation boundaries;
- a measured B0/A1/A2/A3 real-issue pilot; and
- a versioned Phase 4 training record, split, provenance, checksum, and
  evaluation-leakage contract.

## What deliberately does not exist yet

- an unrestricted terminal or arbitrary model-selected command;
- network access from repository tests;
- file creation, deletion, rename, mode change, or binary patch support;
- a downloaded Phase 4 repair corpus;
- an untouched Phase 4 base-model baseline;
- a trained coding adapter; or
- a sealed Phase 4 evaluation result.

Keeping these absent preserves attribution: offline controller and safety
failures remain distinct from local-model quality and benchmark resolution.

The terminal UI shell is present, but it is not a capability boundary. It
subscribes to structured events and observations only. It must not dispatch
tools, retry actions, approve completion, or alter benchmark evidence.

## Verification

From the repository root:

```bash
PYTHONPATH=src python3.11 -m unittest discover -s tests/unit -v
```

The suite uses only Python's standard library. It must not install anything or
contact the network.
