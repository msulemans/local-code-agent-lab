import subprocess

from localcode.real_benchmark_adapters import _evaluator_environment

command = [
    ".venv-realbench/bin/python",
    "-m",
    "localcode.swebench_eval",
    "--dataset_name",
    "SWE-bench/SWE-bench_Verified",
    "--split",
    "test",
    "--predictions_path",
    "runs/real-benchmark/m062-requests-gold-control/B0/predictions.jsonl",
    "--instance_ids",
    "psf__requests-2931",
    "--max_workers",
    "1",
    "--run_id",
    "localcode-b0-verify-hftoken-requests-gold-control",
    "--cache_level",
    "base",
    "--clean",
    "False",
    "--namespace",
    "none",
]
completed = subprocess.run(
    command,
    cwd=".",
    capture_output=True,
    text=True,
    check=False,
    env=_evaluator_environment(),
)
print("RC =", completed.returncode)
print("\n".join(completed.stdout.splitlines()[-6:]))
if completed.returncode != 0:
    print("STDERR TAIL:", "\n".join(completed.stderr.splitlines()[-15:]))
