"""Integration tests for validation DRC exclusion and ERC rule severity tools."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from kicad_mcp.server import build_server
from kicad_mcp.tools.gates import GateOutcome
from tests.conftest import call_tool_payload, call_tool_text


@pytest.mark.anyio
async def test_drc_list_exclusions_empty(sample_project: Path, monkeypatch) -> None:
    """drc_list_exclusions should return empty list when no exclusions exist."""
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    result = await call_tool_text(server, "drc_list_exclusions", {})
    assert '"exclusions": []' in result
    assert '"count": 0' in result


@pytest.mark.anyio
async def test_drc_add_exclusion_creates_file(sample_project: Path, monkeypatch) -> None:
    """drc_add_exclusion should create exclusions file with violation UUIDs."""

    def fake_run_drc(report_name: str) -> tuple[Path, dict | None, str | None]:
        report_path = sample_project / "output" / report_name
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report = {
            "violations": [
                {
                    "uuid": "abc123",
                    "severity": "error",
                    "description": "Clearance violation",
                },
                {
                    "uuid": "def456",
                    "severity": "warning",
                    "description": "Silk overlap",
                },
            ]
        }
        report_path.write_text(json.dumps(report), encoding="utf-8")
        return report_path, report, None

    monkeypatch.setattr("kicad_mcp.tools.validation._run_drc_report", fake_run_drc)
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    result = await call_tool_text(server, "drc_add_exclusion", {"reason": "Fabricator approved"})
    assert "Added 2 DRC exclusion(s)" in result

    listing = await call_tool_text(server, "drc_list_exclusions", {})
    assert "abc123" in listing
    assert "def456" in listing
    assert '"count": 2' in listing


@pytest.mark.anyio
async def test_drc_add_exclusion_skips_duplicates(sample_project: Path, monkeypatch) -> None:
    """drc_add_exclusion should skip already-excluded UUIDs."""

    def fake_run_drc(report_name: str) -> tuple[Path, dict | None, str | None]:
        report_path = sample_project / "output" / report_name
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report = {
            "violations": [{"uuid": "abc123", "severity": "error", "description": "Clearance"}]
        }
        report_path.write_text(json.dumps(report), encoding="utf-8")
        return report_path, report, None

    monkeypatch.setattr("kicad_mcp.tools.validation._run_drc_report", fake_run_drc)
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    await call_tool_text(server, "drc_add_exclusion", {})
    result = await call_tool_text(server, "drc_add_exclusion", {})
    assert "Added 0 DRC exclusion(s)" in result
    assert "Total exclusions stored: 1" in result


@pytest.mark.anyio
async def test_drc_add_exclusion_no_violations(sample_project: Path, monkeypatch) -> None:
    """drc_add_exclusion should report when no violations exist."""

    def fake_run_drc(report_name: str) -> tuple[Path, dict | None, str | None]:
        report_path = sample_project / "output" / report_name
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report = {"violations": []}
        report_path.write_text(json.dumps(report), encoding="utf-8")
        return report_path, report, None

    monkeypatch.setattr("kicad_mcp.tools.validation._run_drc_report", fake_run_drc)
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    result = await call_tool_text(server, "drc_add_exclusion", {})
    assert "No DRC violations found" in result


@pytest.mark.anyio
async def test_drc_add_exclusion_drc_failure(sample_project: Path, monkeypatch) -> None:
    """drc_add_exclusion should report DRC run failure."""

    def fake_run_drc(report_name: str) -> tuple[Path, dict | None, str | None]:
        return sample_project / "output" / report_name, None, "DRC crashed"

    monkeypatch.setattr("kicad_mcp.tools.validation._run_drc_report", fake_run_drc)
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    result = await call_tool_text(server, "drc_add_exclusion", {})
    assert "Could not run DRC" in result


@pytest.mark.anyio
async def test_drc_remove_exclusion(sample_project: Path, monkeypatch) -> None:
    """drc_remove_exclusion should delete an exclusion by UUID."""

    def fake_run_drc(report_name: str) -> tuple[Path, dict | None, str | None]:
        report_path = sample_project / "output" / report_name
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report = {
            "violations": [{"uuid": "abc123", "severity": "error", "description": "Clearance"}]
        }
        report_path.write_text(json.dumps(report), encoding="utf-8")
        return report_path, report, None

    monkeypatch.setattr("kicad_mcp.tools.validation._run_drc_report", fake_run_drc)
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    await call_tool_text(server, "drc_add_exclusion", {})
    result = await call_tool_text(server, "drc_remove_exclusion", {"uuid": "abc123"})
    assert "Removed 1 DRC exclusion" in result

    listing = await call_tool_text(server, "drc_list_exclusions", {})
    assert '"count": 0' in listing


@pytest.mark.anyio
async def test_drc_remove_exclusion_missing_uuid(sample_project: Path) -> None:
    """drc_remove_exclusion should report when UUID is not found."""
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    result = await call_tool_text(server, "drc_remove_exclusion", {"uuid": "nonexistent"})
    assert "No exclusion found with UUID 'nonexistent'" in result


@pytest.mark.anyio
async def test_drc_validate_exclusions(sample_project: Path, monkeypatch) -> None:
    """drc_validate_exclusions should report valid and stale exclusions."""

    def fake_run_drc(report_name: str) -> tuple[Path, dict | None, str | None]:
        report_path = sample_project / "output" / report_name
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report = {
            "violations": [{"uuid": "abc123", "severity": "error", "description": "Clearance"}]
        }
        report_path.write_text(json.dumps(report), encoding="utf-8")
        return report_path, report, None

    monkeypatch.setattr("kicad_mcp.tools.validation._run_drc_report", fake_run_drc)
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    await call_tool_text(server, "drc_add_exclusion", {})
    # Add another exclusion for a violation that won't be in next DRC
    exclusions_path = sample_project / ".kicad-mcp" / "drc_exclusions.json"
    data = json.loads(exclusions_path.read_text(encoding="utf-8"))
    data["exclusions"].append(
        {
            "uuid": "stale789",
            "reason": "Old",
            "created": "2024-01-01T00:00:00",
            "description": "Gone",
        }
    )
    exclusions_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    result = await call_tool_text(server, "drc_validate_exclusions", {})
    assert '"valid_exclusions": 1' in result
    assert '"stale_exclusions": 1' in result
    assert '"total_exclusions": 2' in result


@pytest.mark.anyio
async def test_drc_validate_exclusions_empty(sample_project: Path) -> None:
    """drc_validate_exclusions should report when no exclusions exist."""
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    result = await call_tool_text(server, "drc_validate_exclusions", {})
    assert "No DRC exclusions stored" in result


@pytest.mark.anyio
async def test_drc_validate_exclusions_drc_failure(sample_project: Path, monkeypatch) -> None:
    """drc_validate_exclusions should report DRC run failure."""

    def fake_run_drc(report_name: str) -> tuple[Path, dict | None, str | None]:
        return sample_project / "output" / report_name, None, "DRC failed"

    monkeypatch.setattr("kicad_mcp.tools.validation._run_drc_report", fake_run_drc)
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    # Create empty exclusions file
    exclusions_path = sample_project / ".kicad-mcp" / "drc_exclusions.json"
    exclusions_path.parent.mkdir(parents=True, exist_ok=True)
    exclusions_path.write_text(json.dumps({"exclusions": []}, indent=2), encoding="utf-8")

    result = await call_tool_text(server, "drc_validate_exclusions", {})
    assert "No DRC exclusions stored" in result


@pytest.mark.anyio
async def test_erc_list_rules(sample_project: Path) -> None:
    """erc_list_rules should return all known ERC rules with severities."""
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    result = await call_tool_text(server, "erc_list_rules", {})
    assert "power_pin_not_driven" in result
    assert "pin_not_connected" in result
    assert "duplicate_reference" in result
    assert "error" in result


@pytest.mark.anyio
async def test_erc_set_rule_severity(sample_project: Path) -> None:
    """erc_set_rule_severity should update a rule's severity."""
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    result = await call_tool_text(
        server,
        "erc_set_rule_severity",
        {"rule_name": "pin_not_connected", "severity": "warning"},
    )
    assert "ERC rule 'pin_not_connected' severity set to 'warning'" in result

    listing = await call_tool_text(server, "erc_list_rules", {})
    assert '"name": "pin_not_connected"' in listing
    assert '"severity": "warning"' in listing


