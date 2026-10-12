"""Review a low-privilege weekly RustSec baseline drift detector."""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/rustsec-weekly.yml"
BASELINE = ROOT / ".github/security/rustsec-baseline.json"


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def test_only_main_default_branch_schedule_and_explicit_manual_dispatch() -> None:
    data = _workflow()
    events = data.get("on", data.get(True))
    assert events == {
        "schedule": [{"cron": "23 6 * * 3"}],
        "workflow_dispatch": None,
    }
    assert data["permissions"] == {"contents": "read"}
    assert data["concurrency"]["cancel-in-progress"] is False
    job = data["jobs"]["rustsec-drift"]
    assert job["if"] == "github.repository == 'oaslananka/kicad-mcp-pro'"
    assert job["runs-on"] == "ubuntu-24.04"
    assert job["timeout-minutes"] == 40
    assert "environment" not in job
    assert "permissions" not in job
    assert "schedule" in WORKFLOW.read_text(encoding="utf-8")


def test_pinned_checkout_scanner_and_no_workflow_write_or_secret_access() -> None:
    job = _workflow()["jobs"]["rustsec-drift"]
    steps = job["steps"]
    assert len(steps) == 3
    checkout = steps[0]
    assert checkout["uses"] == ("actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1")
    assert checkout["with"]["persist-credentials"] is False
    assert steps[1]["run"] == "cargo install cargo-audit --version 0.22.2 --locked"
    assert "secrets." not in str(job)
    assert not any("continue-on-error" in step for step in steps)
    assert BASELINE.is_file()


def test_alerts_fail_closed_without_ignores_or_baseline_mutation() -> None:
    script = _workflow()["jobs"]["rustsec-drift"]["steps"][2]
    assert script["working-directory"] == "src-tauri"
    assert script["shell"] == "bash"
    text = script["run"]
    assert "set -euo pipefail" in text
    assert "cargo audit --json --no-yanked" in text
    assert "--baseline ../.github/security/rustsec-baseline.json" in text
    assert '--cargo-audit-version "$audit_version"' in text
    assert "python3 ../scripts/check_rustsec_audit.py" in text
    assert "trap 'rm -f ../rustsec-weekly-audit.json' EXIT" in text
    assert text.index("cargo audit --json") < text.index(
        "python3 ../scripts/check_rustsec_audit.py"
    )
    assert "--ignore" not in text
    assert "cargo audit fix" not in text
    assert "cargo update" not in text
    assert "|| true" not in text
    assert "audit_status > 1" in text
