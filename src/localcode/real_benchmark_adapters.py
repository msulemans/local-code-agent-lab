"""File-backed issue and official SWE-bench evaluator adapters.

The core real-benchmark runner stays dependency-free.  These adapters are the
boundary where a downloaded dataset and the optional official ``swebench``
package enter the process.
"""

from __future__ import annotations

import json
import os
import platform
from pathlib import Path
import subprocess
import tempfile
import time
from typing import Any, Callable

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
from .tools import ToolResult


def _evaluator_environment() -> dict[str, str]:
    """Ensure the evaluator subprocess can import localcode modules.

    huggingface_hub reads ``~/.cache/huggingface/token`` when no token
    environment variable is present, which raises PermissionError in
    restricted environments (e.g. sandboxed evaluation) before the public
    SWE-bench dataset can even be downloaded.  An explicit placeholder token
    skips that unreadable token-file path entirely; a real ``HF_TOKEN`` from
    the caller is preserved via ``setdefault``.
    """

    environment = dict(os.environ)
    source_root = str(Path(__file__).resolve().parent.parent)
    existing = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = (
        source_root if not existing else f"{source_root}{os.pathsep}{existing}"
    )
    environment.setdefault("HF_TOKEN", "localcode-public-dataset-no-auth")
    return environment


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
        max_tool_calls: int = 14,
        max_context_chars: int = 32_000,
        allow_retained_swap: bool = False,
        keep_alive: int = 300,
        think: bool | str = False,
        backend_provider: str = "ollama",
        openai_api_key: str | None = None,
        reasoning_effort: str = "medium",
        test_environment: str = "host",
        observer_factory: Callable[[RealBenchmarkConfiguration, RealBenchmarkIssue, str], object | None] | None = None,
    ) -> None:
        if backend_provider not in {"ollama", "openai"}:
            raise ValueError("backend_provider must be 'ollama' or 'openai'")
        if test_environment not in {"host", "swebench-docker"}:
            raise ValueError("test_environment must be 'host' or 'swebench-docker'")
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
        self.think = think
        self.backend_provider = backend_provider
        self.openai_api_key = openai_api_key
        self.reasoning_effort = reasoning_effort
        self.test_environment = test_environment
        self.observer_factory = observer_factory
        self._preflight_ok = False
        self._client = None

    def finish(self) -> None:
        """Release Ollama memory before the external Docker evaluator starts."""

        if self.backend_provider == "ollama" and self._client is not None:
            _unload_ollama_model(self.model)

    def produce(self, configuration: RealBenchmarkConfiguration, issue: RealBenchmarkIssue):
        from .backends.ollama_loop import (
            LOOP_SYSTEM_PROMPT,
            REVIEW_SYSTEM_PROMPT,
            SINGLE_SHOT_SYSTEM_PROMPT,
            OllamaLoopBackend,
        )
        from .backends.openai_responses import OpenAIResponsesClient, OpenAIResponsesLoopBackend
        from .compatibility import OllamaClient
        from .context import (
            RetrievalContextCompiler,
            SimpleContextCompiler,
            SingleShotContextCompiler,
        )
        from .decisions import DecisionValidator
        from .engineering_registry import (
            EngineeringToolRegistry,
            ProductionReviewRegistry,
            ToolSubsetRegistry,
        )
        from .engineering_smoke import ResourceGuardedLoopBackend
        from .loop import AgentLoop, CompletionRequirements, LoopBudgets
        from .preflight import SmokeBaseline, parse_host_resource_snapshot, validate_smoke_baseline
        from .smoke import _run_host_command
        from .swebench_public_tests import SwebenchPublicTestRunner
        from .tools import git_diff
        from .workspace import create_workspace

        if self.only_instance_id is not None and issue.instance_id != self.only_instance_id:
            return _empty_attempt(issue, self.model, "producer scope excludes this instance")
        agent_observer = (
            self.observer_factory(configuration, issue, "agent") if self.observer_factory else None
        )
        started = time.monotonic()
        if self._client is None:
            self._client = (
                OllamaClient()
                if self.backend_provider == "ollama"
                else OpenAIResponsesClient(api_key=self.openai_api_key)
            )
        client = self._client
        single_shot = configuration.kind == "single_shot_base"
        runtime_tool_document = (
            _tool_document_test_command(self.tool_document, "repository-tests")
            if self.test_environment == "swebench-docker" and not single_shot
            else self.tool_document
        )
        agent_prompt = SINGLE_SHOT_SYSTEM_PROMPT if single_shot else LOOP_SYSTEM_PROMPT
        # The empty-ollama preflight runs once per producer, not once per
        # instance: a multi-instance run legitimately keeps the model resident
        # between instances (m041). The resource baseline for the per-turn
        # swap/memory guard, however, must be captured fresh per instance so
        # drift from earlier instances does not trip the guard (m042).
        if self.backend_provider == "ollama" and not self._preflight_ok:
            validate_smoke_baseline(
                swapusage_output=_run_host_command(("sysctl", "vm.swapusage")),
                memory_pressure_output=_run_host_command(("memory_pressure", "-Q")),
                running_models=client.running_models(),
                allow_retained_swap=self.allow_retained_swap,
            )
            self._preflight_ok = True
        if self.backend_provider == "ollama":
            loop_backend = OllamaLoopBackend(
                model=self.model,
                tool_document=runtime_tool_document,
                client=client,
                context_tokens=self.context_tokens,
                max_output_tokens=self.max_output_tokens,
                allow_tool_subsets=True,
                keep_alive=self.keep_alive,
                think=self.think,
                system_prompt=agent_prompt,
            )
            # Load the model before capturing the per-turn swap baseline so the
            # one-time cold-load cost cannot trip the per-turn growth guard.
            loop_backend.warm_up()
            resources = parse_host_resource_snapshot(
                swapusage_output=_run_host_command(("sysctl", "vm.swapusage")),
                memory_pressure_output=_run_host_command(("memory_pressure", "-Q")),
            )
            baseline = SmokeBaseline(
                swap_used_bytes=resources.swap_used_bytes,
                memory_free_percent=resources.memory_free_percent,
                loaded_models=(),
            )
        else:
            loop_backend = OpenAIResponsesLoopBackend(
                model=self.model,
                tool_document=runtime_tool_document,
                client=client,
                max_output_tokens=self.max_output_tokens,
                reasoning_effort=self.reasoning_effort,
                allow_tool_subsets=True,
                system_prompt=agent_prompt,
            )
            baseline = None
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
            validator_document = (
                _tool_document_subset(runtime_tool_document, {"apply_patch"})
                if single_shot
                else runtime_tool_document
            )
            validator = DecisionValidator.from_tool_document(validator_document)
            backend = (
                ResourceGuardedLoopBackend(
                    loop_backend,
                    baseline=baseline,
                    command_runner=_run_host_command,
                    observer=lambda _snapshot: None,
                )
                if baseline is not None
                else loop_backend
            )
            if self.test_environment == "swebench-docker" and not single_shot:
                if issue.version is None:
                    raise RealBenchmarkError(
                        f"dataset row is missing version for {issue.instance_id}"
                    )
                test_runner = SwebenchPublicTestRunner(
                    instance_id=issue.instance_id,
                    repository=issue.repository,
                    version=issue.version,
                )
            else:
                test_runner = None
            registry = EngineeringToolRegistry(workspace, test_runner)
            agent_registry = (
                ToolSubsetRegistry(registry, {"apply_patch"}) if single_shot else registry
            )
            if single_shot:
                compiler = SingleShotContextCompiler(workspace.root)
            elif configuration.kind in {"retrieval_agent", "agent_plus_review"}:
                compiler = RetrievalContextCompiler(workspace.root, max_files=6)
            else:
                compiler = SimpleContextCompiler()
            if agent_observer is not None and hasattr(agent_observer, "start"):
                agent_observer.start(
                    run_id=f"real-{issue.instance_id}",
                    issue=issue.problem_statement,
                )
            result = AgentLoop(
                backend,
                validator,
                agent_registry,
                LoopBudgets(
                    max_turns=1 if single_shot else self.max_turns,
                    max_tool_calls=1 if single_shot else self.max_tool_calls,
                    max_invalid_actions=1 if single_shot else 4,
                    # Real models may repeat a discovery query after its first
                    # bounded observation; permit one repeat before stopping.
                    max_identical_actions=1 if single_shot else 2,
                    recover_repeated_actions=not single_shot,
                    phase_tool_policy=not single_shot,
                    auto_test_after_edit=not single_shot,
                    auto_test_command_name=(
                        "repository-tests"
                        if self.test_environment == "swebench-docker"
                        else "python-unittest"
                    ),
                    max_wall_seconds=600,
                    max_context_chars=self.max_context_chars,
                ),
                clock=lambda: time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                monotonic=time.monotonic,
                completion_requirements=CompletionRequirements(
                    require_patch=not single_shot,
                    # The official evaluator, not the host, owns real test truth.
                    require_passing_tests=False,
                    # Still require one real local execution before exporting a
                    # patch, so schema mistakes cannot silently skip review.
                    require_test_execution=not single_shot,
                ),
                context_compiler=compiler,
                observer=agent_observer,
            ).run(run_id=f"real-{issue.instance_id}", issue=issue.problem_statement)
            diff = git_diff(workspace.root)
            if agent_observer is not None and hasattr(agent_observer, "finish"):
                agent_observer.finish(result, final_diff=diff.content or "")
            review_tokens = 0
            review_tool_calls = 0
            review_invalid_actions = 0
            review_tests_executed = 0
            review_termination: str | None = None
            if (
                configuration.kind == "agent_plus_review"
                and diff.content
                and diff.content.lstrip().startswith("diff --git ")
                and not diff.truncated
            ):
                if self.backend_provider == "ollama":
                    review_backend = OllamaLoopBackend(
                        model=self.model,
                        tool_document=runtime_tool_document,
                        client=client,
                        context_tokens=self.context_tokens,
                        max_output_tokens=self.max_output_tokens,
                        allow_tool_subsets=True,
                        keep_alive=self.keep_alive,
                        think=self.think,
                        system_prompt=REVIEW_SYSTEM_PROMPT,
                    )
                    review_guarded = ResourceGuardedLoopBackend(
                        review_backend,
                        baseline=baseline,
                        command_runner=_run_host_command,
                        observer=lambda _snapshot: None,
                    )
                else:
                    review_backend = OpenAIResponsesLoopBackend(
                        model=self.model,
                        tool_document=runtime_tool_document,
                        client=client,
                        max_output_tokens=self.max_output_tokens,
                        reasoning_effort=self.reasoning_effort,
                        allow_tool_subsets=True,
                        system_prompt=REVIEW_SYSTEM_PROMPT,
                    )
                    review_guarded = review_backend
                review_observer = (
                    self.observer_factory(configuration, issue, "review")
                    if self.observer_factory
                    else None
                )
                review_result = None
                try:
                    if review_observer is not None and hasattr(review_observer, "start"):
                        review_observer.start(
                            run_id=f"real-{issue.instance_id}-review",
                            issue=issue.problem_statement,
                        )
                    review_result = AgentLoop(
                        review_guarded,
                        validator,
                        ProductionReviewRegistry(registry),
                        LoopBudgets(
                            max_turns=8,
                            max_tool_calls=8,
                            max_invalid_actions=4,
                            max_identical_actions=2,
                            recover_repeated_actions=True,
                            phase_tool_policy=True,
                            auto_test_after_edit=True,
                            auto_test_command_name=(
                                "repository-tests"
                                if self.test_environment == "swebench-docker"
                                else "python-unittest"
                            ),
                            max_wall_seconds=360,
                            max_context_chars=self.max_context_chars,
                        ),
                        clock=lambda: time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                        monotonic=time.monotonic,
                        completion_requirements=CompletionRequirements(
                            require_patch=False,
                            require_passing_tests=False,
                            require_test_execution=True,
                        ),
                        context_compiler=compiler,
                        observer=review_observer,
                    ).run(
                        run_id=f"real-{issue.instance_id}-review",
                        issue=_review_issue_text(
                            issue.problem_statement,
                            diff.content,
                            test_evidence=_last_test_evidence(result.observations),
                        ),
                        initial_patch_tested=result.tests_executed > 0,
                    )
                except Exception:
                    # A crashing review must never destroy the pre-review patch.
                    review_result = None
                if review_result is not None:
                    review_tokens = review_backend.generated_tokens
                    review_tool_calls = review_result.tool_calls_used
                    review_invalid_actions = review_result.invalid_actions_used
                    review_tests_executed = review_result.tests_executed
                    review_termination = review_result.termination_reason.value
                    diff = _final_patch(diff, git_diff(workspace.root))
                if review_observer is not None and hasattr(review_observer, "finish"):
                    if review_result is not None:
                        review_observer.finish(review_result, final_diff=diff.content or "")
        patch = diff.content if not diff.truncated else ""
        produced = (
            bool(patch)
            and patch.lstrip().startswith("diff --git ")
            and (single_shot or result.tests_executed > 0)
        )
        agent_termination = result.termination_reason.value
        termination = review_termination or agent_termination
        return PatchAttempt(
            instance_id=issue.instance_id,
            model_name_or_path=self.model,
            patch=patch if produced else "",
            status="produced" if produced else "no_patch",
            failure_category=None if produced else "LOOP_CONTROL",
            reason=(
                None
                if produced
                else f"agent terminated with {agent_termination}; executed tests={result.tests_executed}"
            ),
            tokens_used=loop_backend.generated_tokens + review_tokens,
            tool_calls=result.tool_calls_used + review_tool_calls,
            wall_seconds=round(time.monotonic() - started, 6),
            termination_reason=termination,
            invalid_actions=result.invalid_actions_used + review_invalid_actions,
            tests_executed=result.tests_executed + review_tests_executed,
            agent_termination_reason=agent_termination,
            review_termination_reason=review_termination,
        )


