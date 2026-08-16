# Milestone 006 lesson — a bounded read-only agent loop

## Outcome

LocalCode can now perform multiple read-only turns with a fake backend. Each
turn receives bounded JSON context, proposes either one tool or one final
answer, consumes explicit budgets, and emits immutable events.

This remains offline engineering evidence. Qwen3.5 has not run. Milestone 007
has since added a guarded edit/test path, but this lesson describes the
read-only gate that made those later capabilities safe to add.

## The loop

```text
issue + bounded history + remaining budgets
                    |
                    v
             backend decision
               /          \
       read-only tool    final answer
             |               |
       observation            v
             +----------> completed
```

The implementation uses `for turn_index in range(max_turns)`. There is no
unbounded `while True`. A model response cannot create more turns, tool calls,
or time than trusted Python code permits.

## Two decision types

`src/localcode/decisions.py` defines a strict versioned envelope. A decision is
either:

```json
{
  "kind": "tool",
  "tool": "search_code",
  "arguments": {"query": "parse_value"}
}
```

or:

```json
{
  "kind": "final",
  "answer": "The parser is defined in src/tiny_parser.py."
}
```

Tool decisions reuse the existing `ActionValidator`, so the multi-turn loop
does not create a weaker tool boundary. Final answers are bounded to 4,000
characters and cannot contain extra fields.

## Budgets

`LoopBudgets` controls:

- total model turns;
- invalid actions;
- executed tool calls;
- identical action executions;
- wall-clock seconds; and
- context characters.

Every event contains the remaining integer budgets. The model sees the same
remaining-budget snapshot in its request context.

## Repeated actions

Each validated tool name and its normalized arguments become a canonical JSON
signature. If that exact signature has already executed the permitted number
of times, LocalCode stops before executing it again. This catches loops such as
searching for the same text forever.

## Termination reasons

The loop returns one explicit reason:

| Reason | Meaning |
|---|---|
| `final_answer` | The model returned a valid bounded answer |
| `invalid_action_exhaustion` | Too many malformed or unknown decisions |
| `tool_exhaustion` | A further tool was proposed after the tool budget |
| `repeated_action` | An identical normalized action would repeat |
| `backend_error` | The local inference backend reported a bounded failure |
| `wall_clock_timeout` | The registered wall time expired |
| `turn_exhaustion` | All model turns were consumed without a final answer |

## Context construction

Issue text and observation history are serialized as JSON data with an explicit
untrusted-data instruction. Oldest observations are dropped first when the
character budget is exceeded, then the issue is truncated if necessary. The
payload always records whether truncation occurred.

This is a deterministic character-budget implementation. Token-aware context
allocation and retrieval ranking belong to later retrieval work.

## Run the offline demonstration

```bash
PYTHONPATH=src python3.11 scripts/demo_read_only_loop.py
```

Expected high-level result:

```text
search_code -> observation
read_file   -> observation
final       -> final_answer
```

## Executable gate

```bash
PYTHONPATH=src python3.11 -m unittest tests.unit.test_decisions tests.unit.test_loop -v
```

The focused historical gate contains 12 tests. After the first Milestone 008
retrieval slice, the current complete offline suite contains 140 tests. Inside
the Codex sandbox, nested macOS sandbox canaries may skip; in normal Terminal,
those canaries should execute.

## What Milestone 007 added next

Milestone 007 did not reuse a general terminal as an editing shortcut. It added
a strict patch format, disposable workspace, named test commands, a macOS
sandbox, timeouts, output limits, and the first deterministic repair task. See
`docs/MILESTONE_007_LESSON.md` for the current engineering boundary.
