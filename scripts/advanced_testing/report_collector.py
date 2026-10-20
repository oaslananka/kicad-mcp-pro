"""Advanced QA evidence and report collector for KiCad MCP Pro.

Aggregates execution artifacts from all testing layers and writes
commit-SHA-indexed summary.json and report.md artifacts into
artifacts/advanced-testing/<commit-sha>/.
"""

from __future__ import annotations

import argparse
import datetime
import json
import platform
import shutil
import subprocess  # nosec B404
import sys
from pathlib import Path


def get_git_info() -> dict[str, str]:
    """Retrieve current git commit SHA, branch, and tree status."""

    def _run(cmd: list[str]) -> str:
        try:
            return subprocess.check_output(cmd, text=True).strip()  # nosec B603  # nosemgrep
        except Exception:
            return "unknown"

    return {
        "commit_sha": _run(["git", "rev-parse", "HEAD"]),
        "short_sha": _run(["git", "rev-parse", "--short", "HEAD"]),
        "branch": _run(["git", "branch", "--show-current"]),
        "dirty": bool(_run(["git", "status", "--porcelain"])),
        "commit_date": _run(["git", "log", "-1", "--format=%cd", "--date=iso"]),
    }


def collect_evidence(
    output_base: Path | None = None,
) -> Path:
    """Collect test summaries and write standard reports."""
    git_info = get_git_info()
    commit_sha = git_info["commit_sha"]
    short_sha = git_info["short_sha"]

    base = output_base or Path("artifacts/advanced-testing")
    target_dir = base / short_sha
    target_dir.mkdir(parents=True, exist_ok=True)

    # The runners write into current/; reports are immutable per commit SHA.
    # Never label absent, invalid, or failing evidence as PASS.
    categories: dict[str, object] = {}
    for name in ("memory-profile", "performance-benchmarks", "runtime-benchmarks"):
        source = base / "current" / f"{name}.json"
        if not source.is_file():
            continue
        try:
            data = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            categories[name] = None
            continue
        categories[name] = data
        shutil.copyfile(source, target_dir / source.name)

    def benchmark_ok(payload: object, profile: str) -> bool:
        if not isinstance(payload, dict):
            return False
        result = payload.get("benchmark")
        if not isinstance(result, dict):
            return False
        latencies = result.get("latencies_ms")
        return (
            result.get("profile") == profile
            and result.get("pass_criteria_met") is True
            and type(result.get("total_requests")) is int
            and result["total_requests"] > 0
            and type(result.get("error_rate_percent")) in (int, float)
            and result["error_rate_percent"] < 1.0
            and isinstance(latencies, dict)
            and type(latencies.get("p95")) in (int, float)
            and latencies["p95"] < 200.0
        )

    memory = categories.get("memory-profile")
    api = categories.get("performance-benchmarks")
    runtime = categories.get("runtime-benchmarks")
    memory_status = (
        "PASS"
        if isinstance(memory, dict)
        and memory.get("all_clean") is True
        and all(
            isinstance(p, dict) and p.get("leak_detected") is False and "error" not in p
            for p in memory.get("profiles", [])
        )
        and bool(memory.get("profiles"))
        else "FAIL"
    )
    api_status = "PASS" if benchmark_ok(api, "lightweight") else "FAIL"
    runtime_status = "PASS" if benchmark_ok(runtime, "runtime") else "WARN"
    layers = {
        "Memory & Leak Profiling": memory_status,
        "Lightweight API Benchmark (required)": api_status,
        "KiCad Runtime Benchmark (diagnostic)": runtime_status,
    }
    status = (
        "FAIL" if "FAIL" in layers.values() else "WARN" if "WARN" in layers.values() else "PASS"
    )

    timestamp = datetime.datetime.now(datetime.UTC).isoformat()

    summary_payload = {
        "git": git_info,
        "timestamp": timestamp,
        "environment": {
            "python_version": sys.version,
            "os": platform.platform(),
            "machine": platform.machine(),
        },
        "evidence_categories": list(categories.keys()),
        "status": status,
        "layers": layers,
    }

    # Write summary.json
    summary_path = target_dir / "summary.json"
    summary_path.write_text(json.dumps(summary_payload, indent=2), encoding="utf-8")

    # Only attest checks for which this collector actually has evidence.
    rows = "\n".join(f"| {name} | {state} |" for name, state in layers.items())
    report_md = f"""# KiCad MCP Pro — Advanced QA Evidence Report

**Commit SHA:** `{commit_sha}` (`{short_sha}`)
**Branch:** `{git_info["branch"]}` (Dirty: `{git_info["dirty"]}`)
**Timestamp:** `{timestamp}`
**Overall evidence status:** **{status}**

| Measured Layer | Status |
|---|---|
{rows}

The runtime benchmark is diagnostic because hosted runners have no live KiCad IPC.
A WARN is not a passing runtime benchmark. Other Advanced QA checks are only
attested by their own CI steps; they are not marked PASS by this report.

Evidence files: `artifacts/advanced-testing/{short_sha}/`.
"""

    report_path = target_dir / "report.md"
    report_path.write_text(report_md, encoding="utf-8")
    print(f"Advanced QA reports written to: {target_dir}")
    return target_dir


def main() -> None:
    parser = argparse.ArgumentParser(description="Advanced QA Report Collector")
    parser.add_argument("--output-base", type=Path, default=Path("artifacts/advanced-testing"))
    args = parser.parse_args()

    target = collect_evidence(output_base=args.output_base)
    summary = json.loads((target / "summary.json").read_text(encoding="utf-8"))
    if summary["status"] == "FAIL":
        raise SystemExit("Required Advanced QA evidence failed or is missing")


if __name__ == "__main__":
    main()