def _review_issue_text(
    issue: str,
    diff_content: str,
    max_diff_chars: int = 12_000,
    *,
    test_evidence: str | None = None,
) -> str:
    """Compose the issue envelope for the fresh A3 critique pass."""
    shown = diff_content[:max_diff_chars]
    if len(diff_content) > max_diff_chars:
        shown += "\n[diff truncated]"
    return (
        "You are reviewing a candidate patch for the issue below. Critique it, "
        "and revise the workspace only when the patch is wrong, incomplete, or "
        "contains unrelated changes. If it is correct, run the tests once and "
        "finish.\n\nISSUE:\n"
        + issue
        + "\n\nCANDIDATE PATCH:\n"
        + shown
        + "\n\nEXISTING PUBLIC TEST EVIDENCE:\n"
        + (test_evidence if test_evidence else "No completed public test command was recorded.")
    )


def _last_test_evidence(observations: tuple[ToolResult, ...], max_chars: int = 4_000) -> str | None:
    """Return bounded public test evidence from the agent phase for A3."""

    for observation in reversed(observations):
        metadata = observation.metadata_dict()
        if "exit_code" not in metadata:
            continue
        header = (
            f"command={metadata.get('command', 'unknown')} "
            f"exit_code={metadata['exit_code']} "
            f"environment={metadata.get('environment', 'local-sandbox')} "
            f"hidden_tests={metadata.get('hidden_tests', False)}"
        )
        remaining = max(0, max_chars - len(header) - 1)
        content = observation.content[:remaining]
        if len(observation.content) > remaining:
            content += "\n[test output truncated]"
        return header + "\n" + content
    return None