@pytest.mark.anyio
async def test_erc_set_rule_severity_invalid_severity(sample_project: Path) -> None:
    """erc_set_rule_severity should reject invalid severity values."""
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    result = await call_tool_text(
        server,
        "erc_set_rule_severity",
        {"rule_name": "pin_not_connected", "severity": "critical"},
    )
    assert "Severity must be one of" in result


@pytest.mark.anyio
async def test_erc_set_rule_severity_unknown_rule(sample_project: Path) -> None:
    """erc_set_rule_severity should reject unknown rule names."""
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    result = await call_tool_text(
        server,
        "erc_set_rule_severity",
        {"rule_name": "unknown_rule", "severity": "warning"},
    )
    assert "Unknown ERC rule 'unknown_rule'" in result


@pytest.mark.anyio
async def test_erc_reset_rules_single(sample_project: Path) -> None:
    """erc_reset_rules should reset a single rule to default."""
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    await call_tool_text(
        server,
        "erc_set_rule_severity",
        {"rule_name": "pin_not_connected", "severity": "warning"},
    )
    result = await call_tool_text(server, "erc_reset_rules", {"rule_name": "pin_not_connected"})
    assert "ERC rule 'pin_not_connected' reset to default severity (error)" in result

    listing = await call_tool_text(server, "erc_list_rules", {})
    assert '"name": "pin_not_connected"' in listing
    assert '"severity": "error"' in listing


