"""Existing MCP design-intent and placement tools enforce declared mating datums."""

from __future__ import annotations

from pathlib import Path

import pytest

from kicad_mcp.server import build_server
from tests.conftest import call_tool_payload, call_tool_text


@pytest.mark.anyio
async def test_mcp_project_spec_mating_contract_rejects_inward_usb_connector(
    sample_project: Path, mock_kicad: object
) -> None:
    _ = mock_kicad
    # KiCad board and footprint parsers use the native footprint (at) line.
    board = (
        '(kicad_pcb (version 20250216) (generator "pytest")\n'
        "  (gr_rect (start 0 0) (end 60 36) "
        '(stroke (width 0.05) (type default)) (fill no) (layer "Edge.Cuts"))\n'
        '  (footprint "Connector_USB:USB_C_Receptacle_GCT_USB4085" '
        '(layer "F.Cu")\n'
        "    (at 2.75 13.5 0)\n"
        '    (property "Reference" "J1" (at 0 0 0) (layer "F.SilkS"))\n'
        '    (property "Value" "USB" (at 0 0 0) (layer "F.Fab"))\n'
        "    (fp_rect (start -1.0 -1.0) (end 1.0 1.0) "
        '(stroke (width 0.05) (type solid)) (fill no) (layer "F.CrtYd"))\n'
        '    (pad "1" smd rect (at 0 0) (size 1 1) '
        '(layers "F.Cu" "F.Mask"))\n'
        "  )\n"
        ")\n"
    )
    (sample_project / "demo.kicad_pcb").write_text(board, encoding="utf-8")
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})
    await call_tool_text(
        server,
        "project_set_design_intent",
        {
            "mechanical": {
                "connector_mating": [
                    {
                        "ref": "J1",
                        "footprint_id": "Connector_USB:USB_C_Receptacle_GCT_USB4085",
                        "edge": "left",
                        "datum_x_mm": 2.975,
                        "datum_y_mm": 6.1,
                        "normal_local": "bottom",
                        "max_datum_error_mm": 0.5,
                    }
                ]
            }
        },
    )
    spec = await call_tool_payload(server, "project_get_design_spec", {})
    assert isinstance(spec, dict)
    assert spec["resolved"]["mechanical"]["connector_mating"][0]["ref"] == "J1"
    gate = await call_tool_text(server, "pcb_placement_quality_gate", {})
    assert "Placement quality gate: FAIL" in gate
    assert "mating direction" in gate
    assert "mating datum" in gate


@pytest.mark.anyio
async def test_mcp_project_placement_gate_applies_declared_datum_tolerance_budget(
    sample_project: Path, mock_kicad: object
) -> None:
    _ = mock_kicad
    board = (
        '(kicad_pcb (version 20250216) (generator "pytest")\n'
        "  (gr_rect (start 0 0) (end 60 36) "
        '(stroke (width 0.05) (type default)) (fill no) (layer "Edge.Cuts"))\n'
        '  (footprint "Connector_USB:USB_C_Receptacle_GCT_USB4085" '
        '(layer "F.Cu")\n'
        "    (at 6.5 13.5 270)\n"
        '    (property "Reference" "J1" (at 0 0 0) (layer "F.SilkS"))\n'
        '    (property "Value" "USB" (at 0 0 0) (layer "F.Fab"))\n'
        "    (fp_rect (start -1 -1) (end 1 1) "
        '(stroke (width 0.05) (type solid)) (fill no) (layer "F.CrtYd"))\n'
        '    (pad "1" smd rect (at 0 0) (size 1 1) '
        '(layers "F.Cu" "F.Mask"))\n'
        "  )\n"
        ")\n"
    )
    (sample_project / "demo.kicad_pcb").write_text(board, encoding="utf-8")
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})
    await call_tool_text(
        server,
        "project_set_design_intent",
        {
            "mechanical": {
                "connector_mating": [
                    {
                        "ref": "J1",
                        "footprint_id": "Connector_USB:USB_C_Receptacle_GCT_USB4085",
                        "edge": "left",
                        "datum_x_mm": 2.975,
                        "datum_y_mm": 6.1,
                        "normal_local": "bottom",
                        "max_datum_error_mm": 0.5,
                        "datum_component_tolerance_mm": 0.1,
                        "board_edge_tolerance_mm": 0.2,
                    }
                ]
            }
        },
    )
    spec = await call_tool_payload(server, "project_get_design_spec", {})
    assert isinstance(spec, dict)
    contract = spec["resolved"]["mechanical"]["connector_mating"][0]
    assert contract["datum_component_tolerance_mm"] == 0.1
    assert contract["board_edge_tolerance_mm"] == 0.2
    gate = await call_tool_text(server, "pcb_placement_quality_gate", {})
    assert "Placement quality gate: FAIL" in gate
    assert "worst-case mating datum offset 0.700 mm" in gate
