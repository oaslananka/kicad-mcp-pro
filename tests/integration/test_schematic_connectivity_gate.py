from __future__ import annotations

from pathlib import Path

import pytest

from kicad_mcp.server import build_server
from kicad_mcp.tools.validation import GateOutcome
from tests.conftest import call_tool_text


def _sheet_pin_block(name: str) -> str:
    return (
        f'\t\t(pin "{name}" input\n'
        "\t\t\t(at 71.12 60.96 180)\n"
        "\t\t\t(effects\n"
        "\t\t\t\t(font\n"
        "\t\t\t\t\t(size 1.27 1.27)\n"
        "\t\t\t\t)\n"
        "\t\t\t)\n"
        '\t\t\t(uuid "44444444-4444-4444-4444-444444444444")\n'
        "\t\t)\n"
    )


def _child_sheet_with_hierarchical_label(name: str) -> str:
    return (
        "(kicad_sch\n"
        "\t(version 20250316)\n"
        '\t(generator "pytest")\n'
        '\t(uuid "11111111-1111-1111-1111-111111111111")\n'
        '\t(paper "A4")\n'
        "\t(lib_symbols)\n"
        f'\t(hierarchical_label "{name}"\n'
        "\t\t(shape input)\n"
        "\t\t(at 10.16 10.16 0)\n"
        "\t\t(effects (font (size 1.27 1.27)))\n"
        '\t\t(uuid "22222222-2222-2222-2222-222222222222")\n'
        "\t)\n"
        "\t(wire (pts (xy 10.16 10.16) (xy 20.32 10.16))\n"
        '\t\t(uuid "33333333-3333-3333-3333-333333333333")\n'
        "\t)\n"
        "\t(sheet_instances\n"
        '\t\t(path "/" (page "1"))\n'
        "\t)\n"
        "\t(embedded_fonts no)\n"
        ")\n"
    )


def _inject_sheet_pin(top_file: Path, pin_name: str) -> None:
    content = top_file.read_text(encoding="utf-8")
    updated = content.replace(
        "\t\t(instances\n",
        _sheet_pin_block(pin_name) + "\t\t(instances\n",
        1,
    )
    top_file.write_text(updated, encoding="utf-8")


@pytest.mark.anyio
async def test_schematic_connectivity_gate_passes_for_connected_flat_net(
    sample_project: Path,
    mock_kicad,
) -> None:
    _ = mock_kicad
    server = build_server("schematic")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    await call_tool_text(
        server,
        "sch_build_circuit",
        {
            "symbols": [
                {
                    "library": "Device",
                    "symbol_name": "R",
                    "x_mm": 10.16,
                    "y_mm": 10.16,
                    "reference": "R1",
                    "value": "10k",
                    "footprint": "Resistor_SMD:R_0805",
                },
                {
                    "library": "Device",
                    "symbol_name": "R",
                    "x_mm": 20.32,
                    "y_mm": 10.16,
                    "reference": "R2",
                    "value": "22k",
                    "footprint": "Resistor_SMD:R_0805",
                },
            ],
        },
    )
    await call_tool_text(
        server,
        "sch_route_wire_between_pins",
        {"ref1": "R1", "pin1": "2", "ref2": "R2", "pin2": "1"},
    )
    await call_tool_text(
        server,
        "sch_add_global_label",
        {"text": "IN", "x_mm": 7.62, "y_mm": 10.16, "shape": "input"},
    )
    await call_tool_text(
        server,
        "sch_add_global_label",
        {"text": "OUT", "x_mm": 22.86, "y_mm": 10.16, "shape": "output"},
    )

    text = await call_tool_text(server, "schematic_connectivity_gate", {})

    assert "Schematic connectivity quality gate: PASS" in text
    assert "Zero-wire pages: 0" in text
    assert "Unnamed single-pin groups: 0" in text
    assert "Isolated footprint symbols: 0" in text


@pytest.mark.anyio
async def test_schematic_connectivity_gate_fails_for_label_only_page(
    sample_project: Path,
    mock_kicad,
) -> None:
    _ = mock_kicad
    server = build_server("schematic")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    await call_tool_text(
        server,
        "sch_build_circuit",
        {
            "symbols": [
                {
                    "library": "Device",
                    "symbol_name": "R",
                    "x_mm": 10.16,
                    "y_mm": 10.16,
                    "reference": "R1",
                    "value": "10k",
                    "footprint": "Resistor_SMD:R_0805",
                },
                {
                    "library": "Device",
                    "symbol_name": "R",
                    "x_mm": 20.32,
                    "y_mm": 10.16,
                    "reference": "R2",
                    "value": "22k",
                    "footprint": "Resistor_SMD:R_0805",
                },
            ],
        },
    )
    await call_tool_text(
        server,
        "sch_add_global_label",
        {"text": "VIN", "x_mm": 40.64, "y_mm": 40.64, "shape": "input"},
    )
    await call_tool_text(
        server,
        "sch_add_global_label",
        {"text": "VOUT", "x_mm": 45.72, "y_mm": 40.64, "shape": "output"},
    )

    text = await call_tool_text(server, "schematic_connectivity_gate", {})

    assert "Schematic connectivity quality gate: FAIL" in text
    assert "Zero-wire pages: 1" in text
    assert "Dangling label groups:" in text
    assert "not ready for PCB or release work" in text