def _final_patch(pre_review: ToolResult, reviewed: ToolResult) -> ToolResult:
    """Keep the reviewed diff only when it is a valid, untruncated git diff."""
    content = reviewed.content
    if (
        content
        and content.lstrip().startswith("diff --git ")
        and not reviewed.truncated
        and not _diff_changes_tests(content)
    ):
        return reviewed
    return pre_review


def _diff_changes_tests(content: str) -> bool:
    from .engineering_registry import _DIFF_PATH, _is_test_path

    return any(_is_test_path(path) for pair in _DIFF_PATH.findall(content) for path in pair)


def _tool_document_subset(document: dict[str, Any], names: set[str]) -> dict[str, Any]:
    tools = document.get("tools")
    if not isinstance(tools, list):
        raise ValueError("tool document must contain a tools list")
    selected = [
        tool
        for tool in tools
        if isinstance(tool, dict)
        and isinstance(tool.get("function"), dict)
        and tool["function"].get("name") in names
    ]
    if len(selected) != len(names):
        raise ValueError("tool document does not contain the required treatment tools")
    return {
        "schema_version": document.get("schema_version", 1),
        "tools": selected,
    }


def _tool_document_test_command(document: dict[str, Any], command_name: str) -> dict[str, Any]:
    """Return a deep copy whose run_tests schema exposes one trusted command."""

    copied = json.loads(json.dumps(document))
    tools = copied.get("tools")
    if not isinstance(tools, list):
        raise ValueError("tool document must contain a tools list")
    matches = [
        tool
        for tool in tools
        if isinstance(tool, dict)
        and isinstance(tool.get("function"), dict)
        and tool["function"].get("name") == "run_tests"
    ]
    if len(matches) != 1:
        raise ValueError("tool document must contain exactly one run_tests schema")
    try:
        command_schema = matches[0]["function"]["parameters"]["properties"]["command_name"]
    except (KeyError, TypeError) as exc:
        raise ValueError("run_tests schema is missing command_name") from exc
    command_schema["enum"] = [command_name]
    matches[0]["function"]["description"] = (
        "Run the repository's registered public test command in a disposable "
        "SWE-bench instance image. Supply only command_name; use repository-tests."
    )
    return copied


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


