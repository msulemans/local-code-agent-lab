from __future__ import annotations

import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from localcode.real_benchmark import RealBenchmarkConfiguration, RealBenchmarkError, RealBenchmarkIssue, RealBenchmarkInstance
from localcode.real_benchmark_adapters import (
    DatasetControlPatchProducer,
    JsonDatasetIssueResolver,
    LocalCodePatchProducer,
    OfficialSwebenchEvaluator,
    _final_patch,
    _last_test_evidence,
    _review_issue_text,
    _tool_document_test_command,
    prepare_swebench_public_test_images,
)
from localcode.tools import ToolResult
from localcode.loop import LoopResult, TerminationReason

SCHEMAS = Path("benchmarks/micro_agent/tool_schemas.json")


class RealBenchmarkAdapterTests(unittest.TestCase):
    def _dataset(self, directory: Path) -> Path:
        path = directory / "snapshot.jsonl"
        row = {
            "instance_id": "owner__repo-1",
            "repo": "owner/repo",
            "base_commit": "1234567890abcdef1234567890abcdef12345678",
            "problem_statement": "Fix the parser.",
            "version": "1.0",
            "patch": "diff --git a/src/parser.py b/src/parser.py\n",
            "test_patch": "hidden",
        }
        path.write_text(json.dumps(row) + "\n", encoding="utf-8")
        return path

    def test_issue_resolver_reads_only_public_issue_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = self._dataset(Path(temporary))
            resolver = JsonDatasetIssueResolver(path)
            issue = resolver.resolve(
                RealBenchmarkInstance(
                    "owner__repo-1", "owner/repo", "1234567890abcdef1234567890abcdef12345678"
                )
            )
            self.assertEqual(issue.problem_statement, "Fix the parser.")
            self.assertEqual(issue.version, "1.0")
            self.assertFalse(hasattr(issue, "patch"))

    def test_docker_test_schema_exposes_only_repository_tests(self) -> None:
        original = json.loads(SCHEMAS.read_text(encoding="utf-8"))

        changed = _tool_document_test_command(original, "repository-tests")
        run_tests = next(
            tool for tool in changed["tools"] if tool["function"]["name"] == "run_tests"
        )

        self.assertEqual(
            run_tests["function"]["parameters"]["properties"]["command_name"]["enum"],
            ["repository-tests"],
        )
        original_run_tests = next(
            tool for tool in original["tools"] if tool["function"]["name"] == "run_tests"
        )
        self.assertEqual(
            original_run_tests["function"]["parameters"]["properties"]["command_name"]["enum"],
            ["python-unittest"],
        )

    def test_public_test_image_preparation_is_pinned_to_selected_instances(self) -> None:
        with patch("localcode.real_benchmark_adapters.subprocess.run") as run:
            prepare_swebench_public_test_images(
                dataset_name="snapshot.jsonl",
                split="test",
                instance_ids=("owner__repo-1",),
                python_executable="python-test",
                evaluation_root=".",
            )

        command = run.call_args_list[0].args[0]
        self.assertIn("swebench.harness.prepare_images", command)
        self.assertIn("owner__repo-1", command)
        self.assertIn("--force_rebuild", command)
        self.assertIn("--env_image_tag", command)
        self.assertEqual(run.call_args_list[1].args[0][:3], ("docker", "image", "inspect"))

    def test_control_producer_separates_gold_and_empty_modes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = self._dataset(Path(temporary))
            issue = RealBenchmarkIssue(
                "owner__repo-1", "owner/repo", "1234567890abcdef1234567890abcdef12345678", "Fix the parser."
            )
            configuration = RealBenchmarkConfiguration("B0", "Base", "control", "single_shot_base", "implemented")
            gold = DatasetControlPatchProducer(path, mode="gold").produce(configuration, issue)
            empty = DatasetControlPatchProducer(path, mode="empty").produce(configuration, issue)
            self.assertEqual(gold.status, "produced")
            self.assertTrue(gold.patch.startswith("diff --git "))
            self.assertEqual(empty.status, "no_patch")
            self.assertEqual(empty.patch, "")

    def test_missing_dataset_issue_is_typed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            resolver = JsonDatasetIssueResolver(self._dataset(Path(temporary)))
            with self.assertRaises(RealBenchmarkError):
                resolver.resolve(RealBenchmarkInstance("owner__repo-2", "owner/repo", "1234567"))

    @patch("localcode.real_benchmark_adapters.platform.machine", return_value="arm64")
    @patch("localcode.real_benchmark_adapters.platform.system", return_value="Darwin")
    def test_evaluator_builds_locally_by_default_on_apple_arm(
        self,
        _system: object,
        _machine: object,
    ) -> None:
        evaluator = OfficialSwebenchEvaluator(dataset_name="snapshot.jsonl")

        self.assertEqual(evaluator.namespace, "none")

    def test_evaluator_namespace_can_be_selected_explicitly(self) -> None:
        evaluator = OfficialSwebenchEvaluator(
            dataset_name="snapshot.jsonl",
            namespace="custom-images",
        )

        self.assertEqual(evaluator.namespace, "custom-images")

    def test_evaluator_runs_through_the_tarpit_override_entry_point(self) -> None:
        from localcode.real_benchmark import RealBenchmarkManifest

        manifest = RealBenchmarkManifest(
            subset_id="pinned20-v1",
            dataset_name="snapshot.jsonl",
            dataset_split="test",
            dataset_revision="rev-1",
            selection_seed=7,
            max_per_repository=1,
            compatibility_filters=(),
            fairness_controls=(),
            configurations=(),
            instances=(
                RealBenchmarkInstance(
                    "owner__repo-1", "owner/repo", "1234567890abcdef1234567890abcdef12345678"
                ),
            ),
        )
        configuration = RealBenchmarkConfiguration(
            "A2", "Retrieval agent", "+ ranked repository context", "retrieval_agent", "implemented"
        )
        predictions = Path("runs/x/A2/predictions.jsonl")
        output = Path("runs/x")
        captured = {}

        class FakeCompletion:
            returncode = 0
            stdout = ""
            stderr = ""

        def fake_run(command, **kwargs):
            captured["command"] = command
            captured["env"] = kwargs.get("env")
            return FakeCompletion()

        with (
            patch("localcode.real_benchmark_adapters.subprocess.run", side_effect=fake_run),
            patch(
                "localcode.real_benchmark_adapters._load_evaluation_results",
                return_value=(),
            ),
        ):
            evaluator = OfficialSwebenchEvaluator(dataset_name="snapshot.jsonl")
            evaluator.evaluate(manifest, configuration, predictions, output)

        # The documented host tarpit override is the module that runs, and the
        # subprocess must be able to import localcode regardless of caller env.
        self.assertIn("-m", captured["command"])
        self.assertEqual(
            captured["command"][captured["command"].index("-m") + 1],
            "localcode.swebench_eval",
        )
        self.assertIn("PYTHONPATH", captured["env"])
        self.assertIn("src", captured["env"]["PYTHONPATH"])
        # A placeholder token keeps huggingface_hub from reading the token file
        # in restricted environments; a caller-provided token is preserved.
        self.assertEqual(captured["env"]["HF_TOKEN"], "localcode-public-dataset-no-auth")

    @patch("localcode.real_benchmark_adapters._unload_ollama_model")
    def test_local_producer_unloads_a_model_that_was_used(self, unload) -> None:
        producer = LocalCodePatchProducer(model="gpt-oss:20b", tool_document={})
        producer._client = object()

        producer.finish()

        unload.assert_called_once_with("gpt-oss:20b")

    @patch("localcode.real_benchmark_adapters._unload_ollama_model")
    def test_openai_producer_does_not_touch_ollama_lifecycle(self, unload) -> None:
        producer = LocalCodePatchProducer(
            model="gpt-5.6-terra",
            tool_document={},
            backend_provider="openai",
            openai_api_key="test-only",
        )
        producer._client = object()

        producer.finish()

        unload.assert_not_called()

    def test_openai_producer_skips_host_memory_preflight(self) -> None:
        issue = RealBenchmarkIssue(
            "owner__repo-1",
            "owner/repo",
            "1234567890abcdef1234567890abcdef12345678",
            "Fix the parser.",
        )
        configuration = RealBenchmarkConfiguration(
            "A2", "Retrieval agent", "+ ranked repository context", "retrieval_agent", "implemented"
        )

        with (
            patch("localcode.preflight.validate_smoke_baseline") as preflight,
            patch("localcode.smoke._run_host_command") as host_command,
            patch(
                "localcode.real_benchmark_adapters._clone_at_commit",
                side_effect=RealBenchmarkError("no network"),
            ),
        ):
            producer = LocalCodePatchProducer(
                model="gpt-5.6-terra",
                tool_document=json.loads(SCHEMAS.read_text(encoding="utf-8")),
                backend_provider="openai",
                openai_api_key="test-only",
            )
            producer._client = object()
            with self.assertRaises(RealBenchmarkError):
                producer.produce(configuration, issue)

        preflight.assert_not_called()
        host_command.assert_not_called()

    def test_real_configuration_ladder_uses_distinct_context_and_loop_treatments(self) -> None:
        from localcode.context import (
            RetrievalContextCompiler,
            SimpleContextCompiler,
            SingleShotContextCompiler,
        )

        issue = RealBenchmarkIssue(
            "owner__repo-1",
            "owner/repo",
            "1234567890abcdef1234567890abcdef12345678",
            "Fix the parser.",
        )
        configurations = (
            RealBenchmarkConfiguration("B0", "Base", "one patch", "single_shot_base", "implemented"),
            RealBenchmarkConfiguration("A1", "Simple", "loop", "simple_agent", "implemented"),
            RealBenchmarkConfiguration("A2", "Retrieval", "retrieval", "retrieval_agent", "implemented"),
            RealBenchmarkConfiguration("A3", "Review", "review", "agent_plus_review", "implemented"),
        )
        captured = []

        class FakeLoop:
            def __init__(self, backend, validator, registry, budgets, **kwargs):
                if validator.tool_names != registry.tool_names:
                    raise AssertionError("validator and registry tool surfaces differ")
                captured.append((validator.tool_names, budgets, kwargs["context_compiler"]))

            def run(self, **kwargs):
                return LoopResult(
                    events=(),
                    observations=(),
                    termination_reason=TerminationReason.TURN_EXHAUSTION,
                    final_answer=None,
                    turns_used=1,
                    tool_calls_used=0,
                    invalid_actions_used=0,
                )

        fixture = Path("tests/fixtures/micro_repos/parser_none").resolve()

        def fake_clone(_repository, _commit, destination):
            shutil.copytree(fixture, destination)

        with (
            patch("localcode.loop.AgentLoop", FakeLoop),
            patch("localcode.real_benchmark_adapters._clone_at_commit", side_effect=fake_clone),
        ):
            for configuration in configurations:
                producer = LocalCodePatchProducer(
                    model="gpt-5.6-terra",
                    tool_document=json.loads(SCHEMAS.read_text(encoding="utf-8")),
                    backend_provider="openai",
                    openai_api_key="test-only",
                )
                producer._client = object()
                producer.produce(configuration, issue)

        b0, a1, a2, a3 = captured
        self.assertEqual(b0[0], ("apply_patch",))
        self.assertEqual(b0[1].max_turns, 1)
        self.assertEqual(b0[1].max_tool_calls, 1)
        self.assertFalse(b0[1].auto_test_after_edit)
        self.assertIsInstance(b0[2], SingleShotContextCompiler)
        self.assertGreater(a1[1].max_turns, 1)
        self.assertTrue(a1[1].auto_test_after_edit)
        self.assertIsInstance(a1[2], SimpleContextCompiler)
        self.assertIsInstance(a2[2], RetrievalContextCompiler)
        self.assertIsInstance(a3[2], RetrievalContextCompiler)

    def test_a3_attempt_aggregates_agent_and_review_evidence(self) -> None:
        issue = RealBenchmarkIssue(
            "owner__repo-1",
            "owner/repo",
            "1234567890abcdef1234567890abcdef12345678",
            "Fix the parser.",
        )
        configuration = RealBenchmarkConfiguration(
            "A3", "Review", "review", "agent_plus_review", "implemented"
        )
        test_observation = ToolResult(
            content="tests passed",
            metadata=(("exit_code", 0),),
        )
        results = iter(
            (
                LoopResult(
                    events=(),
                    observations=(test_observation,),
                    termination_reason=TerminationReason.FINAL_ANSWER,
                    final_answer="candidate ready",
                    turns_used=6,
                    tool_calls_used=5,
                    invalid_actions_used=0,
                ),
                LoopResult(
                    events=(),
                    observations=(test_observation,),
                    termination_reason=TerminationReason.TURN_EXHAUSTION,
                    final_answer=None,
                    turns_used=8,
                    tool_calls_used=6,
                    invalid_actions_used=3,
                ),
            )
        )

        class FakeLoop:
            def __init__(self, *args, **kwargs):
                pass

            def run(self, **kwargs):
                return next(results)

        fixture = Path("tests/fixtures/micro_repos/parser_none").resolve()

        def fake_clone(_repository, _commit, destination):
            shutil.copytree(fixture, destination)

        diff = ToolResult(
            content=(
                "diff --git a/src/tiny_parser.py b/src/tiny_parser.py\n"
                "--- a/src/tiny_parser.py\n"
                "+++ b/src/tiny_parser.py\n"
                "@@ -1 +1 @@\n-old\n+new\n"
            )
        )
        with (
            patch("localcode.loop.AgentLoop", FakeLoop),
            patch("localcode.tools.git_diff", side_effect=(diff, diff)),
            patch("localcode.real_benchmark_adapters._clone_at_commit", side_effect=fake_clone),
        ):
            producer = LocalCodePatchProducer(
                model="gpt-5.6-terra",
                tool_document=json.loads(SCHEMAS.read_text(encoding="utf-8")),
                backend_provider="openai",
                openai_api_key="test-only",
            )
            producer._client = object()
            attempt = producer.produce(configuration, issue)

        self.assertEqual(attempt.status, "produced")
        self.assertEqual(attempt.agent_termination_reason, "final_answer")
        self.assertEqual(attempt.review_termination_reason, "turn_exhaustion")
        self.assertEqual(attempt.termination_reason, "turn_exhaustion")
        self.assertEqual(attempt.tool_calls, 11)
        self.assertEqual(attempt.invalid_actions, 3)
        self.assertEqual(attempt.tests_executed, 2)

    def test_preflight_runs_once_but_resource_baseline_refreshes_per_instance(self) -> None:
        issue = RealBenchmarkIssue(
            "owner__repo-1",
            "owner/repo",
            "1234567890abcdef1234567890abcdef12345678",
            "Fix the parser.",
        )
        configuration = RealBenchmarkConfiguration(
            "A2", "Retrieval agent", "+ ranked repository context", "retrieval_agent", "implemented"
        )
        preflight_calls = {"count": 0}
        snapshot_calls = {"count": 0}

        def fake_validate(**kwargs):
            preflight_calls["count"] += 1
            return None

        class FakeResources:
            swap_used_bytes = 0
            memory_free_percent = 80

        def fake_parse(**kwargs):
            snapshot_calls["count"] += 1
            return FakeResources()

        with (
            patch("localcode.preflight.validate_smoke_baseline", side_effect=fake_validate),
            patch("localcode.preflight.parse_host_resource_snapshot", side_effect=fake_parse),
            patch("localcode.smoke._run_host_command", return_value=""),
            patch("localcode.compatibility.OllamaClient"),
            patch(
                "localcode.real_benchmark_adapters._clone_at_commit",
                side_effect=RealBenchmarkError("no network"),
            ),
        ):
            producer = LocalCodePatchProducer(
                model="m",
                tool_document=json.loads(SCHEMAS.read_text(encoding="utf-8")),
                allow_retained_swap=True,
            )
            with self.assertRaises(RealBenchmarkError):
                producer.produce(configuration, issue)
            with self.assertRaises(RealBenchmarkError):
                producer.produce(configuration, issue)

        # The empty-ollama preflight is a once-per-run gate (m041), but the
        # per-turn swap/memory guard needs a fresh baseline per instance so
        # drift from earlier instances does not stop later ones (m042).
        self.assertEqual(preflight_calls["count"], 1)
        self.assertEqual(snapshot_calls["count"], 2)

    def test_producer_invokes_observer_factory_for_the_agent_phase(self) -> None:
        issue = RealBenchmarkIssue(
            "owner__repo-1",
            "owner/repo",
            "1234567890abcdef1234567890abcdef12345678",
            "Fix the parser.",
        )
        configuration = RealBenchmarkConfiguration(
            "A2", "Retrieval agent", "+ ranked repository context", "retrieval_agent", "implemented"
        )
        phases = []

        def factory(_configuration, issue_arg, phase):
            phases.append((phase, issue_arg.instance_id))
            return None

        class FakeResources:
            swap_used_bytes = 0
            memory_free_percent = 80

        with (
            patch("localcode.preflight.validate_smoke_baseline", return_value=None),
            patch("localcode.preflight.parse_host_resource_snapshot", return_value=FakeResources()),
            patch("localcode.smoke._run_host_command", return_value=""),
            patch("localcode.compatibility.OllamaClient"),
            patch(
                "localcode.real_benchmark_adapters._clone_at_commit",
                side_effect=RealBenchmarkError("no network"),
            ),
        ):
            producer = LocalCodePatchProducer(
                model="m",
                tool_document=json.loads(SCHEMAS.read_text(encoding="utf-8")),
                allow_retained_swap=True,
                observer_factory=factory,
            )
            with self.assertRaises(RealBenchmarkError):
                producer.produce(configuration, issue)

        # The --tui stream is requested per instance before any setup work.
        self.assertEqual(phases, [("agent", "owner__repo-1")])

    def test_review_issue_text_embeds_issue_and_bounded_diff(self) -> None:
        text = _review_issue_text(
            "Fix the parser.",
            "diff --git a/x.py b/x.py\n" + "z" * 100,
            max_diff_chars=50,
        )

        self.assertIn("Fix the parser.", text)
        self.assertIn("diff --git", text)
        self.assertIn("[diff truncated]", text)
        shown = text.split("CANDIDATE PATCH:\n", 1)[1].split(
            "\n\nEXISTING PUBLIC TEST EVIDENCE:", 1
        )[0]
        self.assertLessEqual(len(shown), 50 + len("[diff truncated]\n"))

    def test_review_receives_bounded_public_test_evidence(self) -> None:
        observation = ToolResult(
            content="one failed, ninety passed",
            metadata=(
                ("command", "repository-tests"),
                ("environment", "swebench-instance-image"),
                ("exit_code", 1),
                ("hidden_tests", False),
            ),
        )

        evidence = _last_test_evidence((observation,))
        text = _review_issue_text(
            "Fix the parser.",
            "diff --git a/x.py b/x.py\n",
            test_evidence=evidence,
        )

        self.assertIn("EXISTING PUBLIC TEST EVIDENCE", text)
        self.assertIn("command=repository-tests exit_code=1", text)
        self.assertIn("hidden_tests=False", text)
        self.assertIn("one failed, ninety passed", text)

    def test_final_patch_keeps_valid_reviewed_diff_and_falls_back_safely(self) -> None:
        original = ToolResult(content="diff --git a/one.py b/one.py\n")
        better = ToolResult(
            content="diff --git a/one.py b/one.py\ndiff --git a/two.py b/two.py\n"
        )

        self.assertIs(_final_patch(original, better), better)
        self.assertIs(_final_patch(original, ToolResult(content="")), original)
        self.assertIs(_final_patch(original, ToolResult(content="no patch produced")), original)
        self.assertIs(
            _final_patch(original, ToolResult(content="diff --git a/x.py b/x.py\n", truncated=True)),
            original,
        )
        self.assertIs(
            _final_patch(
                original,
                ToolResult(content="diff --git a/tests/test_x.py b/tests/test_x.py\n"),
            ),
            original,
        )


if __name__ == "__main__":
    unittest.main()