@pytest.mark.anyio
async def test_erc_reset_rules_all(sample_project: Path) -> None:
    """erc_reset_rules should reset all rules to default."""
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    await call_tool_text(
        server,
        "erc_set_rule_severity",
        {"rule_name": "pin_not_connected", "severity": "warning"},
    )
    await call_tool_text(
        server,
        "erc_set_rule_severity",
        {"rule_name": "power_pin_not_driven", "severity": "ignore"},
    )
    result = await call_tool_text(server, "erc_reset_rules", {})
    assert "All" in result
    assert "ERC rules reset to default severity (error)" in result

    listing = await call_tool_text(server, "erc_list_rules", {})
    data = json.loads(listing)
    for rule in data["rules"]:
        assert rule["severity"] == "error"


@pytest.mark.anyio
async def test_erc_reset_rules_unknown_rule(sample_project: Path) -> None:
    """erc_reset_rules should reject unknown rule names."""
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    result = await call_tool_text(server, "erc_reset_rules", {"rule_name": "unknown_rule"})
    assert "Unknown ERC rule 'unknown_rule'" in result


@pytest.mark.anyio
async def test_validate_silk_to_pad_no_violations(sample_project: Path, monkeypatch) -> None:
    """validate_silk_to_pad should report when no silk-to-pad violations exist."""

    def fake_run_drc(report_name: str) -> tuple[Path, dict | None, str | None]:
        report_path = sample_project / "output" / report_name
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report = {
            "violations": [
                {"severity": "error", "description": "Clearance violation", "uuid": "u1"}
            ]
        }
        report_path.write_text(json.dumps(report), encoding="utf-8")
        return report_path, report, None

    monkeypatch.setattr("kicad_mcp.tools.validation._run_drc_report", fake_run_drc)
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    result = await call_tool_text(server, "get_silk_to_pad_violations", {})
    assert "No silk-to-pad violations were reported" in result


