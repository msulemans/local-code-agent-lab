"""Named, bounded test execution inside a disposable macOS sandbox."""

from __future__ import annotations

from dataclasses import dataclass, replace
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import tempfile
import time
from typing import Mapping

from .tools import ToolError, ToolResult
from .workspace import Workspace, _run_git


MAX_TEST_OUTPUT_BYTES = 65_536
MAX_TEST_TIMEOUT_SECONDS = 120
SANDBOX_EXEC = Path("/usr/bin/sandbox-exec")


@dataclass(frozen=True, slots=True)
class TestCommand:
    name: str
    arguments: tuple[str, ...]
    pythonpath: str | None = None

    def __post_init__(self) -> None:
        if not self.name or not self.arguments:
            raise ValueError("test command requires a name and arguments")
        if any(not isinstance(value, str) or not value or "\x00" in value for value in self.arguments):
            raise ValueError("test command arguments must be non-empty strings without NUL bytes")


def default_test_commands() -> dict[str, TestCommand]:
    executable = str(Path(sys.executable).resolve(strict=True))
    return {
        "python-unittest": TestCommand(
            name="python-unittest",
            arguments=(executable, "-m", "unittest", "discover", "-s", "tests", "-v"),
            pythonpath="src",
        )
    }


class TestRunner:
    """Execute only constructor-registered commands under fixed constraints."""

    def __init__(self, commands: Mapping[str, TestCommand] | None = None) -> None:
        registered = default_test_commands() if commands is None else dict(commands)
        if not registered or set(registered) != {command.name for command in registered.values()}:
            raise ValueError("test command mapping keys must match unique command names")
        self._commands = registered

    @property
    def command_names(self) -> tuple[str, ...]:
        return tuple(sorted(self._commands))

    def run(
        self,
        workspace: Workspace,
        command_name: str,
        *,
        timeout_seconds: int = 30,
        max_output_bytes: int = MAX_TEST_OUTPUT_BYTES,
    ) -> ToolResult:
        if command_name not in self._commands:
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
        if not SANDBOX_EXEC.is_file():
            raise ToolError("sandbox_unavailable", "macOS sandbox-exec is unavailable")

        root = workspace.root.resolve(strict=True)
        if root == workspace.source_root or root in workspace.source_root.parents:
            raise ToolError("invalid_workspace", "tests must run in a disposable workspace")
        git_root = Path(_run_git(root, ["rev-parse", "--show-toplevel"]).strip()).resolve()
        if git_root != root:
            raise ToolError("git_root_mismatch", "workspace root must equal Git's top-level directory")
        head = _run_git(root, ["rev-parse", "HEAD"]).strip()
        if head != workspace.baseline_commit:
            raise ToolError("workspace_identity_mismatch", "workspace baseline commit changed")

        command = self._commands[command_name]
        if command.name == "python-unittest":
            # Flat-layout repositories (e.g. requests) keep tests at the repo
            # root instead of under tests/; point discovery at the layout that
            # actually exists so run_tests gives the agent useful feedback.
            discovery_dir = "tests" if (root / "tests").is_dir() else "."
            arguments = list(command.arguments)
            for index, argument in enumerate(arguments):
                if argument == "-s" and index + 1 < len(arguments):
                    arguments[index + 1] = discovery_dir
            command = replace(command, arguments=tuple(arguments))
        executable = Path(command.arguments[0]).resolve(strict=True)
        python_root = executable.parent.parent
        with tempfile.TemporaryDirectory(prefix="localcode-test-") as temporary:
            temporary_root = Path(temporary).resolve(strict=True)
            profile = _sandbox_profile(root, python_root, temporary_root, executable)
            environment = {
                "PATH": str(executable.parent),
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONHASHSEED": "0",
                "TMPDIR": str(temporary_root),
                "LANG": "C.UTF-8",
            }
            if command.pythonpath is not None:
                candidate = (root / command.pythonpath).resolve()
                try:
                    candidate.relative_to(root)
                except ValueError as exc:
                    raise ToolError("invalid_test_command", "PYTHONPATH must stay in the workspace") from exc
                # A src/ pythonpath is a convention, not a contract. Real
                # repositories use flat layouts (e.g. requests keeps the
                # package at the repo root); fall back to the root instead
                # of crashing on a missing src directory.
                pythonpath = candidate if candidate.is_dir() else root.resolve(strict=True)
                environment["PYTHONPATH"] = str(pythonpath)

            return _execute_bounded(
                root,
                (str(SANDBOX_EXEC), "-p", profile, *command.arguments),
                environment,
                timeout_seconds,
                max_output_bytes,
                command_name,
            )


def _sandbox_profile(
    workspace: Path,
    python_root: Path,
    temporary_root: Path,
    executable: Path,
) -> str:
    quoted_workspace = json.dumps(str(workspace))
    quoted_python = json.dumps(str(python_root))
    quoted_temporary = json.dumps(str(temporary_root))
    quoted_executable = json.dumps(str(executable))
    return f"""(version 1)
(allow default)
(deny network*)
(deny process-fork)
(deny process-exec)
(allow process-exec (literal {quoted_executable}))
(deny file-write*)
(allow file-write* (subpath {quoted_temporary}) (literal "/dev/null"))
(deny file-read* (subpath "/Users") (subpath "/Volumes") (subpath "/private/tmp") (subpath "/private/var/folders"))
(allow file-read* (subpath {quoted_workspace}) (subpath {quoted_python}) (subpath {quoted_temporary}))
"""


def _execute_bounded(
    root: Path,
    command: tuple[str, ...],
    environment: dict[str, str],
    timeout_seconds: int,
    max_output_bytes: int,
    command_name: str,
) -> ToolResult:
    started = time.monotonic()
    try:
        process = subprocess.Popen(
            command,
            cwd=root,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    except OSError as exc:
        raise ToolError("test_spawn_error", f"could not start test command: {command_name}") from exc
    if process.stdout is None:
        _kill_process_group(process)
        raise ToolError("test_capture_error", "could not capture test output")

    output = bytearray()
    timed_out = False
    output_limit_hit = False
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    deadline = started + timeout_seconds
    try:
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                _kill_process_group(process)
                break
            ready = selector.select(remaining)
            if not ready:
                timed_out = True
                _kill_process_group(process)
                break
            for key, _ in ready:
                chunk = os.read(key.fileobj.fileno(), 8_192)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                room = max_output_bytes + 1 - len(output)
                output.extend(chunk[: max(0, room)])
                if len(output) > max_output_bytes or len(chunk) > room:
                    output_limit_hit = True
                    _kill_process_group(process)
                    break
            if output_limit_hit:
                break
    finally:
        selector.close()
        process.stdout.close()

    return_code = process.wait()
    duration_ms = round((time.monotonic() - started) * 1_000)
    bounded = bytes(output[:max_output_bytes]).decode("utf-8", errors="replace")
    if "sandbox-exec: sandbox_apply: Operation not permitted" in bounded:
        raise ToolError(
            "sandbox_unavailable",
            "the outer environment prevented macOS sandbox policy application",
        )
    return ToolResult(
        content=bounded,
        truncated=output_limit_hit,
        metadata=(
            ("command", command_name),
            ("exit_code", return_code),
            ("timed_out", timed_out),
            ("output_limit_hit", output_limit_hit),
            ("duration_ms", duration_ms),
            ("sandboxed", True),
        ),
    )


def _kill_process_group(process: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    process.wait()
