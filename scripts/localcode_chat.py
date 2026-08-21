#!/usr/bin/env python3
"""Interactive LocalCode chat: open a REPL in any project and ask it to work.

The repository is copied once into a disposable workspace that persists for
the whole session, so every request builds on the previous edits. Each request
runs the real bounded loop against the chosen backend while the terminal UI
streams events AND the model's live reasoning (thought_summary, or provider
reasoning summaries for the OpenAI Responses backend). The cumulative Git diff
is always one ``diff`` away and is applied to the original repository only
when you type ``apply``.

Commands inside the chat:
  help              show this help
  diff              print the cumulative Git diff for this session
  apply             apply the cumulative diff to the original repo (git apply --check first)
  status            show session state
  exit / quit       end the session (Ctrl-D also works)
  anything else     run the loop with your request

Examples:
  cd ~/projects/myapp
  PYTHONPATH=src .venv-mlx/bin/python scripts/localcode_chat.py --backend mlx

  PYTHONPATH=src python3.11 scripts/localcode_chat.py \
      --repo ~/projects/myapp --backend openai --model gpt-5.6-terra

  PYTHONPATH=src python3.11 scripts/localcode_chat.py \
      --backend openai-compatible --base-url https://openrouter.ai/api/v1 \
      --model provider/model
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time

from localcode.context import RetrievalContextCompiler, SimpleContextCompiler
from localcode.decisions import DecisionValidator
from localcode.engineering_registry import EngineeringToolRegistry, ProductionReviewRegistry
from localcode.loop import AgentLoop, CompletionRequirements, LoopBudgets
from localcode.thinking import ThinkingBackend
from localcode.tools import git_diff
from localcode.tui import TerminalEventStream, TerminalRenderer
from localcode.workspace import create_workspace


ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = ROOT / "benchmarks/micro_agent/tool_schemas.json"
MLX_MODEL_PATH = ROOT / "models/qwen25-coder-7b-instruct-4bit"
RUN_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{2,79}$")

HELP = """Commands:
  help              show this help
  diff              print the cumulative Git diff for this session
  apply             apply the cumulative diff to the original repo (after git apply --check)
  context           show the full context envelope the model saw on the last turn
  status            show session state, token usage and prompt-cache stats
  exit / quit       end the session (Ctrl-D also works)
  anything else     run the loop with your request"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", default=".", help="repository to work on (copied into a disposable workspace)")
    parser.add_argument("--backend", choices=("mlx", "openai", "openai-compatible"), default="mlx")
    parser.add_argument("--model", default=None, help="model ID for openai / openai-compatible backends")
    parser.add_argument("--base-url", default="https://api.openai.com/v1", help="base URL for openai-compatible")
    parser.add_argument("--api-key-env", default="OPENAI_API_KEY",
                        help="env var holding the API key for openai-compatible (e.g. DS_KEY)")
    parser.add_argument("--reasoning-effort", choices=("low", "medium", "high", "xhigh"), default="medium")
    parser.add_argument("--temperature", type=float, default=0.0,
                        help="sampling temperature for mlx and openai-compatible (raise to ~0.4 to break repetition loops)")
    parser.add_argument("--model-path", default=None, help="MLX model directory override for --backend mlx")
    parser.add_argument("--adapter-path", default=None, help="optional LoRA adapter directory for --backend mlx")
    parser.add_argument("--context", choices=("retrieval", "simple"), default="retrieval")
    parser.add_argument("--max-turns", type=int, default=20)
    parser.add_argument("--max-tool-calls", type=int, default=20)
    parser.add_argument("--max-wall-seconds", type=int, default=420)
    parser.add_argument("--max-context-chars", type=int, default=16_000,
                        help="context envelope budget sent to the model each turn")
    parser.add_argument("--strict", action="store_true", help="require a patch with passing tests to finish")
    parser.add_argument("--run-id", default=None, help="optional run ID (auto-generated otherwise)")
    args = parser.parse_args()

    repo = Path(args.repo).expanduser().resolve()
    if not repo.is_dir():
        raise SystemExit(f"repository does not exist: {repo}")
    run_id = args.run_id or f"m-chat-{time.strftime('%Y%m%d-%H%M%S')}"
    if RUN_ID.fullmatch(run_id) is None:
        raise SystemExit("run ID must contain 3-80 lowercase safe characters")

    if args.backend == "mlx" and Path(sys.prefix).resolve() != (ROOT / ".venv-mlx").resolve():
        raise SystemExit("--backend mlx must run with .venv-mlx/bin/python")
    if args.backend in ("openai", "openai-compatible") and not args.model:
        raise SystemExit("--model is required for openai and openai-compatible backends")
    if args.adapter_path is not None and args.backend != "mlx":
        raise SystemExit("--adapter-path is only valid with --backend mlx")

    run_dir = ROOT / "runs/tui" / run_id
    try:
        run_dir.mkdir(parents=True)
    except FileExistsError as exc:
        raise SystemExit(f"run directory already exists; use a fresh run ID: {run_dir}") from exc

    tool_document = json.loads(SCHEMAS.read_text(encoding="utf-8"))
    record = {
        "schema_version": 1,
        "run_id": run_id,
        "state": "running",
        "backend": args.backend,
        "model": args.model or (f"mlx:{Path(args.model_path).expanduser()}" if args.model_path else f"mlx:{MLX_MODEL_PATH}"),
        "repo": str(repo),
        "context_mode": args.context,
        "strict": args.strict,
        "turns": [],
        "error": None,
    }

    print(f"LocalCode chat — {args.backend} backend on {repo}")
    print(f"Session runs in a disposable copy; type `apply` to deliver edits to the real repo.")
    print(HELP)
    print()

    transcript: list[dict[str, str]] = []
    total_turns = 0
    try:
        with tempfile.TemporaryDirectory(prefix=f"localcode-chat-{run_id}-") as temporary:
            workspace = create_workspace(repo, Path(temporary) / "workspace", skip_symlinks=True)
            backend = _build_backend(args, tool_document)
            thinking = ThinkingBackend(backend, on_thought=_print_thought)
            validator = DecisionValidator.from_tool_document(tool_document)
            registry = EngineeringToolRegistry(workspace)
            review = ProductionReviewRegistry(registry)
            context = (
                RetrievalContextCompiler(workspace.root, max_files=5)
                if args.context == "retrieval"
                else SimpleContextCompiler()
            )
            completion = (
                CompletionRequirements(require_patch=True, require_passing_tests=True, require_test_execution=True)
                if args.strict
                else CompletionRequirements()
            )

            while True:
                try:
                    raw = input("you > ")
                except (EOFError, KeyboardInterrupt):
                    print("\nbye")
                    break
                request = raw.strip()
                if not request:
                    continue
                command = request.split()[0].lower()
                if command in ("exit", "quit"):
                    break
                if command == "help":
                    print(HELP)
                    continue
                if command == "diff":
                    print(git_diff(workspace.root).content or "(no changes yet)")
                    continue
                if command == "apply":
                    diff = git_diff(workspace.root).content
                    if not diff.strip():
                        print("(nothing to apply)")
                        continue
                    print(json.dumps(_apply_diff(repo, diff), indent=2, sort_keys=True))
                    continue
                if command == "status":
                    context_chars = len(thinking.last_context) if thinking.last_context else 0
                    print(
                        f"run_id={run_id} backend={args.backend} model={record['model']}\n"
                        f"repo={repo} context={args.context} strict={args.strict}\n"
                        f"requests={len(transcript)} total_loop_turns={total_turns}\n"
                        f"last_context_chars={context_chars} max_context_chars={args.max_context_chars}\n"
                        f"tokens: in={getattr(backend, 'input_tokens', None)} "
                        f"cache_hit={getattr(backend, 'cache_hit_tokens', None)} "
                        f"cache_miss={getattr(backend, 'cache_miss_tokens', None)} "
                        f"out={getattr(backend, 'generated_tokens', None)}"
                    )
                    continue
                if command == "context":
                    if not thinking.last_context:
                        print("(no context captured yet; run a request first)")
                        continue
                    print(f"context chars: {len(thinking.last_context)}")
                    print("--- full context envelope (what the model saw on the last turn) ---")
                    print(thinking.last_context)
                    continue

                issue = _compose_issue(transcript, request)
                stream = TerminalEventStream(TerminalRenderer(sys.stdout))
                stream.start(run_id=f"{run_id}-t{len(transcript)}", issue=request)
                started = time.monotonic()
                result = AgentLoop(
                    thinking,
                    validator,
                    review,
                    LoopBudgets(
                        max_turns=args.max_turns,
                        max_tool_calls=args.max_tool_calls,
                        max_invalid_actions=5,
                        max_identical_actions=1,
                        max_wall_seconds=args.max_wall_seconds,
                        max_context_chars=args.max_context_chars,
                        recover_repeated_actions=True,
                        # Chat mode is open-ended: the model must be free to
                        # search, read, diff, and edit in any order. The rigid
                        # search→read→edit→test phase policy strangles
                        # explanation and exploration sessions (D-053).
                        phase_tool_policy=False,
                        auto_test_after_edit=True,
                    ),
                    clock=lambda: time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                    monotonic=time.monotonic,
                    completion_requirements=completion,
                    observer=stream,
                    context_compiler=context,
                ).run(run_id=f"{run_id}-t{len(transcript)}", issue=issue)
                wall_seconds = round(time.monotonic() - started, 6)
                diff = git_diff(workspace.root).content
                tests = [
                    int(observation.metadata_dict()["exit_code"])
                    for observation in result.observations
                    if "exit_code" in observation.metadata_dict()
                ]
                solved = (
                    result.termination_reason.value == "final_answer"
                    and bool(diff.strip())
                    and bool(tests)
                    and tests[-1] == 0
                )
                stream.finish(result, final_diff=diff)
                total_turns += result.turns_used
                record["turns"].append(
                    {
                        "request": request,
                        "termination_reason": result.termination_reason.value,
                        "solved": bool(solved),
                        "turns_used": result.turns_used,
                        "tool_calls_used": result.tool_calls_used,
                        "invalid_actions_used": result.invalid_actions_used,
                        "tests_executed": tests,
                        "wall_seconds": wall_seconds,
                        "diff_changed_lines": _changed_lines(diff),
                    }
                )
                _write(run_dir / "run.json", record)
                transcript.append(
                    {
                        "user": request,
                        "result": (
                            f"{result.termination_reason.value} in {result.turns_used} turns; "
                            f"{_changed_lines(diff)} changed lines"
                        ),
                    }
                )
                print()
                if (
                    result.termination_reason.value
                    in ("invalid_action_exhaustion", "tool_exhaustion", "turn_exhaustion")
                    and result.tool_calls_used > 0
                ):
                    print("  (run stopped before a final answer; here is the evidence it gathered)")
                    for observation in result.observations[-3:]:
                        preview = " ".join(observation.content.split())[:400]
                        if preview:
                            print(f"  · {preview}")
                    print()
                if (
                    result.termination_reason.value == "invalid_action_exhaustion"
                    and result.tool_calls_used <= 1
                ):
                    print(
                        "  💡 The model got stuck repeating an action (greedy decoding). "
                        "Retry with `--temperature 0.4`, or use a stronger BYOK model "
                        "(`--backend openai --model <id>`)."
                    )
                print(f"[done] solved={solved} {result.termination_reason.value} "
                      f"({result.turns_used} turns, {result.tool_calls_used} tools, {wall_seconds:.1f}s)")
                usage_parts = []
                input_tokens = getattr(backend, "input_tokens", None)
                output_tokens = getattr(backend, "generated_tokens", None)
                cache_hit = getattr(backend, "cache_hit_tokens", None)
                cache_miss = getattr(backend, "cache_miss_tokens", None)
                if isinstance(input_tokens, int):
                    cache_text = f"" if not isinstance(cache_hit, int) else f" (cache hit {cache_hit})"
                    usage_parts.append(f"in {input_tokens}{cache_text}")
                if isinstance(output_tokens, int):
                    usage_parts.append(f"out {output_tokens}")
                if usage_parts:
                    print("tokens: " + " · ".join(usage_parts))
                if diff.strip():
                    print(f"  ⚠️  Changes exist in the DISPOSABLE COPY only — {repo} is untouched so far.")
                    print(f"      Type `apply` to write them to {repo} (unstaged), or `diff` to review first.")
                print(f"Type `diff` to review changes, `apply` to deliver them to {repo}, "
                      f"`context` to see the last context, or keep asking.")
                print()
    except Exception as exc:
        record.update(state="failed", error={"type": type(exc).__name__, "message": str(exc)})
        _write(run_dir / "run.json", record)
        print(json.dumps(record, indent=2, sort_keys=True))
        return 2

    record.update(state="measured", requests=len(transcript), total_loop_turns=total_turns)
    _write(run_dir / "run.json", record)
    print(f"\nSession summary: {len(transcript)} requests, {total_turns} loop turns.")
    print(f"Evidence: {run_dir}")
    return 0


