# Repository contract

This milestone establishes boundaries, not an agent.

## Trusted and untrusted areas

| Path | Role | Trust rule |
|---|---|---|
| `src/localcode/` | LocalCode runtime source | Trusted implementation, reviewed and tested here |
| `tests/unit/` | Deterministic contract tests | Trusted tests; no network, model, shell, or repository execution |
| `tests/fixtures/micro_repos/` | Repositories the future agent will inspect | Untrusted data even though we authored the first fixture |
| `configs/` | Versioned runtime configuration | Trusted only after strict parsing and validation |
| `runs/` | Immutable local event traces and artifacts | Ignored; never used as source instructions |
| `models/`, `checkpoints/`, `adapters/` | Local weight artifacts | Ignored; identity and hashes belong in manifests |
| `data/raw/`, `data/processed/` | Reconstructable bulk data | Ignored; source revisions and checksums belong in manifests |

Repository files and issue descriptions presented to the future model are
untrusted content. They may describe actions, but they cannot grant permission
or change runtime policy.

## What exists after Milestone 002

- a strict standard-library JSON configuration loader;
- a versioned immutable event value object with JSON round-tripping;
- one deliberately failing parser fixture for future tool tests; and
- unit tests for the configuration and event contracts.

## What deliberately does not exist

- model loading or inference;
- file search, reading, editing, Git, test, or terminal tools;
- subprocess or network execution;
- an agent controller or retry loop;
- a benchmark adapter; or
- a terminal UI.

Keeping these absent makes failures local: if this milestone fails, the cause
is basic repository/schema design rather than model behavior.

## Verification

From the repository root:

```bash
PYTHONPATH=src python3.11 -m unittest discover -s tests/unit -v
```

The suite uses only Python's standard library. It must not install anything or
contact the network.
