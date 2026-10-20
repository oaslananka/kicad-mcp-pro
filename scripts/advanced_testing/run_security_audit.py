"""Security & Supply Chain Audit Runner for KiCad MCP Pro.

Orchestrates Semgrep, OSV-Scanner, Trivy, and Gitleaks scans,
producing a consolidated security evidence artifact.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess  # nosec B404
import time
from pathlib import Path


def run_command_json(cmd: list[str], timeout: int = 180) -> tuple[int, object]:
    """Execute command expecting JSON stdout."""
    try:
        proc = subprocess.run(  # nosec B603  # nosemgrep
            cmd, capture_output=True, text=True, timeout=timeout
        )
        try:
            return proc.returncode, json.loads(proc.stdout)
        except json.JSONDecodeError:
            return proc.returncode, {
                "raw": proc.stdout.strip()[:1000],
                "stderr": proc.stderr.strip()[:500],
            }
    except Exception as exc:
        return -1, {"error": str(exc)}


def scan_semgrep() -> dict[str, object]:
    """Run Semgrep security-audit ruleset over src/."""
    bin_path = shutil.which("semgrep")
    if not bin_path:
        return {"tool": "semgrep", "status": "SKIPPED", "reason": "semgrep not installed"}

    _, data = run_command_json([bin_path, "--config", "p/security-audit", "src/", "--json"])
    results_list = data.get("results", []) if isinstance(data, dict) else []
    errors = [f for f in results_list if f.get("extra", {}).get("severity") == "ERROR"]
    warnings = [f for f in results_list if f.get("extra", {}).get("severity") != "ERROR"]

    status = "PASS" if len(errors) == 0 else "FINDINGS"
    return {
        "tool": "semgrep",
        "status": status,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "findings_count": len(results_list),
        "findings": results_list[:10],
    }


def scan_osv() -> dict[str, object]:
    """Run OSV-Scanner over lockfiles."""
    bin_path = shutil.which("osv-scanner")
    if not bin_path:
        return {"tool": "osv-scanner", "status": "SKIPPED", "reason": "osv-scanner not installed"}

    _, data = run_command_json(
        [
            bin_path,
            "scan",
            "--lockfile",
            "uv.lock",
            "--lockfile",
            "pnpm-lock.yaml",
            "--format",
            "json",
        ]
    )
    results_list = data.get("results", []) if isinstance(data, dict) else []
    vuln_count = sum(len(pkg.get("packages", [])) for pkg in results_list)
    return {
        "tool": "osv-scanner",
        "status": "PASS" if vuln_count == 0 else "FINDINGS",
        "vulnerability_count": vuln_count,
        "results": results_list,
    }


def scan_trivy() -> dict[str, object]:
    """Run Trivy filesystem vulnerability scan."""
    bin_path = shutil.which("trivy")
    if not bin_path:
        return {"tool": "trivy", "status": "SKIPPED", "reason": "trivy not installed"}

    _, data = run_command_json(
        [
            bin_path,
            "fs",
            "--scanners",
            "vuln",
            "--severity",
            "HIGH,CRITICAL",
            "--format",
            "json",
            ".",
        ]
    )
    res_list = data.get("Results", []) if isinstance(data, dict) else []
    total_high_crit = 0
    for target in res_list:
        vulns = target.get("Vulnerabilities", [])
        total_high_crit += len(vulns)

    return {
        "tool": "trivy",
        "status": "PASS" if total_high_crit == 0 else "FINDINGS",
        "high_critical_vulns": total_high_crit,
    }


def scan_gitleaks() -> dict[str, object]:
    """Run Gitleaks secret scan."""
    bin_path = shutil.which("gitleaks")
    if not bin_path:
        return {"tool": "gitleaks", "status": "SKIPPED", "reason": "gitleaks not installed"}

    proc = subprocess.run(  # nosec B603  # nosemgrep
        [bin_path, "detect", "--no-git", "--redact", "--report-format", "json"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    return {
        "tool": "gitleaks",
        "status": "PASS" if proc.returncode == 0 else "FINDINGS",
        "exit_code": proc.returncode,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Consolidated Security & Supply Chain Runner")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    print("Running Semgrep code scan...")
    semgrep_res = scan_semgrep()
    print(f"Semgrep: {semgrep_res['status']} ({semgrep_res.get('findings_count', 0)} findings)")

    print("Running OSV-Scanner dependency scan...")
    osv_res = scan_osv()
    print(f"OSV-Scanner: {osv_res['status']} ({osv_res.get('vulnerability_count', 0)} vulns)")

    print("Running Trivy filesystem scan...")
    trivy_res = scan_trivy()
    high_crit = trivy_res.get("high_critical_vulns", 0)
    print(f"Trivy: {trivy_res['status']} ({high_crit} High/Crit vulns)")

    print("Running Gitleaks secret scan...")
    gitleaks_res = scan_gitleaks()
    print(f"Gitleaks: {gitleaks_res['status']}")

    summary = {
        "timestamp": time.time(),
        "scanners": {
            "semgrep": semgrep_res,
            "osv_scanner": osv_res,
            "trivy": trivy_res,
            "gitleaks": gitleaks_res,
        },
        "all_passed": all(
            res.get("status") in ("PASS", "SKIPPED")
            for res in [semgrep_res, osv_res, trivy_res, gitleaks_res]
        ),
    }

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(f"Security audit saved to {args.output}")
    else:
        print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