def _print_thought(thought: str, request) -> None:
    compact = " ".join(thought.split())
    print(f"  💭 {compact[:400]}{'…' if len(compact) > 400 else ''}")


def _compose_issue(transcript: list[dict[str, str]], request: str) -> str:
    if not transcript:
        return request
    lines = [
        "Previous LocalCode session on the same workspace (edits are already applied):"
    ]
    for entry in transcript[-6:]:
        lines.append(f"- USER asked: {entry['user'][:200]}")
        lines.append(f"  LOCALCODE: {entry['result'][:200]}")
    lines.append(f"Current request: {request}")
    return "\n".join(lines)


def _build_backend(args: argparse.Namespace, tool_document: dict) -> object:
    if args.backend == "mlx":
        from localcode.backends.mlx_loop import MlxLoopBackend

        model_path = Path(args.model_path).expanduser() if args.model_path else MLX_MODEL_PATH
        adapter_path = Path(args.adapter_path).expanduser() if args.adapter_path else None
        return MlxLoopBackend(
            model_path=model_path,
            adapter_path=adapter_path,
            tool_document=tool_document,
            max_output_tokens=768,
            temperature=args.temperature,
        )
    if args.backend == "openai":
        from localcode.backends.openai_responses import OpenAIResponsesLoopBackend

        return OpenAIResponsesLoopBackend(
            model=args.model,
            tool_document=tool_document,
            reasoning_effort=args.reasoning_effort,
            allow_tool_subsets=True,
        )
    from localcode.backends.openai_chat import OpenAIChatLoopBackend

    return OpenAIChatLoopBackend(
        model=args.model,
        tool_document=tool_document,
        base_url=args.base_url,
        api_key_env=args.api_key_env,
        temperature=args.temperature,
        allow_tool_subsets=True,
    )


def _apply_diff(repo: Path, diff: str) -> dict[str, object]:
    if not diff.strip():
        return {"applied": False, "reason": "no diff to apply"}
    check = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--is-inside-work-tree"],
        capture_output=True,
        text=True,
    )
    if check.returncode != 0:
        return {"applied": False, "reason": "original repository is not a Git worktree; refusing to apply"}
    probe = subprocess.run(
        ["git", "-C", str(repo), "apply", "--check", "-"],
        input=diff,
        capture_output=True,
        text=True,
    )
    if probe.returncode != 0:
        return {"applied": False, "reason": "git apply --check failed", "detail": probe.stderr.strip()[:500]}
    result = subprocess.run(
        ["git", "-C", str(repo), "apply", "-"],
        input=diff,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return {"applied": False, "reason": "git apply failed", "detail": result.stderr.strip()[:500]}
    return {"applied": True, "reason": "git apply succeeded (unstaged)"}


def _changed_lines(diff: str) -> int:
    return sum(1 for line in diff.splitlines() if line.startswith(("+", "-")))


def _write(path: Path, record: dict) -> None:
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


if __name__ == "__main__":
    raise SystemExit(main())
