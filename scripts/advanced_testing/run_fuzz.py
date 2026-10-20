"""Fuzz testing runner for KiCad MCP Pro using Atheris.

Executes fuzz targets and records coverage and corpus statistics.
"""

from __future__ import annotations

import argparse
import json
import subprocess  # nosec B404
import time
from pathlib import Path

FUZZ_TARGETS = [
    "fuzz/fuzz_sexpr.py",
]


def _parse_libfuzzer_stats(output: str) -> tuple[int, int]:
    """Extract coverage and corpus count from libFuzzer output."""
    cov_count = 0
    corp_count = 0
    for line in output.splitlines():
        if "DONE" not in line and "#" not in line:
            continue
        parts = line.split()
        for i, part in enumerate(parts):
            if part == "cov:" and i + 1 < len(parts):
                try:
                    cov_count = int(parts[i + 1])
                except ValueError:
                    pass
            elif part == "corp:" and i + 1 < len(parts):
                try:
                    corp_count = int(parts[i + 1].split("/")[0])
                except ValueError:
                    pass
    return cov_count, corp_count


def run_fuzz_target(target_path: str, runs: int = 512, max_len: int = 4096) -> dict[str, object]:
    """Execute one Atheris fuzz target and return structured outcome."""
    if target_path not in FUZZ_TARGETS:
        return {
            "target": target_path,
            "status": "INVALID",
            "error": f"Fuzz target not permitted: {target_path}",
        }

    target = Path(target_path)
    if not target.is_file():
        return {
            "target": target_path,
            "status": "MISSING",
            "error": f"Fuzz target not found at {target_path}",
        }

    safe_runs = max(1, min(int(runs), 100_000))
    safe_max_len = max(1, min(int(max_len), 65_536))
    cmd = [
        "uv",
        "run",
        "--all-extras",
        "--with",
        "atheris==3.1.0",
        "python",
        "fuzz/fuzz_sexpr.py",
        f"-runs={safe_runs}",
        f"-max_len={safe_max_len}",
    ]

    start_time = time.time()
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)  # nosec B603  # nosemgrep
    elapsed = time.time() - start_time

    output = proc.stdout + "\n" + proc.stderr
    cov_count, corp_count = _parse_libfuzzer_stats(output)

    return {
        "target": target_path,
        "status": "PASS" if proc.returncode == 0 else "FAIL",
        "exit_code": proc.returncode,
        "runs": safe_runs,
        "coverage_points": cov_count,
        "corpus_entries": corp_count,
        "duration_s": round(elapsed, 2),
        "output_tail": "\n".join(output.strip().splitlines()[-10:]),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="KiCad MCP Pro Fuzz Runner")
    parser.add_argument("--runs", type=int, default=512, help="Number of fuzzing runs per target")
    parser.add_argument("--max-len", type=int, default=4096, help="Max input length in bytes")
    parser.add_argument("--output", type=Path, default=None, help="JSON output destination")
    args = parser.parse_args()

    results = []
    for target in FUZZ_TARGETS:
        print(f"Running fuzz target: {target} ({args.runs} runs)...")
        res = run_fuzz_target(target, runs=args.runs, max_len=args.max_len)
        results.append(res)
        print(f"Target {target} finished with {res['status']} in {res.get('duration_s', 0)}s.")

    summary = {
        "timestamp": time.time(),
        "total_targets": len(FUZZ_TARGETS),
        "results": results,
    }

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(f"Fuzz report saved to {args.output}")
    else:
        print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
