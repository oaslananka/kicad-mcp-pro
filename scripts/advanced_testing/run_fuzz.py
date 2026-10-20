"""Fuzz testing runner for KiCad MCP Pro using Atheris.

Executes fuzz targets and records coverage and corpus statistics.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess  # nosec B404
import time
from pathlib import Path

FUZZ_TARGETS = [
    "fuzz/fuzz_sexpr.py",
]

_COV_RE = re.compile(r"\bcov:\s*(\d+)")
_CORP_RE = re.compile(r"\bcorp:\s*(\d+)")

RUNS_OPTIONS: dict[int, str] = {
    64: "-runs=64",
    128: "-runs=128",
    256: "-runs=256",
    512: "-runs=512",
    1024: "-runs=1024",
    2048: "-runs=2048",
    4096: "-runs=4096",
}

MAX_LEN_OPTIONS: dict[int, str] = {
    512: "-max_len=512",
    1024: "-max_len=1024",
    2048: "-max_len=2048",
    4096: "-max_len=4096",
    8192: "-max_len=8192",
}


def _parse_libfuzzer_stats(output: str) -> tuple[int, int]:
    """Extract coverage and corpus count from libFuzzer output."""
    cov_matches = _COV_RE.findall(output)
    corp_matches = _CORP_RE.findall(output)
    cov = int(cov_matches[-1]) if cov_matches else 0
    corp = int(corp_matches[-1]) if corp_matches else 0
    return cov, corp


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

    runs_flag = "-runs=512"
    for r, flag in RUNS_OPTIONS.items():
        if runs == r:
            runs_flag = flag
            break

    len_flag = "-max_len=4096"
    for m, flag in MAX_LEN_OPTIONS.items():
        if max_len == m:
            len_flag = flag
            break

    cmd = [
        "uv",
        "run",
        "--all-extras",
        "--with",
        "atheris==3.1.0",
        "python",
        "fuzz/fuzz_sexpr.py",
        runs_flag,
        len_flag,
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
        "runs": runs,
        "coverage_points": cov_count,
        "corpus_entries": corp_count,
        "duration_s": round(elapsed, 2),
        "output_tail": "\n".join(output.strip().splitlines()[-10:]),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="KiCad MCP Pro Fuzz Runner")
    parser.add_argument(
        "--runs",
        type=int,
        choices=[64, 128, 256, 512, 1024, 2048, 4096],
        default=512,
        help="Number of fuzzing runs per target",
    )
    parser.add_argument(
        "--max-len",
        type=int,
        choices=[512, 1024, 2048, 4096, 8192],
        default=4096,
        help="Max input length in bytes",
    )
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
