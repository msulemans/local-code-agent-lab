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

## The local backend bridge

`src/localcode/backends/ollama.py` implements the controller's `ModelBackend`
protocol without owning agent behavior. It sends the issue and the same four
tool schemas to the loopback-only Ollama transport with deterministic sampling.

If Ollama returns exactly one well-formed native tool proposal, the adapter
converts only the transport shape into protocol-v1 JSON. It preserves the tool
name and arguments exactly; an unknown tool remains unknown and invalid
arguments remain invalid. Multiple or malformed tool calls are not rescued.
Hidden model thinking is never copied into the action envelope.

The adapter sets `keep_alive` to zero for the bounded smoke path, so Ollama is
asked to unload the model after the response. Fake-client tests exercise this
bridge without loading any model.

## The real-smoke preflight

`src/localcode/preflight.py` parses three pieces of baseline evidence before
the real model is reachable:

1. `sysctl vm.swapusage` must report zero used swap;
2. `memory_pressure -Q` must provide a parseable free-memory percentage; and
3. Ollama's process list must contain no loaded model.

`src/localcode/smoke.py` performs this preflight before constructing the
backend and controller. Its fake-client tests assert that retained swap and a
loaded model both result in zero chat payloads. The clean fake case permits
exactly one backend request and one read-only tool result.

The registered command is `scripts/smoke_one_turn_ollama.py`, but it must not
be run merely because it exists. The learner must first choose a clean restart
and capture the required unloaded-host baseline.

## The smoke evidence recorder

`src/localcode/smoke_records.py` reserves one unique ignored directory under
`runs/one-turn-smoke/` before preflight. The run ID is restricted to a safe
lowercase alphabet, and an existing directory is never reused.

The recorder enforces explicit transitions:

```text
created -> blocked_preflight
created -> baseline_accepted -> backend_error
                             -> completed
                             -> completed_without_tool_result
```

It writes `run.json.tmp` first and atomically replaces `run.json`, preventing a
partially written JSON document from becoming the official record. Events must
belong to the same run and use contiguous sequence numbers from zero. CLI tests
exercise preflight failure, backend failure after baseline acceptance, rejected
action, successful tool result, and duplicate run refusal with fake dependencies.

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

Before parsing, it also rejects responses above 16,384 characters. During
parsing, it rejects duplicate JSON fields at any depth. Standard JSON parsers
often keep only the last duplicate value, which would make an ambiguous model
response appear authoritative.

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

After the first Milestone 008 retrieval slice, the current project suite is
`Ran 140 tests`. In the Codex sandbox it passes with the known nested macOS
sandbox canary skips; in normal Terminal, those canaries should execute.

## Read the implementation in this order

1. `configs/action_protocol_v1.json` — the versioned outer contract.
2. `benchmarks/model_compatibility/tool_schemas.json` — each tool's arguments.
3. `src/localcode/actions.py` — parsing and strict validation.
4. `src/localcode/registry.py` — the exact name-to-function map.
5. `src/localcode/controller.py` — one backend call and at most one tool call.
6. `src/localcode/backends/ollama.py` — local inference transport adapter.
7. `tests/unit/test_one_turn_controller.py` — executable controller claims.
8. `tests/unit/test_ollama_backend.py` — executable backend-boundary claims.
9. `src/localcode/preflight.py` — the clean-host evidence gate.
10. `src/localcode/smoke.py` — preflight followed by exactly one real-model turn.
11. `tests/unit/test_smoke.py` — proof that blocked baselines cannot infer.
12. `src/localcode/smoke_records.py` — immutable-directory run evidence.
13. `tests/unit/test_smoke_cli.py` — executable command-level outcome claims.

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
The offline one-turn controller, bounded loop, and first guarded edit/test path
are implemented, and the current project suite contains 140 unit tests. Qwen3.5
9B is downloaded and verified but must not be run until the learner chooses a
restart and a clean unloaded-host baseline is captured. Do not weaken that
gate. Do not run Qwen, SWE-bench, or download another model.

When helping me learn, explain one concept at a time, ask me to predict the
result before revealing it, and ground every claim in a named file or test.
Allowed work now: inspect the protocol, run fake-backend demos, expand the
Milestone 007 micro suite, or improve lessons without model inference.
```

## Remaining gate

The fake backend proves our controller logic. It does not prove that Qwen3.5
emits usable actions on this Mac. That bounded smoke test remains pending until
the learner is ready for a clean restart and baseline capture.
