#!/usr/bin/env python3
"""Interactive LocalCode CLI: fix any repository with a local or BYOK model.

Point LocalCode at a real repository and an issue. The repository is copied
into a disposable workspace (the safety boundary never leaves it), the real
bounded loop runs against the chosen backend while the terminal UI streams
every event, and the final Git diff is written for review. With ``--apply`` the
diff is applied to the original repository after ``git apply --check`` passes.

Examples:
  PYTHONPATH=src .venv-mlx/bin/python scripts/localcode_cli.py \
      --repo ~/projects/demo-repo --issue "fix the port fallback" --backend mlx

  PYTHONPATH=src .venv-mlx/bin/python scripts/localcode_cli.py \
      --repo ~/projects/demo-repo --issue-file ./issue.md --adapter-path adapters/m020-qwen7b-protocol-diagnostic-v1

  PYTHONPATH=src python3.11 scripts/localcode_cli.py \
      --repo ~/projects/demo-repo --issue "fix the discount boundary" \
      --backend openai --model gpt-5.6-terra --apply

  PYTHONPATH=src python3.11 scripts/localcode_cli.py \
      --repo . --issue "..." \
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
from localcode.tools import git_diff
from localcode.tui import TerminalEventStream, TerminalRenderer
from localcode.workspace import create_workspace


ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = ROOT / "benchmarks/micro_agent/tool_schemas.json"
MLX_MODEL_PATH = ROOT / "models/qwen25-coder-7b-instruct-4bit"
RUN_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{2,79}$")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", required=True, help="repository to fix (copied into a disposable workspace)")
    parser.add_argument("--issue", default=None, help="issue text; defaults to the repo's ISSUE.md")
    parser.add_argument("--issue-file", default=None, help="path to a file containing the issue text")
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
    parser.add_argument("--max-turns", type=int, default=10)
    parser.add_argument("--max-tool-calls", type=int, default=10)
    parser.add_argument("--max-wall-seconds", type=int, default=300)
    parser.add_argument("--no-test-gate", action="store_true", help="do not require passing tests to finish")
    parser.add_argument("--output-diff", default=None, help="also write the final diff to this file")
    parser.add_argument("--apply", action="store_true", help="apply the final diff to the original repo after review")
    parser.add_argument("--run-id", default=None, help="optional run ID (auto-generated otherwise)")
    args = parser.parse_args()

    repo = Path(args.repo).expanduser().resolve()
    if not repo.is_dir():
        raise SystemExit(f"repository does not exist: {repo}")

    issue = _issue_text(args, repo)
    run_id = args.run_id or f"m-tui-{time.strftime('%Y%m%d-%H%M%S')}"
    if RUN_ID.fullmatch(run_id) is None:
        raise SystemExit("run ID must contain 3-80 lowercase safe characters")

    run_dir = ROOT / "runs/tui" / run_id
    try:
        run_dir.mkdir(parents=True)
    except FileExistsError as exc:
        raise SystemExit(f"run directory already exists; use a fresh run ID: {run_dir}") from exc

    if args.backend == "mlx" and Path(sys.prefix).resolve() != (ROOT / ".venv-mlx").resolve():
        raise SystemExit("--backend mlx must run with .venv-mlx/bin/python")
    if args.backend in ("openai", "openai-compatible") and not args.model:
        raise SystemExit("--model is required for openai and openai-compatible backends")
    if args.adapter_path is not None and args.backend != "mlx":
        raise SystemExit("--adapter-path is only valid with --backend mlx")

    tool_document = json.loads(SCHEMAS.read_text(encoding="utf-8"))
    model_label = (
        args.model
        if args.model
        else (f"mlx:{Path(args.model_path).expanduser()}" if args.model_path else f"mlx:{MLX_MODEL_PATH}")
    )
    record = {
        "schema_version": 1,
        "run_id": run_id,
        "state": "running",
        "backend": args.backend,
        "model": model_label,
        "repo": str(repo),
        "issue_chars": len(issue),
        "context_mode": args.context,
        "solved": None,
        "termination_reason": None,
        "turns_used": None,
        "tool_calls_used": None,
        "invalid_actions_used": None,
        "wall_seconds": None,
        "generated_tokens": None,
        "apply": args.apply,
        "error": None,
    }
    _write(run_dir / "run.json", record)

    try:
        with tempfile.TemporaryDirectory(prefix=f"localcode-cli-{run_id}-") as temporary:
            workspace = create_workspace(repo, Path(temporary) / "workspace", skip_symlinks=True)
            backend = _build_backend(args, tool_document)
            validator = DecisionValidator.from_tool_document(tool_document)
            registry = EngineeringToolRegistry(workspace)
            review = ProductionReviewRegistry(registry)
            context = (
                RetrievalContextCompiler(workspace.root, max_files=5)
                if args.context == "retrieval"
                else SimpleContextCompiler()
            )
            renderer = TerminalRenderer(sys.stdout)
            stream = TerminalEventStream(renderer)
            stream.start(run_id=run_id, issue=issue)
            started = time.monotonic()
            result = AgentLoop(
                backend,
                validator,
                review,
                LoopBudgets(
                    max_turns=args.max_turns,
                    max_tool_calls=args.max_tool_calls,
                    max_invalid_actions=3,
                    max_identical_actions=1,
                    max_wall_seconds=args.max_wall_seconds,
                    max_context_chars=12_000,
                    recover_repeated_actions=True,
                    phase_tool_policy=True,
                    auto_test_after_edit=True,
                ),
                clock=lambda: time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                monotonic=time.monotonic,
                completion_requirements=CompletionRequirements(
                    require_patch=True,
                    require_passing_tests=not args.no_test_gate,
                    require_test_execution=True,
                ),
                observer=stream,
                context_compiler=context,
            ).run(run_id=run_id, issue=issue)
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
            print()
            print("=" * 72)
            print(f"Solved: {solved}")
            print(f"Termination: {result.termination_reason.value}")
            print(f"Turns: {result.turns_used}  Tools: {result.tool_calls_used}  Invalid: {result.invalid_actions_used}")
            print(f"Tests executed (exit codes): {tests}")
            print(f"Wall seconds: {wall_seconds}")

            diff_file = run_dir / "final.diff"
            if diff.strip():
                diff_file.write_text(diff, encoding="utf-8")
                print(f"Diff written: {diff_file}")
                if args.output_diff:
                    Path(args.output_diff).expanduser().write_text(diff, encoding="utf-8")
                    print(f"Diff copied to: {args.output_diff}")
            else:
                diff_file.write_text("", encoding="utf-8")
                print("Diff: (empty)")

            apply_status = None
            if args.apply and diff.strip():
                apply_status = _apply_diff(repo, diff)

            record.update(
                state="measured",
                solved=bool(solved),
                termination_reason=result.termination_reason.value,
                turns_used=result.turns_used,
                tool_calls_used=result.tool_calls_used,
                invalid_actions_used=result.invalid_actions_used,
                wall_seconds=wall_seconds,
                generated_tokens=getattr(backend, "generated_tokens", None),
                apply_status=apply_status,
            )
            _write(run_dir / "run.json", record)
            print(json.dumps(_summary(record), indent=2, sort_keys=True))
            return 0
    except Exception as exc:
        record.update(state="failed", error={"type": type(exc).__name__, "message": str(exc)})
        _write(run_dir / "run.json", record)
        print(json.dumps(_summary(record), indent=2, sort_keys=True))
        return 2


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


def _issue_text(args: argparse.Namespace, repo: Path) -> str:
    if args.issue_file:
        path = Path(args.issue_file).expanduser()
        if not path.is_file():
            raise SystemExit(f"issue file does not exist: {path}")
        text = path.read_text(encoding="utf-8")
    elif args.issue:
        text = args.issue
    else:
        candidate = repo / "ISSUE.md"
        if not candidate.is_file():
            raise SystemExit("provide --issue or --issue-file, or a repo containing ISSUE.md")
        text = candidate.read_text(encoding="utf-8")
    if not text.strip():
        raise SystemExit("issue text must not be empty")
    return text.strip()


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
    return {"applied": True, "reason": "git apply succeeded"}


def _write(path: Path, record: dict) -> None:
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _summary(record: dict) -> dict:
    return {
        "artifact": str(ROOT / "runs/tui" / record["run_id"]),
        "run_id": record["run_id"],
        "state": record["state"],
        "backend": record["backend"],
        "model": record["model"],
        "repo": record["repo"],
        "context_mode": record["context_mode"],
        "solved": record["solved"],
        "termination_reason": record["termination_reason"],
        "generated_tokens": record["generated_tokens"],
        "wall_seconds": record["wall_seconds"],
        "error": record["error"],
    }


if __name__ == "__main__":
    raise SystemExit(main())