@pytest.mark.anyio
async def test_validate_silk_to_pad_with_violations(sample_project: Path, monkeypatch) -> None:
    """validate_silk_to_pad should report silk-to-pad violations."""

    def fake_run_drc(report_name: str) -> tuple[Path, dict | None, str | None]:
        report_path = sample_project / "output" / report_name
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report = {
            "violations": [
                {
                    "severity": "error",
                    "description": "Silk screen overlap pad",
                    "uuid": "u1",
                },
                {
                    "severity": "warning",
                    "description": "silk to pad clearance",
                    "uuid": "u2",
                },
            ]
        }
        report_path.write_text(json.dumps(report), encoding="utf-8")
        return report_path, report, None

    monkeypatch.setattr("kicad_mcp.tools.validation._run_drc_report", fake_run_drc)
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    result = await call_tool_text(server, "get_silk_to_pad_violations", {})
    assert "Silk-to-pad violations" in result
    assert "Silk screen overlap pad" in result
    assert "silk to pad clearance" in result


@pytest.mark.anyio
async def test_schematic_quality_gate_pass(sample_project: Path, monkeypatch) -> None:
    """schematic_quality_gate should report PASS for clean schematic."""

    def fake_run_erc(report_name: str) -> tuple[Path, dict | None, str | None]:
        report_path = sample_project / "output" / report_name
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report = {"sheets": [{"path": "/", "violations": []}]}
        report_path.write_text(json.dumps(report), encoding="utf-8")
        return report_path, report, None

    monkeypatch.setattr("kicad_mcp.tools.validation._run_erc_report", fake_run_erc)
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    result = await call_tool_text(server, "schematic_quality_gate", {})
    assert "Schematic quality gate: PASS" in result


@pytest.mark.anyio
async def test_schematic_quality_gate_ignores_empty_child_sheet_erc(
    sample_project: Path,
    monkeypatch,
) -> None:
    """Empty child-sheet placeholders should not hard-fail schematic quality."""

    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})
    await call_tool_text(
        server,
        "sch_create_sheet",
        {
            "name": "Future IO",
            "filename": "future_io.kicad_sch",
            "x_mm": 50.8,
            "y_mm": 50.8,
        },
    )

    def fake_run_erc(report_name: str) -> tuple[Path, dict | None, str | None]:
        report_path = sample_project / "output" / report_name
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report = {
            "sheets": [
                {
                    "path": "Future IO",
                    "violations": [
                        {
                            "severity": "error",
                            "type": "pin_not_connected",
                            "description": "Placeholder child sheet has no real circuit yet",
                        }
                    ],
                }
            ]
        }
        report_path.write_text(json.dumps(report), encoding="utf-8")
        return report_path, report, None

    monkeypatch.setattr("kicad_mcp.tools.validation._run_erc_report", fake_run_erc)

    result = await call_tool_text(server, "schematic_quality_gate", {})

    assert "Schematic quality gate: PASS" in result
    assert "ERC violations: 0" in result
    assert "Ignored empty child-sheet ERC violations: 1" in result


@pytest.mark.anyio
async def test_schematic_quality_gate_fail(sample_project: Path, monkeypatch) -> None:
    """schematic_quality_gate should report FAIL for schematic with violations."""

    def fake_run_erc(report_name: str) -> tuple[Path, dict | None, str | None]:
        report_path = sample_project / "output" / report_name
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report = {
            "sheets": [
                {
                    "path": "/",
                    "violations": [
                        {
                            "severity": "error",
                            "type": "pin_not_connected",
                            "description": "Pin not connected",
                        }
                    ],
                }
            ]
        }
        report_path.write_text(json.dumps(report), encoding="utf-8")
        return report_path, report, None

    monkeypatch.setattr("kicad_mcp.tools.validation._run_erc_report", fake_run_erc)
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    result = await call_tool_text(server, "schematic_quality_gate", {})
    assert "Schematic quality gate: FAIL" in result
    assert "ERC violations: 1" in result


