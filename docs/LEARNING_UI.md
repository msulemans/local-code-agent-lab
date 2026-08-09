# Learning UI

The static browser field manual translates the LocalCode architecture and
verified project state into interactive lessons. It uses no framework, package,
remote font, analytics, model, API, or network dependency.

## Run it

From the repository root:

```bash
python3.11 scripts/serve_learning_lab.py
```

Open `http://127.0.0.1:4173` and stop the server with `Ctrl-C`.

## Learning structure

1. **Anatomy** assigns responsibility to issue, controller, context compiler,
   model, validator, tools, event store, and evaluator.
2. **Tool contracts** simulate the four implemented read-only tools and their
   rejection/truncation behavior without touching the filesystem.
3. **Agent loop** connects each state transition to a structured event and
   distinguishes the implemented one-turn proof from the planned multi-turn,
   edit, test, and review capabilities.
4. **Milestone ledger** separates verified work from the next plan.
5. **Benchmark science** compares B0/A1/A2/A3 while teaching fairness and
   evaluator-only boundaries.
6. **Failure laboratory** preserves real project failures as reusable diagnosis.
7. **Practice** provides explain-back cards and an eight-question assessment.
8. **Glossary** makes agent, repository, and SWE-bench terminology searchable.

Learning completion, deep-note preference, last section, and best quiz score are
stored in browser local storage under `localcode-learning-state-v1`. This is a
personal reading aid, not canonical project evidence. `AGENT_STATE.md` remains
the source of truth for implementation progress.

## Design direction

The interface uses an agent flight-recorder visual language: event tickets,
trace rails, bounded console observations, and state labels. This makes the
project's core idea—model proposals becoming controlled runtime evidence—the
visual signature rather than generic dashboard decoration.

## Verify it

```bash
node --check learning/app.js
node tests/ui/rendered-html.test.mjs
PYTHONPATH=src python3.11 -m unittest discover -s tests/unit -v
```

The browser tool console is explicitly a simulation. It never imports or calls
the Python repository tools; doing so would require a deliberately designed
local API boundary in a later product milestone.
