"""File-backed issue and official SWE-bench evaluator adapters.

The core real-benchmark runner stays dependency-free.  These adapters are the
boundary where a downloaded dataset and the optional official ``swebench``
package enter the process.
"""

from __future__ import annotations

import json
import platform
from pathlib import Path
import subprocess
import tempfile
import time
from typing import Any

from .real_benchmark import (
    EvaluationInstanceResult,
    Evaluator,
    PatchAttempt,
    RealBenchmarkConfiguration,
    RealBenchmarkError,
    RealBenchmarkInstance,
    RealBenchmarkIssue,
    RealBenchmarkManifest,
)


class LocalCodePatchProducer:
    """Run the bounded LocalCode loop against a disposable real repository.

    This is intentionally an adapter, not part of the manifest/evaluator
    contract.  The official SWE-bench harness remains the authority for
    resolved status; local test output is only loop context and diagnostics.
    """

    def __init__(
        self,
        *,
        model: str,
        tool_document: dict[str, Any],
        only_instance_id: str | None = None,
        context_tokens: int = 32_768,
        max_output_tokens: int = 2_048,
        max_turns: int = 12,
        max_tool_calls: int = 12,
        max_context_chars: int = 32_000,
        allow_retained_swap: bool = False,
        keep_alive: int = 300,
    ) -> None:
        self.model = model
        self.tool_document = tool_document
        self.only_instance_id = only_instance_id
        self.context_tokens = context_tokens
        self.max_output_tokens = max_output_tokens
        self.max_turns = max_turns
        self.max_tool_calls = max_tool_calls
        self.max_context_chars = max_context_chars
        self.allow_retained_swap = allow_retained_swap
        self.keep_alive = keep_alive

    def produce(self, configuration: RealBenchmarkConfiguration, issue: RealBenchmarkIssue):
        from .backends.ollama_loop import OllamaLoopBackend
        from .compatibility import OllamaClient
        from .context import RetrievalContextCompiler, SimpleContextCompiler
        from .decisions import DecisionValidator
        from .engineering_registry import EngineeringToolRegistry
        from .engineering_smoke import ResourceGuardedLoopBackend
        from .loop import AgentLoop, CompletionRequirements, LoopBudgets
        from .preflight import validate_smoke_baseline
        from .smoke import _run_host_command
        from .tools import git_diff
        from .workspace import create_workspace

        if self.only_instance_id is not None and issue.instance_id != self.only_instance_id:
            return _empty_attempt(issue, self.model, "producer scope excludes this instance")
        started = time.monotonic()
        client = OllamaClient()
        baseline = validate_smoke_baseline(
            swapusage_output=_run_host_command(("sysctl", "vm.swapusage")),
            memory_pressure_output=_run_host_command(("memory_pressure", "-Q")),
            running_models=client.running_models(),
            allow_retained_swap=self.allow_retained_swap,
        )
        with tempfile.TemporaryDirectory(prefix="localcode-real-agent-") as temporary:
            root = Path(temporary)
            source = root / "source"
            _clone_at_commit(issue.repository, issue.base_commit, source)
            workspace = create_workspace(
                source,
                root / "workspace",
                max_files=12_000,
                max_bytes=512 * 1_024 * 1_024,
                # SWE-bench repositories contain non-source symlinks in
                # docs/fixtures. Never follow them into the agent workspace.
                skip_symlinks=True,
            )
            validator = DecisionValidator.from_tool_document(self.tool_document)
            backend = ResourceGuardedLoopBackend(
                OllamaLoopBackend(
                    model=self.model,
                    tool_document=self.tool_document,
                    client=client,
                    context_tokens=self.context_tokens,
                    max_output_tokens=self.max_output_tokens,
                    allow_tool_subsets=True,
                    keep_alive=self.keep_alive,
                ),
                baseline=baseline,
                command_runner=_run_host_command,
                observer=lambda _snapshot: None,
            )
            registry = EngineeringToolRegistry(workspace)
            if configuration.configuration_id == "A2":
                compiler = RetrievalContextCompiler(workspace.root, max_files=6)
            else:
                compiler = SimpleContextCompiler()
            result = AgentLoop(
                backend,
                validator,
                registry,
                LoopBudgets(
                    max_turns=self.max_turns,
                    max_tool_calls=self.max_tool_calls,
                    max_invalid_actions=4,
                    # Real models may repeat a discovery query after its first
                    # bounded observation; permit one repeat before stopping.
                    max_identical_actions=2,
                    recover_repeated_actions=True,
                    phase_tool_policy=True,
                    max_wall_seconds=600,
                    max_context_chars=self.max_context_chars,
                ),
                clock=lambda: time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                monotonic=time.monotonic,
                completion_requirements=CompletionRequirements(
                    require_patch=True,
                    # The official evaluator, not the host, owns real test truth.
                    require_passing_tests=False,
                ),
                context_compiler=compiler,
            ).run(run_id=f"real-{issue.instance_id}", issue=issue.problem_statement)
            diff = git_diff(workspace.root)
        patch = diff.content if not diff.truncated else ""
        produced = bool(patch) and patch.lstrip().startswith("diff --git ")
        termination = result.termination_reason.value
        return PatchAttempt(
            instance_id=issue.instance_id,
            model_name_or_path=self.model,
            patch=patch if produced else "",
            status="produced" if produced else "no_patch",
            failure_category=None if produced else "LOOP_CONTROL",
            reason=None if produced else f"agent terminated with {termination}",
            tool_calls=result.tool_calls_used,
            wall_seconds=round(time.monotonic() - started, 6),
        )