@pytest.mark.anyio
async def test_connectivity_gate_joins_same_named_labels(sample_project: Path, monkeypatch) -> None:
    """Same-named labels represent one net even when drawn at separate points."""

    def fake_run_erc(report_name: str) -> tuple[Path, dict | None, str | None]:
        report_path = sample_project / "output" / report_name
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report = {"sheets": [{"path": "/", "violations": []}]}
        report_path.write_text(json.dumps(report), encoding="utf-8")
        return report_path, report, None

    monkeypatch.setattr("kicad_mcp.tools.validation._run_erc_report", fake_run_erc)

    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})
    await call_tool_text(
        server,
        "sch_build_circuit",
        {
            "symbols": [
                {
                    "library": "Device",
                    "symbol_name": "R",
                    "reference": "R1",
                    "value": "10k",
                    "footprint": "Resistor_SMD:R_0805",
                    "x_mm": 50.8,
                    "y_mm": 50.8,
                }
            ],
            "labels": [
                {"name": "GND", "x_mm": 48.26, "y_mm": 50.8},
                {"name": "3V3_DIG", "x_mm": 53.34, "y_mm": 50.8},
                {"name": "3V3_DIG", "x_mm": 101.6, "y_mm": 101.6},
            ],
            "wires": [{"x1_mm": 101.6, "y1_mm": 101.6, "x2_mm": 104.14, "y2_mm": 101.6}],
        },
    )

    result = await call_tool_text(server, "schematic_connectivity_gate", {})

    assert "Schematic connectivity quality gate: PASS" in result
    assert "Dangling label groups: 0" in result


@pytest.mark.anyio
async def test_pcb_quality_gate_pass(sample_project: Path, monkeypatch) -> None:
    """pcb_quality_gate should report PASS for clean PCB."""

    def fake_run_drc(report_name: str) -> tuple[Path, dict | None, str | None]:
        report_path = sample_project / "output" / report_name
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report = {
            "violations": [],
            "unconnected_items": [],
            "items_not_passing_courtyard": [],
        }
        report_path.write_text(json.dumps(report), encoding="utf-8")
        return report_path, report, None

    monkeypatch.setattr("kicad_mcp.tools.validation._run_drc_report", fake_run_drc)
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    result = await call_tool_text(server, "pcb_quality_gate", {})
    assert "PCB quality gate: PASS" in result


@pytest.mark.anyio
async def test_pcb_quality_gate_fail(sample_project: Path, monkeypatch) -> None:
    """pcb_quality_gate should report FAIL for PCB with violations."""

    def fake_run_drc(report_name: str) -> tuple[Path, dict | None, str | None]:
        report_path = sample_project / "output" / report_name
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report = {
            "violations": [{"severity": "error", "type": "clearance", "description": "Clearance"}],
            "unconnected_items": [{"severity": "error", "description": "NET1"}],
            "items_not_passing_courtyard": [],
        }
        report_path.write_text(json.dumps(report), encoding="utf-8")
        return report_path, report, None

    monkeypatch.setattr("kicad_mcp.tools.validation._run_drc_report", fake_run_drc)
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    result = await call_tool_text(server, "pcb_quality_gate", {})
    assert "PCB quality gate: FAIL" in result
    assert "DRC violations: 1" in result
    assert "Unconnected items: 1" in result


@pytest.mark.anyio
async def test_manufacturing_quality_gate(sample_project: Path, monkeypatch) -> None:
    """manufacturing_quality_gate should evaluate DFM checks."""

    def fake_run_drc(report_name: str) -> tuple[Path, dict | None, str | None]:
        report_path = sample_project / "output" / report_name
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report = {
            "violations": [],
            "unconnected_items": [],
            "items_not_passing_courtyard": [],
        }
        report_path.write_text(json.dumps(report), encoding="utf-8")
        return report_path, report, None

    monkeypatch.setattr("kicad_mcp.tools.validation._run_drc_report", fake_run_drc)
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    result = await call_tool_text(server, "manufacturing_quality_gate", {"profile": "JLCPCB"})
    assert "Manufacturing quality gate" in result


@pytest.mark.anyio
async def test_footprint_parity_gate(sample_project: Path, monkeypatch) -> None:
    """footprint_parity_gate should compare schematic and PCB references."""
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    result = await call_tool_text(server, "validate_footprints_vs_schematic", {})
    assert "Footprint versus schematic comparison" in result


