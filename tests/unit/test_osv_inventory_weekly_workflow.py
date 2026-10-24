"""OSV multi-ecosystem monitoring does not hide advisories or weaken PR gates."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/osv-inventory-weekly.yml"


def test_osv_weekly_inventory_is_pinned_and_uploads_all_findings() -> None:
    data = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert data["permissions"]["contents"] == "read"
    assert data["permissions"]["actions"] == "read"
    assert data["permissions"]["security-events"] == "write"
    assert data["concurrency"]["cancel-in-progress"] is False
    assert data[True]["schedule"] and data[True]["workflow_dispatch"] is None
    job = data["jobs"]["osv-full-inventory"]
    assert job["if"] == "github.repository == 'oaslananka/kicad-mcp-pro'"
    assert job["uses"] == (
        "google/osv-scanner-action/.github/workflows/osv-scanner-reusable.yml@"
        "b1d267aea5211fa648d9d442fa64b90dbdcbdd36"
    )
    options = job["with"]
    assert options["runs-on"] == "ubuntu-24.04"
    assert options["scan-args"].strip().splitlines() == ["-r", "./"]
    assert options["upload-sarif"] is True
    # Known five upstream advisories remain visible, but the weekly reporting
    # run is non-gating. Required RustSec PR audit stays strict.
    assert options["fail-on-vuln"] is False
    assert not (ROOT / "osv-scanner.toml").exists()
    assert not (ROOT / "src-tauri/osv-scanner.toml").exists()


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