def _clone_at_commit(repository: str, commit: str, destination: Path) -> None:
    try:
        subprocess.run(
            ["git", "clone", "--quiet", f"https://github.com/{repository}.git", str(destination)],
            check=True,
            capture_output=True,
            text=True,
            timeout=300,
        )
        subprocess.run(
            ["git", "-C", str(destination), "checkout", "--quiet", "--detach", commit],
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RealBenchmarkError(f"could not clone {repository} at {commit}") from exc


def _empty_attempt(issue: RealBenchmarkIssue, model: str, reason: str):
    from .real_benchmark import PatchAttempt

    return PatchAttempt(
        instance_id=issue.instance_id,
        model_name_or_path=model,
        patch="",
        status="no_patch",
        failure_category="LOOP_CONTROL",
        reason=reason,
    )


class JsonDatasetIssueResolver:
    """Resolve manifest rows from a local SWE-bench JSON or JSONL snapshot."""

    def __init__(self, dataset_path: str | Path) -> None:
        self.dataset_path = Path(dataset_path)
        self._rows = _load_rows(self.dataset_path)
        self._by_id = {}
        for row in self._rows:
            instance_id = row.get("instance_id")
            if not isinstance(instance_id, str) or instance_id in self._by_id:
                raise RealBenchmarkError("dataset snapshot has invalid or duplicate instance_id")
            self._by_id[instance_id] = row

    def resolve(self, instance: RealBenchmarkInstance) -> RealBenchmarkIssue:
        row = self._by_id.get(instance.instance_id)
        if row is None:
            raise RealBenchmarkError(f"dataset snapshot is missing {instance.instance_id}")
        repository = row.get("repo", row.get("repository"))
        base_commit = row.get("base_commit")
        problem_statement = row.get("problem_statement")
        if not all(isinstance(value, str) and value for value in (repository, base_commit, problem_statement)):
            raise RealBenchmarkError(f"dataset row is missing issue fields for {instance.instance_id}")
        return RealBenchmarkIssue(
            instance_id=instance.instance_id,
            repository=repository,
            base_commit=base_commit,
            problem_statement=problem_statement,
        )


class DatasetControlPatchProducer:
    """Produce an explicit gold or empty control from a local dataset snapshot.

    This adapter is for Milestone 009 controls only.  The gold patch is never
    exposed through ``JsonDatasetIssueResolver`` and must not be passed to an
    agent producer.
    """

    def __init__(
        self,
        dataset_path: str | Path,
        *,
        mode: str,
        only_instance_id: str | None = None,
    ) -> None:
        if mode not in {"gold", "empty"}:
            raise ValueError("control mode must be 'gold' or 'empty'")
        self.mode = mode
        self.only_instance_id = only_instance_id
        self._rows = {
            row["instance_id"]: row for row in _load_rows(Path(dataset_path))
        }

    def produce(self, configuration: RealBenchmarkConfiguration, issue: RealBenchmarkIssue):
        from .real_benchmark import PatchAttempt

        row = self._rows.get(issue.instance_id)
        if row is None:
            raise RealBenchmarkError(f"dataset snapshot is missing {issue.instance_id}")
        if self.only_instance_id is not None and issue.instance_id != self.only_instance_id:
            return PatchAttempt(
                instance_id=issue.instance_id,
                model_name_or_path="localcode/empty-control",
                patch="",
                status="no_patch",
                failure_category="LOOP_CONTROL",
                reason="control scope excludes this instance",
            )
        if self.mode == "gold":
            patch = row.get("patch")
            if not isinstance(patch, str) or not patch:
                raise RealBenchmarkError(f"gold patch is missing for {issue.instance_id}")
            return PatchAttempt(
                instance_id=issue.instance_id,
                model_name_or_path="localcode/gold-control",
                patch=patch,
                status="produced",
                failure_category=None,
                reason="official gold control; never an agent prediction",
            )
        return PatchAttempt(
            instance_id=issue.instance_id,
            model_name_or_path="localcode/empty-control",
            patch="",
            status="no_patch",
            failure_category="LOOP_CONTROL",
            reason="empty control: no patch supplied",
        )


def _default_evaluator_namespace() -> str:
    """Build locally when prebuilt SWE-bench images do not match Apple ARM."""

    if platform.system() == "Darwin" and platform.machine().lower() in {"arm64", "aarch64"}:
        return "none"
    return "swebench"


class OfficialSwebenchEvaluator(Evaluator):
    """Run the official SWE-bench harness and read its instance results."""

    def __init__(
        self,
        *,
        dataset_name: str,
        split: str = "test",
        evaluation_root: str | Path = "evaluation_results",
        python_executable: str = "python3.11",
        max_workers: int = 1,
        cache_level: str = "base",
        clean: bool = False,
        namespace: str | None = None,
    ) -> None:
        if not dataset_name or not isinstance(dataset_name, str):
            raise ValueError("dataset_name must be a non-empty string")
        if not isinstance(max_workers, int) or isinstance(max_workers, bool) or max_workers < 1:
            raise ValueError("max_workers must be a positive integer")
        if cache_level not in {"none", "base", "env", "instance"}:
            raise ValueError("cache_level must be one of none, base, env, instance")
        if namespace is not None and (
            not isinstance(namespace, str)
            or not namespace
            or any(character.isspace() for character in namespace)
        ):
            raise ValueError("namespace must be a non-empty value without whitespace")
        self.dataset_name = dataset_name
        self.split = split
        self.evaluation_root = Path(evaluation_root)
        self.python_executable = python_executable
        self.max_workers = max_workers
        self.cache_level = cache_level
        self.clean = clean
        self.namespace = namespace if namespace is not None else _default_evaluator_namespace()

    def evaluate(
        self,
        manifest: RealBenchmarkManifest,
        configuration: RealBenchmarkConfiguration,
        predictions_path: Path,
        output_directory: Path,
    ) -> tuple[EvaluationInstanceResult, ...]:
        run_id = f"localcode-{configuration.configuration_id.lower()}-{output_directory.parent.name}"
        command = [
            self.python_executable,
            "-m",
            "swebench.harness.run_evaluation",
            "--dataset_name",
            self.dataset_name,
            "--split",
            self.split,
            "--predictions_path",
            str(predictions_path),
            "--instance_ids",
            *(instance.instance_id for instance in manifest.instances),
            "--max_workers",
            str(self.max_workers),
            "--run_id",
            run_id,
            "--cache_level",
            self.cache_level,
            "--clean",
            "True" if self.clean else "False",
            "--namespace",
            self.namespace,
        ]
        try:
            completed = subprocess.run(
                command,
                cwd=self.evaluation_root,
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError as exc:
            raise RealBenchmarkError("could not start the official SWE-bench evaluator") from exc
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).strip()[-2000:]
            raise RealBenchmarkError(
                f"official SWE-bench evaluator failed with exit {completed.returncode}: {detail}"
            )
        return _load_evaluation_results(
            self.evaluation_root,
            run_id,
            predictions_path,
            manifest,
        )


def _load_rows(path: Path) -> tuple[dict[str, Any], ...]:
    try:
        if path.suffix == ".jsonl":
            values = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        elif path.suffix == ".json":
            values = json.loads(path.read_text(encoding="utf-8"))
        else:
            raise RealBenchmarkError("dataset snapshot must be .json or .jsonl")
    except (OSError, json.JSONDecodeError) as exc:
        raise RealBenchmarkError(f"cannot load dataset snapshot: {path}") from exc
    if not isinstance(values, list) or not all(isinstance(row, dict) for row in values):
        raise RealBenchmarkError("dataset snapshot must contain a list of objects")
    return tuple(values)


def _load_evaluation_results(
    evaluation_root: Path,
    run_id: str,
    predictions_path: Path,
    manifest: RealBenchmarkManifest,
) -> tuple[EvaluationInstanceResult, ...]:
    expected = {instance.instance_id for instance in manifest.instances}
    try:
        predictions = [
            json.loads(line)
            for line in predictions_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except (OSError, json.JSONDecodeError) as exc:
        raise RealBenchmarkError(f"cannot read predictions for evaluator results: {predictions_path}") from exc
    rows: list[EvaluationInstanceResult] = []
    for prediction in predictions:
        instance_id = prediction.get("instance_id")
        if not isinstance(instance_id, str) or instance_id not in expected:
            continue
        if not prediction.get("model_patch"):
            rows.append(
                EvaluationInstanceResult(
                    instance_id=instance_id,
                    resolved=False,
                    status="unresolved",
                    reason="empty patch control",
                )
            )
            continue
        model_name = prediction.get("model_name_or_path")
        if not isinstance(model_name, str) or not model_name:
            raise RealBenchmarkError(f"prediction model name is invalid for {instance_id}")
        report_path = (
            evaluation_root
            / "logs"
            / "run_evaluation"
            / run_id
            / model_name.replace("/", "__")
            / instance_id
            / "report.json"
        )
        if not report_path.is_file():
            rows.append(
                EvaluationInstanceResult(
                    instance_id=instance_id,
                    resolved=False,
                    status="environment_error",
                    reason=f"official evaluator did not write {report_path}",
                )
            )
            continue
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
            payload = report.get(instance_id, {})
            resolved = bool(payload.get("resolved", False))
            reason = payload.get("tests_status") or payload.get("error")
        except (OSError, json.JSONDecodeError, AttributeError) as exc:
            raise RealBenchmarkError(f"cannot parse official evaluator report: {report_path}") from exc
        rows.append(
            EvaluationInstanceResult(
                instance_id=instance_id,
                resolved=resolved,
                status="resolved" if resolved else "unresolved",
                reason=reason if isinstance(reason, str) and reason else None,
            )
        )
    by_id = {row.instance_id: row for row in rows}
    if set(by_id) != expected:
        raise RealBenchmarkError("official evaluator results do not cover the pinned subset")
    return tuple(by_id[instance.instance_id] for instance in manifest.instances)
