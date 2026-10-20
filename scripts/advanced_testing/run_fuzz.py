"""Fuzz testing runner for KiCad MCP Pro using Atheris.

Executes fuzz targets and records coverage and corpus statistics.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path

FUZZ_TARGETS = [
    "fuzz/fuzz_sexpr.py",
]


def run_fuzz_target(target_path: str, runs: int = 512, max_len: int = 4096) -> dict[str, object]:
    """Execute one Atheris fuzz target and return structured outcome."""
    target = Path(target_path)
    if not target.exists():
        return {
            "target": target_path,
            "status": "MISSING",
            "error": f"Fuzz target not found at {target_path}",
        }

    cmd = [
        "uv",
        "run",
        "--all-extras",
        "--with",
        "atheris==3.1.0",
        "python",
        str(target),
        f"-runs={runs}",
        f"-max_len={max_len}",
    ]

    start_time = time.time()
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    elapsed = time.time() - start_time

    # Parse stdout/stderr for libfuzzer stats
    output = proc.stdout + "\n" + proc.stderr
    cov_count = 0
    corp_count = 0
    for line in output.splitlines():
        if "DONE" in line or "#" in line:
            parts = line.split()
            for i, p in enumerate(parts):
                if p == "cov:":
                    try:
                        cov_count = int(parts[i + 1])
                    except (ValueError, IndexError):
                        pass
                elif p == "corp:":
                    try:
                        corp_count = int(parts[i + 1].split("/")[0])
                    except (ValueError, IndexError):
                        pass

    return {
        "target": target_path,
        "status": "PASS" if proc.returncode == 0 else "FAIL",
        "exit_code": proc.returncode,
        "runs": runs,
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