def _unload_ollama_model(model: str) -> None:
    """Release the resident model before Docker evaluation begins."""

    try:
        subprocess.run(
            ["ollama", "stop", model],
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RealBenchmarkError(f"could not unload Ollama model {model!r}") from exc


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
        version = row.get("version")
        if not all(isinstance(value, str) and value for value in (repository, base_commit, problem_statement)):
            raise RealBenchmarkError(f"dataset row is missing issue fields for {instance.instance_id}")
        if version is not None and (not isinstance(version, str) or not version):
            raise RealBenchmarkError(f"dataset row has invalid version for {instance.instance_id}")
        return RealBenchmarkIssue(
            instance_id=instance.instance_id,
            repository=repository,
            base_commit=base_commit,
            problem_statement=problem_statement,
            version=version,
        )


def prepare_swebench_public_test_images(
    *,
    dataset_name: str,
    split: str,
    instance_ids: tuple[str, ...],
    python_executable: str,
    evaluation_root: str | Path,
    max_workers: int = 1,
) -> None:
    """Build public-test instance images before model inference begins."""

    command = [
        python_executable,
        "-m",
        "swebench.harness.prepare_images",
        "--dataset_name",
        dataset_name,
        "--split",
        split,
        "--instance_ids",
        *instance_ids,
        "--max_workers",
        str(max_workers),
        "--force_rebuild",
        "false",
        # swebench 4.x's prepare_images CLI forwards explicit None values and
        # thereby bypasses make_test_spec's defaults unless both tags are set.
        "--tag",
        "latest",
        "--env_image_tag",
        "latest",
    ]
    try:
        subprocess.run(
            command,
            cwd=Path(evaluation_root),
            env=_evaluator_environment(),
            check=True,
            text=True,
            timeout=3_600,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RealBenchmarkError("could not prepare SWE-bench public-test images") from exc
    for instance_id in instance_ids:
        image = f"sweb.eval.x86_64.{instance_id.lower()}:latest"
        try:
            subprocess.run(
                ("docker", "image", "inspect", image),
                check=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=20,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise RealBenchmarkError(
                f"SWE-bench image preparation did not produce {image}"
            ) from exc


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
            # localcode.swebench_eval installs the documented host tarpit
            # override (m058 gold control: 10.255.255.1 is refused on this
            # host, not blackholed), then delegates to the official harness.
            "localcode.swebench_eval",
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
                env=_evaluator_environment(),
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
