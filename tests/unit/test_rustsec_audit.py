from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.check_rustsec_audit import RustSecAuditError, validate_report


def _finding(advisory_id: str, package: str, version: str) -> dict[str, object]:
    return {
        "advisory": {"id": advisory_id, "title": "ignored mutable title"},
        "package": {"name": package, "version": version},
    }


def _baseline(path: Path) -> Path:
    payload = {
        "schema_version": 1,
        "cargo_audit_version": "0.22.2",
        "advisories": [
            {
                "id": "RUSTSEC-2024-0429",
                "package": "glib",
                "version": "0.18.5",
                "category": "unsound",
                "rationale": "Transitive through Tauri GTK3; affected API is not called directly.",
                "revisit": "Re-evaluate when upstream Tauri moves off GTK3/glib 0.18.",
                "source": "https://rustsec.org/advisories/RUSTSEC-2024-0429",
            },
            {
                "id": "RUSTSEC-2024-0419",
                "package": "gtk3-macros",
                "version": "0.18.2",
                "category": "unmaintained",
                "rationale": "Transitive through Tauri's supported Linux GTK3 stack.",
                "revisit": "Re-evaluate when upstream Tauri supports a non-GTK3 Linux stack.",
                "source": "https://rustsec.org/advisories/RUSTSEC-2024-0419",
            },
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _report(path: Path) -> Path:
    payload = {
        "vulnerabilities": {"list": []},
        "warnings": {
            "unsound": [_finding("RUSTSEC-2024-0429", "glib", "0.18.5")],
            "unmaintained": [_finding("RUSTSEC-2024-0419", "gtk3-macros", "0.18.2")],
        },
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_validator_accepts_exact_reviewed_rustsec_baseline(tmp_path: Path) -> None:
    validate_report(
        report_path=_report(tmp_path / "audit.json"),
        baseline_path=_baseline(tmp_path / "baseline.json"),
        cargo_audit_version="0.22.2",
    )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("id", "RUSTSEC-2099-9999", "unexpected RustSec findings"),
        ("name", "glib-sys", "unexpected RustSec findings"),
        ("version", "0.19.0", "unexpected RustSec findings"),
    ],
)
def test_validator_fails_closed_on_unreviewed_finding_drift(
    tmp_path: Path,
    field: str,
    value: str,
    message: str,
) -> None:
    report = json.loads(_report(tmp_path / "audit.json").read_text(encoding="utf-8"))
    finding = report["warnings"]["unsound"][0]
    if field == "id":
        finding["advisory"]["id"] = value
    else:
        finding["package"][field] = value
    report_path = tmp_path / "drift.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")

    with pytest.raises(RustSecAuditError, match=message):
        validate_report(
            report_path=report_path,
            baseline_path=_baseline(tmp_path / "baseline.json"),
            cargo_audit_version="0.22.2",
        )


def test_validator_rejects_stale_baseline_entries(tmp_path: Path) -> None:
    report = json.loads(_report(tmp_path / "audit.json").read_text(encoding="utf-8"))
    report["warnings"] = {}
    report_path = tmp_path / "missing.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")

    with pytest.raises(RustSecAuditError, match="stale RustSec baseline entries"):
        validate_report(
            report_path=report_path,
            baseline_path=_baseline(tmp_path / "baseline.json"),
            cargo_audit_version="0.22.2",
        )


def test_validator_requires_review_metadata_and_exact_tool_version(tmp_path: Path) -> None:
    baseline_path = _baseline(tmp_path / "baseline.json")
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    baseline["advisories"][0]["revisit"] = ""
    baseline_path.write_text(json.dumps(baseline), encoding="utf-8")

    with pytest.raises(RustSecAuditError, match="review metadata"):
        validate_report(
            report_path=_report(tmp_path / "audit.json"),
            baseline_path=baseline_path,
            cargo_audit_version="0.22.2",
        )

    with pytest.raises(RustSecAuditError, match="cargo-audit version"):
        validate_report(
            report_path=_report(tmp_path / "audit.json"),
            baseline_path=_baseline(tmp_path / "baseline-2.json"),
            cargo_audit_version="0.23.0",
        )


def test_gui_ci_runs_pinned_rustsec_audit_on_linux() -> None:
    root = Path(__file__).resolve().parents[2]
    workflow = (root / ".github" / "workflows" / "gui-ci.yml").read_text(encoding="utf-8")

    assert "cargo install cargo-audit --version 0.22.2 --locked" in workflow
    assert "cargo audit --json --no-yanked" in workflow
    assert "scripts/check_rustsec_audit.py" in workflow
    assert "rustsec-audit:" in workflow
    assert ".github/security/rustsec-baseline.json" in workflow


def test_repository_baseline_tracks_exact_scorecard_rustsec_inventory() -> None:
    root = Path(__file__).resolve().parents[2]
    baseline = json.loads(
        (root / ".github" / "security" / "rustsec-baseline.json").read_text(encoding="utf-8")
    )
    expected_ids = {
        "RUSTSEC-2024-0370",
        "RUSTSEC-2024-0411",
        "RUSTSEC-2024-0412",
        "RUSTSEC-2024-0413",
        "RUSTSEC-2024-0414",
        "RUSTSEC-2024-0415",
        "RUSTSEC-2024-0416",
        "RUSTSEC-2024-0417",
        "RUSTSEC-2024-0418",
        "RUSTSEC-2024-0419",
        "RUSTSEC-2024-0420",
        "RUSTSEC-2024-0429",
        "RUSTSEC-2025-0075",
        "RUSTSEC-2025-0080",
        "RUSTSEC-2025-0081",
        "RUSTSEC-2025-0098",
        "RUSTSEC-2025-0100",
    }
    advisories = baseline["advisories"]
    assert baseline["cargo_audit_version"] == "0.22.2"
    assert {entry["id"] for entry in advisories} == expected_ids
    assert len(advisories) == len(expected_ids)
    assert {entry["category"] for entry in advisories} == {"unmaintained", "unsound"}
    assert all(entry["rationale"] and entry["revisit"] and entry["source"] for entry in advisories)


def test_cargo_audit_config_surfaces_informational_rustsec_findings() -> None:
    root = Path(__file__).resolve().parents[2]
    config = (root / "src-tauri" / ".cargo" / "audit.toml").read_text(encoding="utf-8")
    assert 'informational_warnings = ["unmaintained", "unsound"]' in config