@pytest.mark.anyio
async def test_pcb_transfer_quality_gate_no_project() -> None:
    """pcb_transfer_quality_gate should handle missing project gracefully."""
    server = build_server("full")
    result = await call_tool_text(server, "pcb_transfer_quality_gate", {})
    assert "PCB transfer quality gate" in result or "No project" in result


@pytest.mark.anyio
async def test_run_drc_tool(sample_project: Path, monkeypatch) -> None:
    """run_drc should execute DRC and return summary."""

    def fake_run_drc(report_name: str) -> tuple[Path, dict | None, str | None]:
        report_path = sample_project / "output" / report_name
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report = {
            "violations": [{"severity": "error", "type": "clearance", "description": "Clearance"}],
            "unconnected_items": [],
            "items_not_passing_courtyard": [],
        }
        report_path.write_text(json.dumps(report), encoding="utf-8")
        return report_path, report, None

    monkeypatch.setattr("kicad_mcp.tools.validation._run_drc_report", fake_run_drc)
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    result = await call_tool_text(server, "run_drc", {})
    assert "DRC summary" in result


@pytest.mark.anyio
async def test_run_erc_tool(sample_project: Path, monkeypatch) -> None:
    """run_erc should execute ERC and return summary."""

    def fake_run_erc(report_name: str) -> tuple[Path, dict | None, str | None]:
        report_path = sample_project / "output" / report_name
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report = {
            "sheets": [
                {
                    "path": "/",
                    "violations": [
                        {
                            "severity": "error",
                            "type": "pin_not_connected",
                            "description": "Pin not connected",
                        }
                    ],
                }
            ]
        }
        report_path.write_text(json.dumps(report), encoding="utf-8")
        return report_path, report, None

    monkeypatch.setattr("kicad_mcp.tools.validation._run_erc_report", fake_run_erc)
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    result = await call_tool_text(server, "run_erc", {})
    assert "ERC summary" in result
    assert "Pin not connected" in result


@pytest.mark.anyio
async def test_project_signoff_report_is_unverified_without_intent(
    sample_project: Path,
) -> None:
    """The project_signoff_report tool renders a verdict and is UNVERIFIED (never a
    silent PASS) when no design intent is declared (P5-T3)."""
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    result = await call_tool_text(server, "project_signoff_report", {})

    assert "Manufacturing sign-off:" in result
    assert "UNVERIFIED" in result


def _clean_drc_report(report_path: Path) -> tuple[Path, dict[str, object] | None, str | None]:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "violations": [],
        "unconnected_items": [],
        "items_not_passing_courtyard": [],
    }
    report_path.write_text(json.dumps(report), encoding="utf-8")
    return report_path, report, None


def _clean_erc_report(report_path: Path) -> tuple[Path, dict[str, object] | None, str | None]:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report = {"sheets": [{"path": "/", "violations": []}]}
    report_path.write_text(json.dumps(report), encoding="utf-8")
    return report_path, report, None


