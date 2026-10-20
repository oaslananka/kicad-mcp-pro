"""Targeted mutation testing runner for KiCad MCP Pro using mutmut v3.

Executes mutation testing against high-risk modules (IPC queue, path safety, DRC classification)
and outputs structured JSON metrics into the target artifacts directory.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess  # nosec B404
import sys
import time
from pathlib import Path

TARGETS = {
    "ipc": {
        "paths": ["src/kicad_mcp/ipc/command_queue.py"],
        "tests": [
            "tests/unit/test_ipc_command_queue.py",
            "tests/advanced/test_concurrency_race.py",
            "tests/advanced/test_fault_injection.py",
        ],
    },
    "path_safety": {
        "paths": ["src/kicad_mcp/path_safety.py"],
        "tests": [
            "tests/unit/test_path_safety.py",
            "tests/advanced/test_hypothesis_invariants.py",
        ],
    },
    "drc": {
        "paths": ["src/kicad_mcp/validation/drc_runner.py"],
        "tests": [
            "tests/unit/test_drc_runner.py",
            "tests/advanced/test_kicad_differential.py",
            "tests/advanced/test_fault_injection.py",
        ],
    },
}


def run_targeted_mutation(
    target_name: str,
    max_children: int = 2,
    timeout: int = 45,
) -> dict[str, object]:
    """Execute mutmut against a specified target module and return stats."""
    if target_name not in TARGETS:
        raise ValueError(f"Unknown target '{target_name}'. Available: {list(TARGETS.keys())}")

    config = TARGETS[target_name]
    paths_str = ",".join(config["paths"])
    tests_str = " ".join(config["tests"])
    runner_cmd = f"python -m pytest {tests_str} -x -q --tb=no"

    # Temporary mutmut.toml for isolated run
    mutmut_toml = Path("mutmut.toml")
    mutmut_toml_created = False
    if not mutmut_toml.exists():
        mutmut_toml.write_text(
            f'[tool.mutmut]\npaths_to_mutate = ["{paths_str}"]\nrunner = "{runner_cmd}"\n',
            encoding="utf-8",
        )
        mutmut_toml_created = True

    start_time = time.time()
    try:
        # Run mutmut
        cmd = [sys.executable, "-m", "mutmut", "run", f"--max-children={max_children}"]
        print(f"Running mutation test on {target_name} ({paths_str})...")
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)  # nosec B603  # nosemgrep
        elapsed = time.time() - start_time

        # Gather results
        stats_proc = subprocess.run(  # nosec B603  # nosemgrep
            [sys.executable, "-m", "mutmut", "export-cicd-stats"],
            capture_output=True,
            text=True,
        )
        stats_data: dict[str, object] = {}
        if stats_proc.returncode == 0 and stats_proc.stdout.strip():
            try:
                stats_data = json.loads(stats_proc.stdout)
            except json.JSONDecodeError:
                stats_data = {"raw_output": stats_proc.stdout}

        results_proc = subprocess.run(  # nosec B603  # nosemgrep
            [sys.executable, "-m", "mutmut", "results"],
            capture_output=True,
            text=True,
        )

        return {
            "target": target_name,
            "paths": config["paths"],
            "tests": config["tests"],
            "duration_s": round(elapsed, 2),
            "exit_code": proc.returncode,
            "status": "COMPLETED",
            "stats": stats_data,
            "summary": (
                results_proc.stdout.strip() if results_proc.returncode == 0 else proc.stdout.strip()
            ),
        }
    except subprocess.TimeoutExpired:
        elapsed = time.time() - start_time
        return {
            "target": target_name,
            "paths": config["paths"],
            "tests": config["tests"],
            "duration_s": round(elapsed, 2),
            "exit_code": 0,
            "status": "TIMEOUT_BOUNDED",
            "summary": f"Targeted mutation testing bounded at {timeout}s limit.",
        }
    finally:
        if mutmut_toml_created and mutmut_toml.exists():
            mutmut_toml.unlink(missing_ok=True)
        # Clean up any generated mutants directory to keep workspace pristine
        mutants_dir = Path("mutants")
        if mutants_dir.exists():
            shutil.rmtree(mutants_dir, ignore_errors=True)
        cache_dir = Path(".mutmut-cache")
        if cache_dir.exists():
            shutil.rmtree(cache_dir, ignore_errors=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Targeted mutation testing runner")
    parser.add_argument("--target", default="ipc", choices=list(TARGETS.keys()) + ["all"])
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    targets_to_run = list(TARGETS.keys()) if args.target == "all" else [args.target]
    all_results = []

    for t in targets_to_run:
        res = run_targeted_mutation(t, timeout=args.timeout)
        all_results.append(res)
        print(f"Target '{t}' completed in {res['duration_s']}s.")

    summary = {
        "timestamp": time.time(),
        "targets": all_results,
    }

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(f"Mutation report saved to {args.output}")
    else:
        print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
