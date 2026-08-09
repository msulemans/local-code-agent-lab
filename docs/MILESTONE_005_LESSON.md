# Milestone 005 lesson — from model text to one safe action

## Outcome

LocalCode can now take one untrusted backend response, validate it, execute at
most one read-only repository tool, and record the result. The offline proof
uses a fake backend, so it requires no Ollama load or restart.

This is not a multi-turn agent yet. It cannot edit, run repository tests, retry,
or declare an issue solved.

## The five-part pipeline

```text
issue -> backend text -> ActionValidator -> ToolRegistry -> observation/events
```

1. The **issue** is untrusted problem data.
2. The **backend** proposes one action as JSON text. In tests it is fake; later
   it will be the selected local model.
3. The **validator** checks protocol version, exact fields, tool name, and the
   selected tool's argument schema.
4. The **registry** maps the accepted name to one real read-only function.
5. The **controller** returns a bounded observation and immutable event trace.

The model proposes. Trusted Python code decides whether anything runs.

## The action envelope

```json
{
  "protocol_version": "1",
  "thought_summary": "Find the parser definition before reading files.",
  "action": {
    "tool": "search_code",
    "arguments": {
      "query": "def parse",
      "path": ".",
      "max_results": 40,
      "regex": false,
      "case_sensitive": true,
      "glob": null
    }
  }
}
```

Why version it? A recorded run must say which language the model and controller
were speaking. If version 2 later changes fields or meanings, old traces remain
interpretable.

Why `thought_summary` instead of hidden reasoning? We need a short inspectable
hypothesis, not private chain-of-thought or thousands of unbounded tokens.

## Validation is not repair

The validator may:

- parse exact JSON;
- add defaults already declared in the tool schema;
- canonicalize harmless syntax such as `./src/` to `src`;
- reject an invalid proposal with a typed code.

It may not silently change `terminal` into `search_code`, turn a bad glob into a
path, or guess a missing query. Those changes would make controller intelligence
look like model intelligence and corrupt later benchmark comparisons.

## Two different safety gates

Schema validation asks: “Is this a well-formed `read_file` request?”

Repository policy asks: “May this exact path be read?”

Therefore `{ "path": "../secret.txt" }` can pass the string type check and
still be rejected by the tool with `path_escape`. Keeping both gates matters:
the schema describes shape; the tool owns real filesystem policy.

## Run the four offline experiments

From the repository root:

```bash
PYTHONPATH=src python3.11 scripts/demo_one_turn.py --case valid
PYTHONPATH=src python3.11 scripts/demo_one_turn.py --case invalid-json
PYTHONPATH=src python3.11 scripts/demo_one_turn.py --case unknown-tool
PYTHONPATH=src python3.11 scripts/demo_one_turn.py --case path-escape
```

Predict each event sequence before running it:

| Case | Expected sequence | Tool executes? |
|---|---|---|
| valid | `run_created -> action_accepted -> tool_result` | yes, once |
| invalid JSON | `run_created -> action_rejected` | no |
| unknown tool | `run_created -> action_rejected` | no |
| path escape | `run_created -> action_accepted -> tool_error` | attempted, but no file read |

Then run the complete offline proof:

```bash
PYTHONPATH=src python3.11 -m unittest discover -s tests/unit -v
```

The current expected result is `Ran 53 tests` followed by `OK`.

## Read the implementation in this order

1. `configs/action_protocol_v1.json` — the versioned outer contract.
2. `benchmarks/model_compatibility/tool_schemas.json` — each tool's arguments.
3. `src/localcode/actions.py` — parsing and strict validation.
4. `src/localcode/registry.py` — the exact name-to-function map.
5. `src/localcode/controller.py` — one backend call and at most one tool call.
6. `tests/unit/test_one_turn_controller.py` — executable claims.

## Explain-back check

Answer without looking:

1. Why is valid JSON not automatically a safe action?
2. Why does an unknown tool become an observation instead of executing?
3. Why is `path_escape` a tool error rather than an invalid JSON error?
4. Why do tests inject a fixed clock?
5. What would be scientifically dishonest about silently repairing arguments?

Good answers mention separate trust boundaries, typed feedback for a future
retry, filesystem policy, deterministic event equality, and fair attribution of
model quality.

## Handoff prompt for a smaller assistant

```text
We are working only on LocalCode Milestone 005 in
/Users/suleman/non-icloud/Personal/learning-labs/local-code-agent-lab.

Read AGENT_STATE.md, docs/MILESTONES.md, and docs/MILESTONE_005_LESSON.md first.
The offline one-turn controller is implemented and 53 unit tests pass. Qwen3.5
9B is downloaded and verified but must not be run until the learner chooses a
restart and a clean unloaded-host baseline is captured. Do not weaken that
gate. Do not start the multi-turn loop, editing, test execution, SWE-bench, or
download another model.

When helping me learn, explain one concept at a time, ask me to predict the
result before revealing it, and ground every claim in a named file or test.
Allowed work now: inspect the protocol, run fake-backend demos, add bounded
fake-backend tests, or improve the Milestone 005 lesson without model inference.
```

## Remaining gate

The fake backend proves our controller logic. It does not prove that Qwen3.5
emits usable actions on this Mac. That bounded smoke test remains pending until
the learner is ready for a clean restart and baseline capture.