@pytest.mark.anyio
async def test_schematic_connectivity_gate_passes_matching_hierarchy_contract(
    sample_project: Path,
    mock_kicad,
) -> None:
    _ = mock_kicad
    server = build_server("schematic")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})
    await call_tool_text(
        server,
        "sch_create_sheet",
        {"name": "Power", "filename": "power.kicad_sch", "x_mm": 40.64, "y_mm": 50.8},
    )

    _inject_sheet_pin(sample_project / "demo.kicad_sch", "VIN")
    (sample_project / "power.kicad_sch").write_text(
        _child_sheet_with_hierarchical_label("VIN"),
        encoding="utf-8",
    )

    text = await call_tool_text(server, "schematic_connectivity_gate", {})

    assert "Schematic connectivity quality gate: PASS" in text
    assert "Hierarchy contract mismatches: 0" in text


@pytest.mark.anyio
async def test_schematic_connectivity_gate_fails_hierarchy_contract_mismatch(
    sample_project: Path,
    mock_kicad,
) -> None:
    _ = mock_kicad
    server = build_server("schematic")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})
    await call_tool_text(
        server,
        "sch_create_sheet",
        {"name": "Power", "filename": "power.kicad_sch", "x_mm": 40.64, "y_mm": 50.8},
    )

    _inject_sheet_pin(sample_project / "demo.kicad_sch", "VOUT")
    (sample_project / "power.kicad_sch").write_text(
        _child_sheet_with_hierarchical_label("VIN"),
        encoding="utf-8",
    )

    text = await call_tool_text(server, "schematic_connectivity_gate", {})

    assert "Schematic connectivity quality gate: FAIL" in text
    assert "Hierarchy contract mismatch for 'Power'" in text


@pytest.mark.anyio
async def test_project_quality_gate_includes_connectivity_failures(
    sample_project: Path,
    mock_kicad,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ = mock_kicad
    monkeypatch.setattr(
        "kicad_mcp.tools.validation._evaluate_schematic_gate",
        lambda: GateOutcome(
            name="Schematic",
            status="PASS",
            summary="ERC is clean.",
            details=["ERC violations: 0"],
        ),
    )
    monkeypatch.setattr(
        "kicad_mcp.tools.validation._evaluate_pcb_gate",
        lambda: GateOutcome(
            name="PCB",
            status="PASS",
            summary="PCB passes DRC, unconnected, and courtyard checks.",
            details=["DRC violations: 0"],
        ),
    )
    monkeypatch.setattr(
        "kicad_mcp.tools.validation._evaluate_pcb_placement_gate",
        lambda: GateOutcome(
            name="Placement",
            status="PASS",
            summary="Footprint placement is geometrically sane.",
            details=["Overlaps: 0"],
        ),
    )
    monkeypatch.setattr(
        "kicad_mcp.tools.validation._evaluate_manufacturing_gate",
        lambda **_kwargs: GateOutcome(
            name="Manufacturing",
            status="PASS",
            summary="DFM checks passed.",
            details=["Profile: JLCPCB / standard"],
        ),
    )
    monkeypatch.setattr(
        "kicad_mcp.tools.validation._footprint_parity_outcome",
        lambda: GateOutcome(
            name="Footprint parity",
            status="PASS",
            summary="PCB and schematic references are aligned.",
            details=["Missing on board: 0"],
        ),
    )
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
                    "x_mm": 10.16,
                    "y_mm": 10.16,
                    "reference": "R1",
                    "value": "10k",
                    "footprint": "Resistor_SMD:R_0805",
                },
                {
                    "library": "Device",
                    "symbol_name": "R",
                    "x_mm": 20.32,
                    "y_mm": 10.16,
                    "reference": "R2",
                    "value": "22k",
                    "footprint": "Resistor_SMD:R_0805",
                },
            ],
        },
    )
    await call_tool_text(
        server,
        "sch_add_global_label",
        {"text": "VIN", "x_mm": 40.64, "y_mm": 40.64, "shape": "input"},
    )

    text = await call_tool_text(server, "project_quality_gate", {})

    assert "Schematic connectivity quality gate: FAIL" in text


@pytest.mark.anyio
async def test_schematic_connectivity_gate_flags_component_contract_violation(
    sample_project: Path,
    mock_kicad,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ = mock_kicad
    server = build_server("schematic")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    monkeypatch.setattr("kicad_mcp.tools.validation._sheet_contracts", lambda _path: [])
    monkeypatch.setattr(
        "kicad_mcp.tools.schematic.parse_schematic_file",
        lambda _path: {
            "symbols": [
                {
                    "reference": "U1",
                    "value": "ESP32-S3-WROOM-1",
                    "footprint": "RF_Module:ESP32-S3-WROOM-1",
                    "lib_id": "RF_Module:ESP32-S3-WROOM-1",
                }
            ],
            "power_symbols": [],
            "labels": [],
            "wires": [],
        },
    )
    monkeypatch.setattr(
        "kicad_mcp.tools.schematic._build_connectivity_groups",
        lambda _path: [
            {
                "names": ["GND"],
                "points": [(0.0, 0.0)],
                "pins": [{"reference": "U1", "pin": "1", "value": "ESP32-S3-WROOM-1"}],
            }
        ],
    )

    text = await call_tool_text(server, "schematic_connectivity_gate", {})

    assert "Schematic connectivity quality gate: FAIL" in text
    assert "Matched component contracts: 1" in text
    assert "Component contract violations: 1" in text
    assert "esp32_s3_wroom_1" in text