@pytest.mark.anyio
async def test_project_release_readiness_fails_closed_without_release_artifacts(
    sample_project: Path,
    monkeypatch,
) -> None:
    def fake_run_drc(report_name: str) -> tuple[Path, dict[str, object] | None, str | None]:
        return _clean_drc_report(sample_project / "output" / report_name)

    def fake_run_erc(report_name: str) -> tuple[Path, dict[str, object] | None, str | None]:
        return _clean_erc_report(sample_project / "output" / report_name)

    monkeypatch.setattr("kicad_mcp.tools.validation._run_drc_report", fake_run_drc)
    monkeypatch.setattr("kicad_mcp.tools.validation._run_erc_report", fake_run_erc)
    monkeypatch.setattr(
        "kicad_mcp.tools.validation._evaluate_project_gate",
        lambda manufacturer=None, tier=None: [
            GateOutcome(
                name="Manufacturing",
                status="PASS",
                summary="DFM checks passed.",
                details=["Profile: JLCPCB / standard"],
            )
        ],
    )
    monkeypatch.setattr(
        "kicad_mcp.tools.library._schematic_component_rows",
        lambda: [
            {
                "reference": "R1",
                "value": "10k",
                "footprint": "Resistor_SMD:R_0603_1608Metric",
                "lib_id": "Device:R",
                "lcsc": "C25804",
                "mpn": "RC0603FR-0710KL",
                "manufacturer": "Yageo",
                "populate": "Populate",
            }
        ],
    )

    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    result = await call_tool_payload(server, "project_release_readiness", {})

    assert result["verdict"] == "FAIL"
    assert result["drc"]["path"].endswith("release_readiness_drc.json")
    assert result["erc"]["path"].endswith("release_readiness_erc.json")
    assert result["artifacts"]["available"] is False
    assert result["manifest"]["available"] is False
    assert any(
        "Archive BOM, pick-and-place, and manufacturing release artifacts" in item
        for item in result["approval_checklist"]
    )


@pytest.mark.anyio
async def test_project_release_readiness_exports_markdown_when_evidence_is_complete(
    sample_project: Path,
    monkeypatch,
) -> None:
    output_dir = sample_project / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "bom.csv").write_text("ref,mpn\nR1,RC0603FR-0710KL\n", encoding="utf-8")
    (output_dir / "board-pos.csv").write_text("ref,x,y,rot\nR1,0,0,0\n", encoding="utf-8")
    (output_dir / "fabrication.pdf").write_text("placeholder", encoding="utf-8")
    (output_dir / "manifest.json").write_text(
        json.dumps({"content_hash": "abc123", "files": [{"filename": "bom.csv"}]}),
        encoding="utf-8",
    )
    (output_dir / "MANIFEST.txt").write_text("manifest", encoding="utf-8")

    def fake_run_drc(report_name: str) -> tuple[Path, dict[str, object] | None, str | None]:
        return _clean_drc_report(output_dir / report_name)

    def fake_run_erc(report_name: str) -> tuple[Path, dict[str, object] | None, str | None]:
        return _clean_erc_report(output_dir / report_name)

    monkeypatch.setattr("kicad_mcp.tools.validation._run_drc_report", fake_run_drc)
    monkeypatch.setattr("kicad_mcp.tools.validation._run_erc_report", fake_run_erc)
    monkeypatch.setattr(
        "kicad_mcp.tools.validation._evaluate_project_gate",
        lambda manufacturer=None, tier=None: [
            GateOutcome(
                name="Manufacturing",
                status="PASS",
                summary="DFM checks passed.",
                details=["Profile: JLCPCB / standard"],
            )
        ],
    )
    monkeypatch.setattr(
        "kicad_mcp.tools.library._schematic_component_rows",
        lambda: [
            {
                "reference": "R1",
                "value": "10k",
                "footprint": "Resistor_SMD:R_0603_1608Metric",
                "lib_id": "Device:R",
                "lcsc": "C25804",
                "mpn": "RC0603FR-0710KL",
                "manufacturer": "Yageo",
                "populate": "Populate",
            },
            {
                "reference": "DNP1",
                "value": "TP",
                "footprint": "TestPoint:TestPoint_Pad",
                "lib_id": "Connector:TestPoint",
                "lcsc": "",
                "mpn": "",
                "manufacturer": "",
                "populate": "DNP",
            },
        ],
    )

    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    result = await call_tool_payload(
        server,
        "project_release_readiness",
        {
            "output_path": "output/release_readiness.md",
            "export_format": "markdown",
        },
    )

    assert result["verdict"] == "WARN"
    assert result["artifacts"]["available"] is True
    assert result["manifest"]["available"] is True
    assert result["exported_report_path"].endswith("release_readiness.md")
    assert (output_dir / "release_readiness.md").is_file()
    exported = (output_dir / "release_readiness.md").read_text(encoding="utf-8")
    assert "Project release readiness: WARN" in exported
    assert "Formal sign-off" in exported


