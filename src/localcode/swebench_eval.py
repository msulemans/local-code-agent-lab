"""Official SWE-bench evaluator entry point with a host environment override.

The requests TestTimeout suite connects to the TARPIT address
``http://10.255.255.1``, which is expected to silently blackhole so the
connect hangs and requests raises :class:`requests.exceptions.ConnectTimeout`.
On this host (macOS + Docker Desktop), routed traffic to 10.255.255.1 is
answered with an immediate ICMP unreachable (ECONNREFUSED), so the connect is
refused instead of timing out.

This was proven to be an environment limitation, not a model defect, by the
official gold control for ``psf__requests-2931`` (m058): the ground-truth
patch passed the FAIL_TO_PASS test and 83 of 84 PASS_TO_PASS tests, failing
only ``test_connect_timeout``, which never touches the changed code.

The override below rewrites the TARPIT constant to ``203.0.113.1`` (RFC 5737
TEST-NET-3), a documentation-range address that blackholes on this host
exactly as 10.255.255.1 does on the official infrastructure.  The test's
assertion is preserved unchanged: a silent connect timeout must surface as
``ConnectTimeout``.  The sed is guarded (no match means no change), so it is
a no-op for every repository that does not use the tarpit address.
"""

from __future__ import annotations

from typing import Any, Callable, Iterable

#: The requests tarpit address that this host refuses instead of blackholing.
TARPIT_SOURCE = "10.255.255.1"
#: RFC 5737 TEST-NET-3: documentation range that blackholes on this host.
TARPIT_REPLACEMENT = "203.0.113.1"

_SED_COMMAND = (
    "find . -name '*.py' -type f -exec "
    f"sed -i 's#{TARPIT_SOURCE}#{TARPIT_REPLACEMENT}#g' {{}} + "
    "|| true"
)


def inject_tarpit_override(commands: Iterable[str]) -> list[str]:
    """Insert a guarded tarpit rewrite before the pytest step of an eval script.

    The command list is the SWE-bench eval_script_list for one instance.  The
    rewrite runs after the test patch is applied and before pytest, inside the
    repository working directory.  It is harmless for repositories that never
    reference the tarpit address.
    """

    rewritten = False
    result: list[str] = []
    for command in commands:
        if (
            not rewritten
            and command.lstrip().startswith("git apply")
            and not any(line.startswith(_SED_COMMAND) for line in result)
        ):
            result.append(_SED_COMMAND)
            rewritten = True
        result.append(command)
    return result


def install_tarpit_override() -> None:
    """Wrap the SWE-bench eval-script generator with the tarpit rewrite.

    ``make_test_spec`` resolves ``make_eval_script_list`` at call time from the
    ``swebench.harness.test_spec.test_spec`` module namespace, so assigning the
    wrapper there is sufficient for every instance the harness builds.
    """

    from swebench.harness.test_spec import test_spec as test_spec_module

    original: Callable[..., list[str]] = test_spec_module.make_eval_script_list

    def wrapped(instance: dict[str, Any], *args: Any, **kwargs: Any) -> list[str]:
        commands = original(instance, *args, **kwargs)
        return inject_tarpit_override(commands)

    test_spec_module.make_eval_script_list = wrapped


def main() -> None:
    """Install the environment override, then run the official harness."""

    import runpy

    install_tarpit_override()
    runpy.run_module("swebench.harness.run_evaluation", run_name="__main__")


if __name__ == "__main__":
    main()
