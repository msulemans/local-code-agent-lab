"""Run repository-owned public tests in a pinned SWE-bench instance image.

The agent receives only the repository patch and the public test command from
SWE-bench's version specification.  Evaluator scripts, FAIL_TO_PASS tests, and
the hidden test patch are never mounted or exposed here.
"""

from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import uuid

from .test_runner import MAX_TEST_OUTPUT_BYTES, MAX_TEST_TIMEOUT_SECONDS, _execute_bounded
from .tools import ToolError, ToolResult
from .workspace import Workspace, _run_git


_INSTANCE_ID = re.compile(r"^[A-Za-z0-9._-]+__[A-Za-z0-9._-]+-\d+$")


class SwebenchPublicTestRunner:
    """Execute one trusted public command in an isolated instance image."""

    command_names = ("repository-tests",)

    def __init__(
        self,
        *,
        instance_id: str,
        repository: str,
        version: str,
        public_test_command: str | None = None,
        docker_executable: str | None = None,
    ) -> None:
        if not isinstance(instance_id, str) or _INSTANCE_ID.fullmatch(instance_id) is None:
            raise ValueError("invalid SWE-bench instance ID")
        if not isinstance(repository, str) or "/" not in repository:
            raise ValueError("invalid SWE-bench repository")
        if not isinstance(version, str) or not version:
            raise ValueError("SWE-bench version is required for public tests")
        command = public_test_command or _public_test_command(repository, version)
        if not isinstance(command, str) or not command.strip() or "\x00" in command:
            raise ValueError("public test command must be non-empty and contain no NUL bytes")
        executable = docker_executable or shutil.which("docker")
        if not executable:
            raise ToolError("test_environment_unavailable", "Docker CLI is unavailable")
        self.instance_id = instance_id
        self.repository = repository
        self.version = version
        self.public_test_command = command.strip()
        self.docker_executable = str(Path(executable).resolve())
        self.image = f"sweb.eval.x86_64.{instance_id.lower()}:latest"

    def run(
        self,
        workspace: Workspace,
        command_name: str,
        *,
        timeout_seconds: int = 120,
        max_output_bytes: int = MAX_TEST_OUTPUT_BYTES,
    ) -> ToolResult:
        if command_name != "repository-tests":
            raise ToolError("unknown_test_command", f"unknown test command: {command_name!r}")
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, int)
            or not 1 <= timeout_seconds <= MAX_TEST_TIMEOUT_SECONDS
        ):
            raise ToolError(
                "invalid_argument",
                f"timeout_seconds must be between 1 and {MAX_TEST_TIMEOUT_SECONDS}",
            )
        if (
            isinstance(max_output_bytes, bool)
            or not isinstance(max_output_bytes, int)
            or not 1 <= max_output_bytes <= MAX_TEST_OUTPUT_BYTES
        ):
            raise ToolError(
                "invalid_argument",
                f"max_output_bytes must be between 1 and {MAX_TEST_OUTPUT_BYTES}",
            )

        root = _validated_workspace_root(workspace)
        _require_image(self.docker_executable, self.image)
        patch = _run_git(root, ["diff", "--binary", "--no-ext-diff"])
        container_name = f"localcode-{uuid.uuid4().hex}"
        with tempfile.TemporaryDirectory(prefix="localcode-swebench-test-") as temporary:
            patch_path = Path(temporary) / "candidate.patch"
            patch_path.write_text(patch, encoding="utf-8")
            apply_patch = (
                "git apply --check /localcode/candidate.patch && "
                "git apply /localcode/candidate.patch && "
                if patch
                else ""
            )
            shell_command = f"cd /testbed && {apply_patch}{self.public_test_command}"
            command = (
                self.docker_executable,
                "run",
                "--rm",
                "--name",
                container_name,
                "--network",
                "none",
                "--platform",
                "linux/amd64",
                "--pids-limit",
                "512",
                "--memory",
                "4g",
                "--cpus",
                "4",
                "--mount",
                f"type=bind,source={patch_path},destination=/localcode/candidate.patch,readonly",
                self.image,
                "/bin/bash",
                "-lc",
                shell_command,
            )
            result = _execute_bounded(
                root,
                command,
                {"PATH": os.path.dirname(self.docker_executable), "LANG": "C.UTF-8"},
                timeout_seconds,
                max_output_bytes,
                command_name,
                False,
            )
            if result.metadata_dict().get("timed_out"):
                _remove_container(self.docker_executable, container_name)

        metadata = result.metadata_dict()
        metadata.update(
            sandboxed=True,
            environment="swebench-instance-image",
            hidden_tests=False,
            image=self.image,
            public_test_command=self.public_test_command,
        )
        return ToolResult(
            content=result.content,
            truncated=result.truncated,
            metadata=tuple(sorted(metadata.items())),
        )


def _public_test_command(repository: str, version: str) -> str:
    try:
        from swebench.harness.constants import MAP_REPO_VERSION_TO_SPECS

        command = MAP_REPO_VERSION_TO_SPECS[repository][version]["test_cmd"]
    except (ImportError, KeyError, TypeError) as exc:
        raise ToolError(
            "test_environment_unavailable",
            f"no pinned public test command for {repository} version {version}",
        ) from exc
    if not isinstance(command, str) or not command.strip():
        raise ToolError("test_environment_unavailable", "invalid public test command in SWE-bench")
    return command


def _validated_workspace_root(workspace: Workspace) -> Path:
    root = workspace.root.resolve(strict=True)
    if root == workspace.source_root or root in workspace.source_root.parents:
        raise ToolError("invalid_workspace", "tests must run in a disposable workspace")
    git_root = Path(_run_git(root, ["rev-parse", "--show-toplevel"]).strip()).resolve()
    if git_root != root:
        raise ToolError("git_root_mismatch", "workspace root must equal Git's top-level directory")
    if _run_git(root, ["rev-parse", "HEAD"]).strip() != workspace.baseline_commit:
        raise ToolError("workspace_identity_mismatch", "workspace baseline commit changed")
    return root


def _require_image(docker: str, image: str) -> None:
    try:
        subprocess.run(
            (docker, "image", "inspect", image),
            check=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ToolError(
            "test_environment_unavailable",
            f"SWE-bench instance image is not ready: {image}",
        ) from exc


def _remove_container(docker: str, name: str) -> None:
    try:
        subprocess.run(
            (docker, "rm", "-f", name),
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        pass
