"""Cross-surface courtyard DRC regressions for issue #496."""

from __future__ import annotations

from pathlib import Path

import pytest

from kicad_mcp.server import build_server
from kicad_mcp.tools import dfm
from tests.conftest import call_tool_payload, call_tool_text, read_resource_text


def _kicad_10_courtyard_report() -> dict[str, object]:
    return {
        "violations": [
            {
                "type": "courtyards_overlap",
                "uuid": "courtyard-1",
                "severity": "error",
                "description": "Courtyards overlap",
            },
            {
                "type": "pth_inside_courtyard",
                "uuid": "courtyard-2",
                "severity": "error",
                "description": "PTH inside courtyard",
            },
            {
                "type": "npth_inside_courtyard",
                "uuid": "courtyard-3",
                "severity": "warning",
                "description": "NPTH inside courtyard",
            },
        ],
        "unconnected_items": [],
    }


@pytest.mark.anyio
async def test_kicad_10_courtyard_findings_are_consistent_across_validation_surfaces(
    sample_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = _kicad_10_courtyard_report()

    def fake_run_drc(report_name: str) -> tuple[Path, dict[str, object], None]:
        return sample_project / "output" / report_name, report, None

    monkeypatch.setattr("kicad_mcp.tools.validation._run_drc_report", fake_run_drc)
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    drc_payload = await call_tool_payload(server, "run_drc", {})
    courtyard_text = await call_tool_text(server, "get_courtyard_violations", {})
    gate_text = await call_tool_text(server, "pcb_quality_gate", {})
    resource_text = await read_resource_text(server, "kicad://drc/latest")

    assert isinstance(drc_payload, dict)
    assert drc_payload["verdict"] == "FAIL"
    assert "Courtyard issues: 3" in drc_payload["text"]
    assert len(drc_payload["findings"]) == 3
    assert "Courtyard violations (3 total):" in courtyard_text
    assert "No courtyard violations were reported." not in courtyard_text
    assert "PCB quality gate: FAIL" in gate_text
    assert "Courtyard issues: 3" in gate_text
    assert "Courtyard issues: 3" in resource_text


def test_dfm_uses_the_same_kicad_10_courtyard_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = _kicad_10_courtyard_report()
    monkeypatch.setattr(
        dfm,
        "_run_drc_report",
        lambda _report_name: (Path("dfm_profile_check.json"), report, None),
    )
    monkeypatch.setattr(
        dfm,
        "_board_metrics",
        lambda: {
            "copper_layers": 2,
            "min_track_width_mm": 0.2,
            "min_via_drill_mm": 0.3,
            "min_via_diameter_mm": 0.6,
            "via_count": 4,
        },
    )

    lines = dfm._dfm_check_lines(dfm._load_profile("JLCPCB", "standard"))

    assert "- WARN: Courtyard issues: 3" in lines
    assert "- PASS: Courtyard issues: 0" not in lines


@pytest.mark.anyio
async def test_legacy_courtyard_field_remains_blocking_without_double_counting(
    sample_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    legacy_entry = {
        "uuid": "legacy-courtyard",
        "severity": "error",
        "description": "Legacy courtyard overlap",
    }
    report: dict[str, object] = {
        "violations": [],
        "unconnected_items": [],
        "items_not_passing_courtyard": [legacy_entry],
    }

    def fake_run_drc(report_name: str) -> tuple[Path, dict[str, object], None]:
        return sample_project / "output" / report_name, report, None

    monkeypatch.setattr("kicad_mcp.tools.validation._run_drc_report", fake_run_drc)
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    drc_payload = await call_tool_payload(server, "run_drc", {})
    gate_text = await call_tool_text(server, "pcb_quality_gate", {})

    assert isinstance(drc_payload, dict)
    assert drc_payload["verdict"] == "FAIL"
    assert "Violations: 0" in drc_payload["text"]
    assert "Courtyard issues: 1" in drc_payload["text"]
    assert len(drc_payload["findings"]) == 1
    assert "PCB quality gate: FAIL" in gate_text
    assert "Courtyard issues: 1" in gate_text
