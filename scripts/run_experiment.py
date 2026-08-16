#!/usr/bin/env python3
"""Run the frozen LocalCode configuration ladder on one registered suite."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from localcode.experiment import load_experiment_manifest, run_experiment


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "benchmarks/experiment/manifest_v1.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        default=str(DEFAULT_MANIFEST),
        help="path to the frozen experiment manifest",
    )
    arguments = parser.parse_args()

    manifest = load_experiment_manifest(arguments.manifest, ROOT)
    result = run_experiment(manifest)
    for configuration in result.configurations:
        if configuration.measured:
            print(
                f"CONFIG {configuration.configuration_id} status={configuration.status} "
                f"label={configuration.label!r} context={configuration.context_mode} "
                f"solved={configuration.solved}/{configuration.registered}"
            )
            for case in configuration.cases:
                status = "PASS" if case.success else "FAIL"
                review = (
                    f" review={case.review_disposition}"
                    if case.review_disposition is not None
                    else ""
                )
                print(
                    f"  CASE {case.case_id} {status} termination={case.termination_reason} "
                    f"tests={list(case.test_exit_codes)} selected={list(case.first_selected_paths)}{review}"
                )
        else:
            print(
                f"CONFIG {configuration.configuration_id} status={configuration.status} "
                f"label={configuration.label!r} reason={configuration.reason}"
            )
    for comparison in result.adjacent_comparisons:
        if comparison.status == "measured":
            print(
                f"DELTA {comparison.previous_configuration_id}->{comparison.next_configuration_id} "
                f"gained={list(comparison.gained)} lost={list(comparison.lost)} "
                f"solved_both={list(comparison.solved_both)}"
            )
        else:
            print(
                f"DELTA {comparison.previous_configuration_id}->{comparison.next_configuration_id} "
                f"status={comparison.status} reason={comparison.reason}"
            )
    print("SUMMARY " + json.dumps(result.to_dict(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