def _write_release_blocking_contract_store(project: Path) -> None:
    root = project / ".kicad-mcp"
    root.mkdir(parents=True, exist_ok=True)
    (root / "hardware_intent_contracts-v1.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "contracts": [
                    {
                        "schema_version": 1,
                        "contract_id": "INTENT-USB-SI",
                        "contract_version": 1,
                        "requirement_id": "REQ-USB-SI",
                        "applicability": {"kind": "net", "key": "USB_DP"},
                        "severity": "blocking",
                        "release_blocking": True,
                        "verification": [
                            {"method_ref": "native-check", "evidence_classes": ["drc"]}
                        ],
                        "quantity_range": {"maximum": {"value": "90", "unit": "ohm"}},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


@pytest.mark.anyio
async def test_project_signoff_blocks_adopted_contract_without_fresh_evidence(
    sample_project: Path,
    monkeypatch,
) -> None:
    from kicad_mcp.tools.design_intent_state import ProjectDesignIntent

    _write_release_blocking_contract_store(sample_project)
    monkeypatch.setattr(
        "kicad_mcp.tools.validation._evaluate_project_gate",
        lambda manufacturer=None, tier=None: [
            GateOutcome(name="PCB", status="PASS", summary="DRC clean")
        ],
    )
    monkeypatch.setattr(
        "kicad_mcp.tools.project.load_design_intent",
        lambda: ProjectDesignIntent(critical_nets=["USB_DP"]),
    )
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    result = await call_tool_text(server, "project_signoff_report", {})

    assert "Manufacturing sign-off: FAIL" in result
    assert "Release contract evidence:" in result
    assert "INTENT-USB-SI@1" in result
    assert "required_evidence_missing" in result


@pytest.mark.anyio
async def test_project_release_readiness_blocks_adopted_contract_without_fresh_evidence(
    sample_project: Path,
    monkeypatch,
) -> None:
    output_dir = sample_project / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "bom.csv").write_text("ref,mpn\nR1,RC0603FR-0710KL\n", encoding="utf-8")
    (output_dir / "board-pos.csv").write_text("ref,x,y,rot\nR1,0,0,0\n", encoding="utf-8")
    (output_dir / "fabrication.pdf").write_text("placeholder", encoding="utf-8")
    (output_dir / "manifest.json").write_text(
        json.dumps({"content_hash": "abc123", "files": [{"filename": "bom.csv"}]}),
        encoding="utf-8",
    )
    (output_dir / "MANIFEST.txt").write_text("manifest", encoding="utf-8")
    _write_release_blocking_contract_store(sample_project)

    monkeypatch.setattr(
        "kicad_mcp.tools.validation._run_drc_report",
        lambda report_name: _clean_drc_report(output_dir / report_name),
    )
    monkeypatch.setattr(
        "kicad_mcp.tools.validation._run_erc_report",
        lambda report_name: _clean_erc_report(output_dir / report_name),
    )
    monkeypatch.setattr(
        "kicad_mcp.tools.validation._evaluate_project_gate",
        lambda manufacturer=None, tier=None: [
            GateOutcome(
                name="Manufacturing",
                status="PASS",
                summary="DFM checks passed.",
                details=["Profile: JLCPCB / standard"],
            )
        ],
    )
    monkeypatch.setattr(
        "kicad_mcp.tools.library._schematic_component_rows",
        lambda: [
            {
                "reference": "R1",
                "value": "10k",
                "footprint": "Resistor_SMD:R_0603_1608Metric",
                "lib_id": "Device:R",
                "lcsc": "C25804",
                "mpn": "RC0603FR-0710KL",
                "manufacturer": "Yageo",
                "populate": "Populate",
            }
        ],
    )

    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})
    result = await call_tool_payload(server, "project_release_readiness", {})

    assert result["verdict"] == "FAIL"
    assert any("required_evidence_missing" in risk for risk in result["open_risks"])
    assert any(
        "HardwareIntentContract evidence is fresh" in item and item.startswith("[ ]")
        for item in result["approval_checklist"]
    )
