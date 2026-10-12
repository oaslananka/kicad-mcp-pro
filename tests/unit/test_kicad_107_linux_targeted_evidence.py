"""Ensure source-bound, bounded physical Linux KiCad 10.0.7 evidence remains honest."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "docs/evidence/kicad-10-0-7/2026-10-12-main-linux-targeted-patch-regressions.json"
AUDIT = ROOT / "docs/evidence/kicad-10-0-7/2026-10-12-feature-parity-audit.md"


def _evidence() -> dict:
    return json.loads(EVIDENCE.read_text(encoding="utf-8"))


def test_physical_linux_native_results_are_source_bound_and_not_promoted() -> None:
    evidence = _evidence()
    assert evidence["schemaVersion"] == "kicad-107-linux-targeted-patch-regressions.v1"
    assert evidence["sourceRevision"] == "8e31947f9e136ea1e33d07e89d9cd599a3263592"
    assert evidence["nativeHostClass"] == "ubuntu-24.04.5-linux-x86_64"
    assert evidence["nativeCliVersion"] == "10.0.7"
    assert evidence["status"] == "three-targeted-linux-cli-regressions-pass"
    assert evidence["fixtureIsolation"] == "temporary-copies-and-outputs-deleted"
    assert evidence["sourceTreeCleanAfterRun"] is True
    assert evidence["globalPromotionApproved"] is False
    assert evidence["latestVerifiedRetained"] == "10.0.6"
    assert evidence["macosWindowsBomGuiQualified"] is False
    assert "native-windows-macos-schematic-editor-bom-gui" in evidence["outstandingScopes"]
    assert "reference-board-manufacturing-not-qualified" in evidence["outstandingScopes"]
    assert str(ROOT) not in EVIDENCE.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("name", "upstream"),
    [
        ("erc-json-unit-scale", "25582"),
        ("multi-root-schematic-plot", "25198"),
        ("gerber-drill-marks", "25532"),
    ],
)
def test_only_three_actual_linux_cli_patch_contracts_pass(name: str, upstream: str) -> None:
    evidence = _evidence()
    assert set(evidence["patchProbeScopes"]) == {
        "erc-json-unit-scale",
        "multi-root-schematic-plot",
        "gerber-drill-marks",
    }
    assert evidence["patchProbeScopes"][name]["status"] == "pass"
    assert evidence["patchProbeScopes"][name]["upstream"] == upstream


def test_erc_j1_positions_convert_from_known_mm_coordinates() -> None:
    report = _evidence()["patchProbeScopes"]["erc-json-unit-scale"]
    assert report["diagnostic"] == "footprint_link_issues"
    assert report["symbol"] == "J1"
    assert report["violationCountEachUnit"] == 4
    for unit, scale in (("mm", 1), ("in", 1 / 25.4), ("mils", 1000 / 25.4)):
        for axis, millimetres in (("x", 15), ("y", 14)):
            assert report["positions"][unit][axis] == pytest.approx(millimetres * scale, abs=0.001)


def test_pdf_contains_two_unique_real_top_level_roots() -> None:
    data = _evidence()["patchProbeScopes"]["multi-root-schematic-plot"]
    assert data["pageCount"] == 2
    assert {(p["root"], p["title"]) for p in data["pages"]} == {
        ("FlatRoot1", "erc-power-pin-error"),
        ("FlatRoot2", "clean-led-kicad10"),
    }


def test_gerber_preserves_hole_but_no_false_npth_copper_flash() -> None:
    data = _evidence()["patchProbeScopes"]["gerber-drill-marks"]
    assert data["savedDrillMarkStyle"] == "full"
    assert data["copperFlashCount"] == {"npth": 0, "pth": 1}
    assert data["npthDrillMm"] == 3.2
    assert data["npthLocationMm"] == {"x": 50, "y": 50}


def test_source_fixture_sha256_is_recomputed_from_committed_fixture() -> None:
    evidence = _evidence()
    fixtures = evidence["sourceFixtureSha256"]
    assert len(fixtures) == 4
    # Manifest keys are platform-neutral POSIX-style paths even on Windows.
    # Keep their serialized identifiers as fixed strings, not str(Path),
    # which would introduce backslashes on Windows runners.
    allowed_paths = (
        "packages/kicad-fixtures/fixtures/erc-power-pin-error/erc-power-pin-error.kicad_sch",
        "packages/kicad-fixtures/fixtures/clean-led-kicad10/clean-led-kicad10.kicad_sch",
        "tests/fixtures/kicad-10-0-7-drill-marks/npth-stored-full-drill.kicad_pcb",
        "tests/fixtures/kicad-10-0-7-drill-marks/pth-stored-full-drill.kicad_pcb",
    )
    assert set(fixtures) == set(allowed_paths)
    for rel in allowed_paths:
        source = ROOT / rel
        assert source.is_file()
        assert hashlib.sha256(source.read_bytes()).hexdigest() == fixtures[rel]


def test_audit_explicitly_limits_native_linux_acceptance() -> None:
    audit = AUDIT.read_text(encoding="utf-8")
    assert "2026-10-12-main-linux-targeted-patch-regressions.json" in audit
    assert "three targeted **Linux CLI** subgates" in audit
    assert "**pending**" in audit
    assert "10.0.6" in audit
