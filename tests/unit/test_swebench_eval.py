from __future__ import annotations

import json
from pathlib import Path
import unittest
from unittest.mock import patch

from localcode.swebench_eval import (
    TARPIT_REPLACEMENT,
    TARPIT_SOURCE,
    _SED_COMMAND,
    inject_tarpit_override,
    install_tarpit_override,
)


class SwebenchEvalOverrideTests(unittest.TestCase):
    def test_injects_guarded_sed_before_git_apply(self) -> None:
        commands = [
            "source /opt/miniconda3/bin/activate",
            "conda activate testbed",
            "cd /testbed",
            "git checkout 5f7a3a74 test_requests.py",
            "git apply -v - <<'EOF'\ndiff --git a/test_requests.py b/test_requests.py\nEOF",
            ": '>>>>> Start Test Output'",
            "pytest test_requests.py",
            ": '>>>>> End Test Output'",
        ]

        result = inject_tarpit_override(commands)

        self.assertIn(_SED_COMMAND, result)
        self.assertEqual(
            result.index(_SED_COMMAND) + 1,
            result.index(
                "git apply -v - <<'EOF'\ndiff --git a/test_requests.py b/test_requests.py\nEOF"
            ),
        )
        self.assertEqual(len(result), len(commands) + 1)

    def test_sed_targets_the_tarpit_address(self) -> None:
        self.assertIn(TARPIT_SOURCE, _SED_COMMAND)
        self.assertIn(TARPIT_REPLACEMENT, _SED_COMMAND)
        # sed -i with # separators: no / escaping needed inside the pattern.
        self.assertIn("sed -i 's#10.255.255.1#203.0.113.1#g'", _SED_COMMAND)

    def test_no_double_injection_with_multiple_git_apply_lines(self) -> None:
        commands = [
            "git apply -v - <<'EOF'\none\nEOF",
            "git apply -v - <<'EOF'\ntwo\nEOF",
            "pytest .",
        ]

        result = inject_tarpit_override(commands)

        self.assertEqual(result.count(_SED_COMMAND), 1)

    def test_no_op_when_no_git_apply_step(self) -> None:
        commands = ["cd /testbed", "pytest ."]

        self.assertEqual(inject_tarpit_override(commands), commands)

    def test_install_wraps_the_generator_in_the_harness_namespace(self) -> None:
        import swebench.harness.test_spec.test_spec as test_spec_module

        original = test_spec_module.make_eval_script_list
        try:
            with patch.object(
                test_spec_module,
                "make_eval_script_list",
                return_value=[
                    "git apply -v - <<'EOF'\ndiff --git a/x b/x\nEOF",
                    "pytest .",
                ],
            ):
                install_tarpit_override()
                wrapped = test_spec_module.make_eval_script_list
                commands = wrapped(
                    {"instance_id": "x"}, {}, "testbed", "/testbed", "abc", "patch"
                )
            # The wrapper stays installed (restore happened, but the module
            # attribute is our wrapper, and its captured original still works).
            self.assertIn(_SED_COMMAND, commands)
            self.assertIn("pytest .", commands)
        finally:
            test_spec_module.make_eval_script_list = original


if __name__ == "__main__":
    unittest.main()
