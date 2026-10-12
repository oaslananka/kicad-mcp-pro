"""Keep signed Windows 10.0.7 targeted native CLI evidence source-bound."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = (
    ROOT / "docs/evidence/kicad-10-0-7/2026-10-12-main-windows-targeted-patch-regressions.json"
)
LINUX_EVIDENCE = (
    ROOT / "docs/evidence/kicad-10-0-7/2026-10-12-main-linux-targeted-patch-regressions.json"
)
AUDIT = ROOT / "docs/evidence/kicad-10-0-7/2026-10-12-feature-parity-audit.md"


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_windows_real_run_pins_exact_source_and_signed_installer_without_promotion() -> None:
    e = _read(EVIDENCE)
    assert e["schemaVersion"] == "kicad-107-windows-targeted-patch-regressions.v1"
    assert e["sourceRevision"] == "5d5324b1c90d65eebec545d7f83c455b05b6042b"
    assert e["runner"] == "windows-2025"
    assert e["kicadCliVersion"] == "10.0.7"
    assert e["workflowRunId"] == 38199126080
    assert e["artifactId"] == 11724038722
    assert e["artifactName"] == "kicad-10-0-7-windows-native"
    assert e["installer"] == {
        "version": "10.0.7",
        "sha256": "ce3881b6a9188eb34ac1ebaaec7651149e8a025206410addfb11a1a9656ecf95",
        "authenticode": "Valid",
        "shaCheckedBeforeExecution": True,
    }
    assert e["status"] == "three-targeted-windows-cli-regressions-pass"
    assert e["globalPromotionApproved"] is False
    assert e["latestVerifiedRetained"] == "10.0.6"
    assert e["nativeSchematicBomGuiQualified"] is False
    assert "windows-and-macos-schematic-editor-bom-export-field-and-cancel" in e["unqualified"]
    assert "autonomous-manufacturing-reference-board" in e["unqualified"]
    assert str(ROOT) not in EVIDENCE.read_text(encoding="utf-8")


def test_all_bounded_raw_report_digests_have_reviewed_fixed_names() -> None:
    reports = _read(EVIDENCE)["artifactSha256ByReport"]
    assert set(reports) == {
        "provenance.json",
        "erc-units.json",
        "flat-root-pdf.json",
        "gerber-drill-marks.json",
        "differential/summary.json",
    }
    assert all(len(h) == 64 and set(h) <= set("0123456789abcdef") for h in reports.values())


def test_windows_32_native_and_5_differentials_are_fail_closed() -> None:
    assert _read(EVIDENCE)["nativeCanary"] == {
        "expectedStepsPassed": 32,
        "totalSteps": 32,
        "failingFixtures": 0,
        "semanticMatches": 5,
        "semanticTotal": 5,
        "falsePass": 0,
        "falseFail": 0,
        "divergence": 0,
        "invalidInfrastructure": 0,
    }


@pytest.mark.parametrize(
    "name,upstream",
    [
        ("erc-json-unit-scale", "25582"),
        ("multi-root-schematic-plot", "25198"),
        ("gerber-drill-marks", "25532"),
    ],
)
def test_exactly_three_native_windows_patch_gates(name: str, upstream: str) -> None:
    gates = _read(EVIDENCE)["patchProbeScopes"]
    assert set(gates) == {"erc-json-unit-scale", "multi-root-schematic-plot", "gerber-drill-marks"}
    assert gates[name]["upstream"] == upstream
    assert gates[name]["status"] == "pass"


def test_windows_erc_coordinate_values_with_real_cross_platform_count_difference() -> None:
    e = _read(EVIDENCE)
    erc = e["patchProbeScopes"]["erc-json-unit-scale"]
    assert erc["symbol"] == "J1"
    assert erc["diagnostic"] == "footprint_link_issues"
    assert erc["violationCountEachUnit"] == 5
    assert (
        _read(LINUX_EVIDENCE)["patchProbeScopes"]["erc-json-unit-scale"]["violationCountEachUnit"]
        == 4
    )
    assert e["crossPlatformDifferences"]["ercViolationCountPerUnit"] == {"windows": 5, "linux": 4}
    for unit, scale in (("mm", 1), ("in", 1 / 25.4), ("mils", 1000 / 25.4)):
        for axis, mm in (("x", 15), ("y", 14)):
            assert erc["positions"][unit][axis] == pytest.approx(mm * scale, abs=0.001)


def test_windows_pdf_both_named_roots_independent_of_linux_page_order() -> None:
    e = _read(EVIDENCE)["patchProbeScopes"]["multi-root-schematic-plot"]
    linux = _read(LINUX_EVIDENCE)["patchProbeScopes"]["multi-root-schematic-plot"]
    assert e["pageCount"] == 2
    assert linux["pageCount"] == 2
    assert {(p["root"], p["title"]) for p in e["pages"]} == {
        ("FlatRoot1", "erc-power-pin-error"),
        ("FlatRoot2", "clean-led-kicad10"),
    }
    assert [p["root"] for p in e["pages"]] == ["FlatRoot1", "FlatRoot2"]
    assert [p["root"] for p in linux["pages"]] == ["FlatRoot2", "FlatRoot1"]


def test_windows_npth_and_control_geometry_preserved() -> None:
    e = _read(EVIDENCE)["patchProbeScopes"]["gerber-drill-marks"]
    assert e["savedDrillMarkStyle"] == "full"
    assert e["copperFlashCount"] == {"npth": 0, "pth": 1}
    assert e["npthDrillMm"] == 3.2
    assert e["npthLocationMm"] == {"x": 50, "y": 50}


def test_audit_limits_cross_platform_native_cli_to_documented_gates() -> None:
    doc = AUDIT.read_text(encoding="utf-8")
    assert EVIDENCE.name in doc
    assert LINUX_EVIDENCE.name in doc
    assert "**5** diagnoses per unit" in doc
    assert "**4** per unit" in doc
    assert "**Schematic Editor BOM GUI**" in doc
    assert "10.0.6" in doc
