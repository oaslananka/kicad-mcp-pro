"""OSV multi-ecosystem monitoring does not hide advisories or weaken PR gates."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/osv-inventory-weekly.yml"


def test_osv_weekly_inventory_is_pinned_and_uploads_all_findings() -> None:
    data = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert data["permissions"]["contents"] == "read"
    assert data["permissions"]["actions"] == "read"
    assert data["concurrency"]["cancel-in-progress"] is False
    assert data[True]["schedule"]
    assert data[True]["workflow_dispatch"] is None
    job = data["jobs"]["osv-full-inventory"]
    assert job["permissions"] == {
        "contents": "read",
        "actions": "read",
        "security-events": "write",
    }
    assert job["if"] == "github.repository == 'oaslananka/kicad-mcp-pro'"
    assert job["runs-on"] == "ubuntu-24.04"
    steps = {step["name"]: step for step in job["steps"]}
    checkout = steps["Checkout source for reproducible inventory"]
    assert checkout["uses"] == "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1"
    assert checkout["with"]["persist-credentials"] is False

    scan = steps["Scan all repository lockfiles with pinned OSV-Scanner 2.7.0"]
    assert scan["uses"] == (
        "google/osv-scanner-action/osv-scanner-action@0a65f82af05cd58cf587827b0bb0489548c18346"
    )
    assert scan["continue-on-error"] is True
    assert scan["with"]["scan-args"].strip().splitlines() == [
        "--output=results.json",
        "--format=json",
        "--config=.github/security/osv-full-inventory.toml",
        "-r",
        "./",
    ]
    check = steps["Reject scanner failures without a result document"]
    assert check["if"] == "steps.scan.outcome == 'failure'"
    assert "[[ ! -s results.json ]]" in check["run"]

    reporter = steps["Produce SARIF without hiding reviewed Rust findings"]
    assert reporter["uses"] == (
        "google/osv-scanner-action/osv-reporter-action@0a65f82af05cd58cf587827b0bb0489548c18346"
    )
    assert "--fail-on-vuln=false" in reporter["with"]["scan-args"]
    assert "--new=results.json" in reporter["with"]["scan-args"]
    assert "--output=results.sarif" in reporter["with"]["scan-args"]
    artifact = steps["Store auditable OSV SARIF for 5 days"]
    assert artifact["uses"] == ("actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a")
    assert artifact["with"]["if-no-files-found"] == "error"
    upload = steps["Publish every finding in GitHub Code Scanning"]
    assert upload["uses"] == (
        "github/codeql-action/upload-sarif@b96794f015dfd88f77b49b1c93e0fa7110f94c63"
    )
    assert upload["with"]["sarif_file"] == "results.sarif"
    # Independent override must be empty, so the weekly inventory continues
    # reporting everything even when a scoped Cargo scanner config has
    # time-limited local exceptions.
    assert not (ROOT / "osv-scanner.toml").exists()
    config = ROOT / ".github/security/osv-full-inventory.toml"
    assert config.exists()
    assert tomllib.loads(config.read_text(encoding="utf-8")) == {}
    assert (ROOT / "src-tauri/osv-scanner.toml").exists()


def test_existing_rustsec_baseline_is_still_exact_and_not_ignored() -> None:
    baseline = json.loads(
        (ROOT / ".github/security/rustsec-baseline.json").read_text(encoding="utf-8")
    )
    items = baseline["advisories"]
    assert len(items) == 5
    assert {item["id"] for item in items} == {
        "RUSTSEC-2024-0370",
        "RUSTSEC-2024-0429",
        "RUSTSEC-2026-0370",
        "RUSTSEC-2026-0371",
        "RUSTSEC-2026-0372",
    }
    assert all(item["rationale"] and item["revisit"] for item in items)
    ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "scripts/check_rustsec_audit.py" in ci
    assert ".github/security/rustsec-baseline.json" in ci


def test_osv_action_has_a_single_explicit_approved_repository() -> None:
    policy = json.loads((ROOT / ".github/actions-policy.json").read_text(encoding="utf-8"))
    assert "google/osv-scanner-action" in policy["allowed_action_repositories"]
    assert policy["workflow_write_permissions"]["osv-inventory-weekly.yml"] == {
        "osv-full-inventory": ["security-events"],
    }
