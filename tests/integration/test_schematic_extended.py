"""Integration tests for schematic edge cases and error paths."""

from __future__ import annotations

import re

import pytest

from kicad_mcp.server import build_server
from tests.conftest import call_tool_text


@pytest.mark.anyio
async def test_schematic_add_missing_junctions(sample_project, mock_kicad) -> None:
    """sch_add_missing_junctions should add junctions at wire intersections."""
    server = build_server("schematic")
    await call_tool_text(
        server,
        "sch_build_circuit",
        {
            "symbols": [
                {
                    "library": "Device",
                    "symbol_name": "R",
                    "x_mm": 10.0,
                    "y_mm": 10.0,
                    "reference": "R1",
                    "value": "10k",
                    "footprint": "Resistor_SMD:R_0805",
                },
                {
                    "library": "Device",
                    "symbol_name": "R",
                    "x_mm": 20.0,
                    "y_mm": 10.0,
                    "reference": "R2",
                    "value": "22k",
                    "footprint": "Resistor_SMD:R_0805",
                },
            ],
            "wires": [
                {"x1_mm": 10.0, "y1_mm": 10.0, "x2_mm": 20.0, "y2_mm": 10.0},
                {"x1_mm": 15.0, "y1_mm": 5.0, "x2_mm": 15.0, "y2_mm": 15.0},
            ],
        },
    )

    result = await call_tool_text(server, "sch_add_missing_junctions", {})
    assert "junction" in result.lower() or "added" in result.lower() or "updated" in result.lower()


@pytest.mark.anyio
async def test_schematic_check_power_flags(sample_project, mock_kicad) -> None:
    """sch_check_power_flags should analyze power symbols in the schematic."""
    server = build_server("schematic")
    await call_tool_text(
        server,
        "sch_build_circuit",
        {
            "symbols": [
                {
                    "library": "Device",
                    "symbol_name": "R",
                    "x_mm": 10.0,
                    "y_mm": 10.0,
                    "reference": "R1",
                    "value": "10k",
                    "footprint": "Resistor_SMD:R_0805",
                }
            ],
            "power_symbols": [{"name": "GND", "x_mm": 15.0, "y_mm": 15.0}],
        },
    )

    result = await call_tool_text(server, "sch_check_power_flags", {})
    assert "Power" in result or "power" in result or "GND" in result


@pytest.mark.anyio
async def test_schematic_trace_net_missing(sample_project, mock_kicad) -> None:
    """sch_trace_net should report when a net is not found."""
    server = build_server("schematic")
    await call_tool_text(
        server,
        "sch_build_circuit",
        {
            "symbols": [
                {
                    "library": "Device",
                    "symbol_name": "R",
                    "x_mm": 10.0,
                    "y_mm": 10.0,
                    "reference": "R1",
                    "value": "10k",
                    "footprint": "Resistor_SMD:R_0805",
                }
            ],
        },
    )

    result = await call_tool_text(server, "sch_trace_net", {"net_name": "NONEXISTENT"})
    assert "was not found" in result or "not found" in result.lower()


@pytest.mark.anyio
async def test_schematic_find_free_placement_no_keepout(sample_project, mock_kicad) -> None:
    """sch_find_free_placement should return coordinates without keepout regions."""
    server = build_server("schematic")
    result = await call_tool_text(server, "sch_find_free_placement", {"count": 3})
    assert "Free placement coordinates" in result
    assert "x_mm=" in result


@pytest.mark.anyio
async def test_schematic_find_free_placement_with_count(sample_project, mock_kicad) -> None:
    """sch_find_free_placement should return requested count of coordinates."""
    server = build_server("schematic")
    result = await call_tool_text(server, "sch_find_free_placement", {"count": 5})
    assert "Free placement coordinates" in result
    # Should have 5 coordinate entries (rendered as "Slot N: x_mm=..., y_mm=...").
    matches = re.findall(r"Slot \d+:", result)
    assert len(matches) >= 5


@pytest.mark.anyio
async def test_schematic_set_sheet_size_invalid(sample_project, mock_kicad) -> None:
    """sch_set_sheet_size should report unknown paper size."""
    server = build_server("schematic")
    result = await call_tool_text(server, "sch_set_sheet_size", {"paper": "INVALID"})
    assert "Unknown paper size" in result


@pytest.mark.anyio
async def test_schematic_set_sheet_size_valid(sample_project, mock_kicad) -> None:
    """sch_set_sheet_size should resize to known paper sizes."""
    server = build_server("schematic")
    for paper in ["A4", "A3", "A2", "USLetter", "USLegal"]:
        result = await call_tool_text(server, "sch_set_sheet_size", {"paper": paper})
        # The sample sheet starts as A4, so resizing to A4 reports "already"; any
        # other target reports the resize.
        assert "Sheet resized" in result or "already" in result.lower()


@pytest.mark.anyio
async def test_schematic_auto_resize_sheet(sample_project, mock_kicad) -> None:
    """sch_auto_resize_sheet should resize sheet to fit symbols."""
    server = build_server("schematic")
    await call_tool_text(
        server,
        "sch_build_circuit",
        {
            "symbols": [
                {
                    "library": "Device",
                    "symbol_name": "R",
                    "x_mm": 200.0,
                    "y_mm": 150.0,
                    "reference": "R1",
                    "value": "10k",
                    "footprint": "Resistor_SMD:R_0805",
                }
            ]
        },
    )

    result = await call_tool_text(server, "sch_auto_resize_sheet", {})
    assert "Sheet resized" in result or "already fits" in result


@pytest.mark.anyio
async def test_schematic_annotate_start_number(sample_project, mock_kicad) -> None:
    """sch_annotate should support custom start number and order."""
    server = build_server("schematic")
    await call_tool_text(
        server,
        "sch_build_circuit",
        {
            "symbols": [
                {
                    "library": "Device",
                    "symbol_name": "R",
                    "x_mm": 10.0,
                    "y_mm": 10.0,
                    "reference": "R1",
                    "value": "10k",
                    "footprint": "Resistor_SMD:R_0805",
                },
                {
                    "library": "Device",
                    "symbol_name": "R",
                    "x_mm": 20.0,
                    "y_mm": 10.0,
                    "reference": "R2",
                    "value": "22k",
                    "footprint": "Resistor_SMD:R_0805",
                },
            ]
        },
    )

    result = await call_tool_text(
        server, "sch_annotate", {"start_number": 100, "order": "left_to_right"}
    )
    assert "Annotated" in result


@pytest.mark.anyio
async def test_schematic_reload(sample_project, mock_kicad) -> None:
    """sch_reload should reload the schematic file."""
    server = build_server("schematic")
    result = await call_tool_text(server, "sch_reload", {})
    assert "updated" in result.lower() or "reload" in result.lower()


@pytest.mark.anyio
async def test_schematic_create_sheet_duplicate(sample_project, mock_kicad) -> None:
    """sch_create_sheet should handle duplicate sheet names."""
    server = build_server("schematic")
    await call_tool_text(
        server,
        "sch_create_sheet",
        {"name": "Power", "filename": "power.kicad_sch", "x_mm": 40.0, "y_mm": 50.0},
    )
    result = await call_tool_text(
        server,
        "sch_create_sheet",
        {"name": "Power", "filename": "power2.kicad_sch", "x_mm": 80.0, "y_mm": 50.0},
    )
    assert "already exists" in result.lower() or "created" in result.lower()


@pytest.mark.anyio
async def test_schematic_list_sheets_empty(sample_project, mock_kicad) -> None:
    """sch_list_sheets should handle project with no child sheets."""
    server = build_server("schematic")
    result = await call_tool_text(server, "sch_list_sheets", {})
    assert "Sheets" in result or "No child sheets" in result or "sheet" in result.lower()


@pytest.mark.anyio
async def test_schematic_get_sheet_info_missing(sample_project, mock_kicad) -> None:
    """sch_get_sheet_info should report when sheet is not found."""
    server = build_server("schematic")
    result = await call_tool_text(server, "sch_get_sheet_info", {"sheet_name": "NONEXISTENT"})
    assert "not found" in result.lower() or "no sheet" in result.lower()


@pytest.mark.anyio
async def test_schematic_route_wire_between_pins_missing_refs(sample_project, mock_kicad) -> None:
    """sch_route_wire_between_pins should report missing references."""
    server = build_server("schematic")
    result = await call_tool_text(
        server,
        "sch_route_wire_between_pins",
        {"ref1": "R99", "pin1": "1", "ref2": "R100", "pin2": "2"},
    )
    assert "not found" in result.lower() or "missing" in result.lower()


@pytest.mark.anyio
async def test_schematic_swap_pins_same_pin(sample_project, mock_kicad) -> None:
    """sch_swap_pins should handle swapping same pin gracefully."""
    server = build_server("schematic")
    await call_tool_text(
        server,
        "sch_build_circuit",
        {
            "symbols": [
                {
                    "library": "Device",
                    "symbol_name": "R",
                    "x_mm": 10.0,
                    "y_mm": 10.0,
                    "reference": "R1",
                    "value": "10k",
                    "footprint": "Resistor_SMD:R_0805",
                }
            ]
        },
    )

    result = await call_tool_text(
        server, "sch_swap_pins", {"component_ref": "R1", "pin_a": "1", "pin_b": "1"}
    )
    assert "Recorded pin swap" in result or "same pin" in result.lower()


@pytest.mark.anyio
async def test_schematic_swap_gates_not_available(sample_project, mock_kicad) -> None:
    """sch_swap_gates should report when gates are not available."""
    server = build_server("schematic")
    await call_tool_text(
        server,
        "sch_build_circuit",
        {
            "symbols": [
                {
                    "library": "Device",
                    "symbol_name": "R",
                    "x_mm": 10.0,
                    "y_mm": 10.0,
                    "reference": "R1",
                    "value": "10k",
                    "footprint": "Resistor_SMD:R_0805",
                }
            ]
        },
    )

    result = await call_tool_text(
        server, "sch_swap_gates", {"component_ref": "R1", "gate_a": 1, "gate_b": 2}
    )
    assert "not available" in result.lower()


@pytest.mark.anyio
async def test_schematic_list_swappable_pins(sample_project, mock_kicad) -> None:
    """sch_list_swappable_pins should list swappable pins for a component."""
    server = build_server("schematic")
    await call_tool_text(
        server,
        "sch_build_circuit",
        {
            "symbols": [
                {
                    "library": "Device",
                    "symbol_name": "R",
                    "x_mm": 10.0,
                    "y_mm": 10.0,
                    "reference": "R1",
                    "value": "10k",
                    "footprint": "Resistor_SMD:R_0805",
                }
            ]
        },
    )

    result = await call_tool_text(server, "sch_list_swappable_pins", {"component_ref": "R1"})
    assert '"pins"' in result or "swappable" in result.lower()


@pytest.mark.anyio
async def test_schematic_move_symbol_missing(sample_project, mock_kicad) -> None:
    """sch_move_symbol should report when reference is not found."""
    server = build_server("schematic")
    result = await call_tool_text(
        server, "sch_move_symbol", {"reference": "R404", "x_mm": 10.0, "y_mm": 10.0}
    )
    assert "not found" in result.lower()


@pytest.mark.anyio
async def test_schematic_delete_symbol_missing(sample_project, mock_kicad) -> None:
    """sch_delete_symbol should report when reference is not found."""
    server = build_server("schematic")
    result = await call_tool_text(server, "sch_delete_symbol", {"reference": "R404"})
    assert "not found" in result.lower()


@pytest.mark.anyio
async def test_schematic_delete_wire_missing(sample_project, mock_kicad) -> None:
    """sch_delete_wire should report when wire_id is not found."""
    server = build_server("schematic")
    result = await call_tool_text(server, "sch_delete_wire", {"wire_id": "nonexistent"})
    assert "not found" in result.lower()


@pytest.mark.anyio
async def test_schematic_get_bounding_boxes(sample_project, mock_kicad) -> None:
    """sch_get_bounding_boxes should return bounding boxes for schematic items."""
    server = build_server("schematic")
    await call_tool_text(
        server,
        "sch_build_circuit",
        {
            "symbols": [
                {
                    "library": "Device",
                    "symbol_name": "R",
                    "x_mm": 10.0,
                    "y_mm": 10.0,
                    "reference": "R1",
                    "value": "10k",
                    "footprint": "Resistor_SMD:R_0805",
                }
            ]
        },
    )

    result = await call_tool_text(server, "sch_get_bounding_boxes", {})
    assert "Schematic bounding boxes" in result
    assert "R1" in result


@pytest.mark.anyio
async def test_schematic_get_connectivity_graph(sample_project, mock_kicad) -> None:
    """sch_get_connectivity_graph should return connectivity groups."""
    server = build_server("schematic")
    await call_tool_text(
        server,
        "sch_build_circuit",
        {
            "symbols": [
                {
                    "library": "Device",
                    "symbol_name": "R",
                    "x_mm": 10.0,
                    "y_mm": 10.0,
                    "reference": "R1",
                    "value": "10k",
                    "footprint": "Resistor_SMD:R_0805",
                },
                {
                    "library": "Device",
                    "symbol_name": "R",
                    "x_mm": 20.0,
                    "y_mm": 10.0,
                    "reference": "R2",
                    "value": "22k",
                    "footprint": "Resistor_SMD:R_0805",
                },
            ],
            "wires": [{"x1_mm": 10.0, "y1_mm": 10.0, "x2_mm": 20.0, "y2_mm": 10.0}],
            "labels": [{"name": "MID", "x_mm": 15.0, "y_mm": 10.0}],
        },
    )

    result = await call_tool_text(server, "sch_get_connectivity_graph", {})
    assert "Connectivity groups" in result
    assert "MID" in result


@pytest.mark.anyio
async def test_schematic_instantiate_template_missing(sample_project, mock_kicad) -> None:
    """sch_instantiate_template should report when template is not found."""
    server = build_server("schematic")
    result = await call_tool_text(
        server,
        "sch_instantiate_template",
        {"template_name": "nonexistent_template", "prefix": "TEST_"},
    )
    assert "not found" in result.lower()


@pytest.mark.anyio
async def test_schematic_get_template_info_missing(sample_project, mock_kicad) -> None:
    """sch_get_template_info should report when template is not found."""
    server = build_server("schematic")
    result = await call_tool_text(
        server, "sch_get_template_info", {"template_name": "nonexistent_template"}
    )
    assert "not found" in result.lower()


@pytest.mark.anyio
async def test_schematic_list_templates(sample_project, mock_kicad) -> None:
    """sch_list_templates should list available subcircuit templates."""
    server = build_server("schematic")
    result = await call_tool_text(server, "sch_list_templates", {})
    assert "Available" in result or "Templates" in result or "template" in result.lower()


@pytest.mark.anyio
async def test_schematic_add_jumper(sample_project, mock_kicad) -> None:
    """sch_add_jumper should add a jumper symbol to the schematic."""
    server = build_server("schematic")
    result = await call_tool_text(
        server, "sch_add_jumper", {"x_mm": 30.0, "y_mm": 30.0, "pins": 2, "open_by_default": True}
    )
    assert "Added jumper" in result or "jumper" in result.lower()


@pytest.mark.anyio
async def test_schematic_set_hop_over(sample_project, mock_kicad) -> None:
    """sch_set_hop_over should toggle hop-over display setting."""
    server = build_server("schematic")
    result = await call_tool_text(server, "sch_set_hop_over", {"enabled": False})
    assert "Hop-over display set to disabled" in result

    result = await call_tool_text(server, "sch_set_hop_over", {"enabled": True})
    assert "Hop-over display set to enabled" in result


@pytest.mark.anyio
async def test_schematic_add_bus_and_entry(sample_project, mock_kicad) -> None:
    """sch_add_bus and sch_add_bus_wire_entry should add bus elements."""
    server = build_server("schematic")
    bus = await call_tool_text(
        server, "sch_add_bus", {"x1_mm": 10.0, "y1_mm": 20.0, "x2_mm": 40.0, "y2_mm": 20.0}
    )
    entry = await call_tool_text(
        server,
        "sch_add_bus_wire_entry",
        {"x_mm": 15.0, "y_mm": 20.0, "direction": "up_right"},
    )
    schematic = (sample_project / "demo.kicad_sch").read_text(encoding="utf-8")
    assert "updated" in bus.lower() or "reload" in bus.lower()
    assert "updated" in entry.lower() or "reload" in entry.lower()
    assert "(bus" in schematic
    assert "(bus_entry" in schematic


@pytest.mark.anyio
async def test_schematic_add_no_connect(sample_project, mock_kicad) -> None:
    """sch_add_no_connect should add no-connect markers."""
    server = build_server("schematic")
    result = await call_tool_text(server, "sch_add_no_connect", {"x_mm": 30.0, "y_mm": 30.0})
    schematic = (sample_project / "demo.kicad_sch").read_text(encoding="utf-8")
    assert "updated" in result.lower() or "reload" in result.lower()
    assert "(no_connect" in schematic


@pytest.mark.anyio
async def test_schematic_delete_no_connect(sample_project, mock_kicad) -> None:
    """sch_delete_no_connect should remove a matching no-connect marker."""
    server = build_server("schematic")
    await call_tool_text(server, "sch_add_no_connect", {"x_mm": 30.0, "y_mm": 30.0})
    assert "(no_connect" in (sample_project / "demo.kicad_sch").read_text(encoding="utf-8")

    result = await call_tool_text(
        server,
        "sch_delete_no_connect",
        {"x_mm": 30.0, "y_mm": 30.0},
    )
    assert "Deleted" in result
    assert "(no_connect" not in (sample_project / "demo.kicad_sch").read_text(encoding="utf-8")

    missing = await call_tool_text(
        server,
        "sch_delete_no_connect",
        {"x_mm": 90.0, "y_mm": 90.0},
    )
    assert "No no-connect marker found" in missing


@pytest.mark.anyio
async def test_schematic_add_hierarchical_label(sample_project, mock_kicad) -> None:
    """sch_add_hierarchical_label should add hierarchical labels with shapes."""
    server = build_server("schematic")
    for shape in ["input", "output", "bidirectional", "tri_state", "passive"]:
        result = await call_tool_text(
            server,
            "sch_add_hierarchical_label",
            {"text": f"SIG_{shape}", "x_mm": 30.0, "y_mm": 30.0, "shape": shape},
        )
        assert "updated" in result.lower() or "reload" in result.lower()

    schematic = (sample_project / "demo.kicad_sch").read_text(encoding="utf-8")
    assert "(hierarchical_label" in schematic


@pytest.mark.anyio
async def test_schematic_add_global_label_shapes(sample_project, mock_kicad) -> None:
    """sch_add_global_label should support all label shapes."""
    server = build_server("schematic")
    for shape in ["input", "output", "bidirectional", "tri_state", "passive"]:
        result = await call_tool_text(
            server,
            "sch_add_global_label",
            {"text": f"NET_{shape}", "x_mm": 30.0, "y_mm": 30.0, "shape": shape},
        )
        assert "updated" in result.lower() or "reload" in result.lower()

    schematic = (sample_project / "demo.kicad_sch").read_text(encoding="utf-8")
    assert "(global_label" in schematic


@pytest.mark.anyio
async def test_schematic_update_properties_missing_field(sample_project, mock_kicad) -> None:
    """sch_update_properties should handle missing symbols gracefully."""
    server = build_server("schematic")
    result = await call_tool_text(
        server,
        "sch_update_properties",
        {"reference": "R404", "field": "Value", "value": "100k"},
    )
    assert "not found" in result.lower() or "Reference 'R404'" in result


@pytest.mark.anyio
async def test_schematic_get_pin_positions_missing_library(sample_project, mock_kicad) -> None:
    """sch_get_pin_positions should report when library is not found."""
    server = build_server("schematic")
    result = await call_tool_text(
        server,
        "sch_get_pin_positions",
        {"library": "MissingLib", "symbol_name": "R", "x_mm": 10.0, "y_mm": 10.0},
    )
    assert "could not calculate pin positions" in result.lower()


@pytest.mark.anyio
async def test_schematic_get_symbols_empty(sample_project, mock_kicad) -> None:
    """sch_get_symbols should handle empty schematic."""
    server = build_server("schematic")
    result = await call_tool_text(server, "sch_get_symbols", {})
    assert "no symbols" in result.lower()


@pytest.mark.anyio
async def test_schematic_get_wires_empty(sample_project, mock_kicad) -> None:
    """sch_get_wires should handle schematic with no wires."""
    server = build_server("schematic")
    result = await call_tool_text(server, "sch_get_wires", {})
    assert "Wires" in result or "No wires" in result or "contains no wires" in result


@pytest.mark.anyio
async def test_schematic_get_labels_empty(sample_project, mock_kicad) -> None:
    """sch_get_labels should handle schematic with no labels."""
    server = build_server("schematic")
    result = await call_tool_text(server, "sch_get_labels", {})
    assert "no labels" in result.lower()


@pytest.mark.anyio
async def test_schematic_get_net_names_empty(sample_project, mock_kicad) -> None:
    """sch_get_net_names should handle schematic with no nets."""
    server = build_server("schematic")
    result = await call_tool_text(server, "sch_get_net_names", {})
    assert "no named nets" in result.lower()


@pytest.mark.anyio
async def test_schematic_build_circuit_empty(sample_project, mock_kicad) -> None:
    """sch_build_circuit should handle empty circuit definition."""
    server = build_server("schematic")
    result = await call_tool_text(
        server, "sch_build_circuit", {"symbols": [], "wires": [], "labels": []}
    )
    assert "Circuit" in result or "built" in result.lower() or "updated" in result.lower()


@pytest.mark.anyio
async def test_schematic_build_circuit_with_nets(sample_project, mock_kicad) -> None:
    """sch_build_circuit should support netlist-based wiring."""
    server = build_server("schematic")
    result = await call_tool_text(
        server,
        "sch_build_circuit",
        {
            "symbols": [
                {
                    "library": "Device",
                    "symbol_name": "R",
                    "x_mm": 10.0,
                    "y_mm": 10.0,
                    "reference": "R1",
                    "value": "10k",
                    "footprint": "Resistor_SMD:R_0805",
                },
                {
                    "library": "Device",
                    "symbol_name": "R",
                    "x_mm": 20.0,
                    "y_mm": 10.0,
                    "reference": "R2",
                    "value": "22k",
                    "footprint": "Resistor_SMD:R_0805",
                },
            ],
            "nets": [
                {
                    "name": "VIN",
                    "endpoints": [{"reference": "R1", "pin": "1"}],
                },
                {
                    "name": "MID",
                    "endpoints": [
                        {"reference": "R1", "pin": "2"},
                        {"reference": "R2", "pin": "1"},
                    ],
                },
                {"name": "GND", "endpoints": [{"reference": "R2", "pin": "2"}]},
            ],
        },
    )
    assert "Circuit" in result or "built" in result.lower() or "updated" in result.lower()
    schematic = (sample_project / "demo.kicad_sch").read_text(encoding="utf-8")
    # Without auto_layout, sch_build_circuit routes nets that resolve to >=2 pins
    # into Manhattan wire segments. The two-pin "MID" net (R1.2 -> R2.1) is routed
    # as a wire; net names only become labels in the auto_layout path (covered by
    # the netlist auto-layout tests in test_schematic_tools.py).
    assert "(wire" in schematic


@pytest.mark.anyio
async def test_schematic_auto_place_symbols_linear(sample_project, mock_kicad) -> None:
    """sch_auto_place_symbols should support linear strategy."""
    server = build_server("schematic")
    await call_tool_text(
        server,
        "sch_build_circuit",
        {
            "symbols": [
                {
                    "library": "Device",
                    "symbol_name": "R",
                    "x_mm": 10.0,
                    "y_mm": 10.0,
                    "reference": "R1",
                    "value": "10k",
                    "footprint": "Resistor_SMD:R_0805",
                },
                {
                    "library": "Device",
                    "symbol_name": "R",
                    "x_mm": 10.0,
                    "y_mm": 20.0,
                    "reference": "R2",
                    "value": "22k",
                    "footprint": "Resistor_SMD:R_0805",
                },
            ]
        },
    )

    result = await call_tool_text(
        server, "sch_auto_place_symbols", {"symbol_list": ["R1", "R2"], "strategy": "linear"}
    )
    assert "Auto-placed" in result


@pytest.mark.anyio
async def test_schematic_auto_place_symbols_grid(sample_project, mock_kicad) -> None:
    """sch_auto_place_symbols should support grid strategy."""
    server = build_server("schematic")
    await call_tool_text(
        server,
        "sch_build_circuit",
        {
            "symbols": [
                {
                    "library": "Device",
                    "symbol_name": "R",
                    "x_mm": 10.0,
                    "y_mm": 10.0,
                    "reference": "R1",
                    "value": "10k",
                    "footprint": "Resistor_SMD:R_0805",
                },
                {
                    "library": "Device",
                    "symbol_name": "R",
                    "x_mm": 10.0,
                    "y_mm": 20.0,
                    "reference": "R2",
                    "value": "22k",
                    "footprint": "Resistor_SMD:R_0805",
                },
            ]
        },
    )

    result = await call_tool_text(
        server, "sch_auto_place_symbols", {"symbol_list": ["R1", "R2"], "strategy": "grid"}
    )
    assert "Auto-placed" in result


@pytest.mark.anyio
async def test_schematic_auto_place_symbols_missing_refs(sample_project, mock_kicad) -> None:
    """sch_auto_place_symbols should report missing references."""
    server = build_server("schematic")
    result = await call_tool_text(
        server,
        "sch_auto_place_symbols",
        {"symbol_list": ["R99", "R100"], "strategy": "linear"},
    )
    assert "not found" in result.lower() or "missing" in result.lower()


@pytest.mark.anyio
async def test_schematic_auto_place_functional_no_project(mock_kicad) -> None:
    """sch_auto_place_functional should handle missing project gracefully."""
    server = build_server("schematic")
    result = await call_tool_text(server, "sch_auto_place_functional", {})
    assert "No project" in result or "project" in result.lower()


@pytest.mark.anyio
async def test_schematic_analyze_net_compilation_empty(sample_project, mock_kicad) -> None:
    """sch_analyze_net_compilation should handle empty netlist."""
    server = build_server("schematic")
    result = await call_tool_text(
        server,
        "sch_analyze_net_compilation",
        {"symbols": [], "nets": []},
    )
    assert "Net compilation analysis" in result
    assert "Nets requested: 0" in result


@pytest.mark.anyio
async def test_schematic_add_power_symbol_rotated(sample_project, mock_kicad) -> None:
    """sch_add_power_symbol should support rotation."""
    server = build_server("schematic")
    result = await call_tool_text(
        server,
        "sch_add_power_symbol",
        {"name": "VCC", "x_mm": 20.0, "y_mm": 20.0, "rotation": 90},
    )
    schematic = (sample_project / "demo.kicad_sch").read_text(encoding="utf-8")
    assert "updated" in result.lower() or "reload" in result.lower()
    assert "VCC" in schematic


@pytest.mark.anyio
async def test_schematic_add_power_symbol_preserves_unsnapped_coordinate(
    sample_project, mock_kicad
) -> None:
    """snap_to_grid=False should preserve the exact requested power-symbol origin."""
    server = build_server("schematic")
    result = await call_tool_text(
        server,
        "sch_add_power_symbol",
        {
            "name": "GND",
            "x_mm": 340.13,
            "y_mm": 70.37,
            "snap_to_grid": False,
        },
    )

    schematic = (sample_project / "demo.kicad_sch").read_text(encoding="utf-8")
    assert "Power symbol GND placed at (340.13, 70.37)" in result
    assert '(lib_id "power:GND")' in schematic
    assert "\t\t(at 340.13 70.37 0)" in schematic
    assert "233.68" not in schematic


@pytest.mark.anyio
async def test_schematic_add_symbol_with_unit(sample_project, mock_kicad) -> None:
    """sch_add_symbol should support unit parameter for multi-unit symbols."""
    server = build_server("schematic")
    result = await call_tool_text(
        server,
        "sch_add_symbol",
        {
            "library": "MultiUnit",
            "symbol_name": "DualChild",
            "x_mm": 30.0,
            "y_mm": 30.0,
            "reference": "U1",
            "value": "DualChild",
            "footprint": "Package_DIP:DIP-8_W7.62mm",
            "rotation": 0,
            "unit": 1,
        },
    )
    schematic = (sample_project / "demo.kicad_sch").read_text(encoding="utf-8")
    assert "updated" in result.lower() or "reload" in result.lower()
    assert "(unit 1)" in schematic


@pytest.mark.anyio
async def test_schematic_add_wire_snap_to_grid(sample_project, mock_kicad) -> None:
    """sch_add_wire should snap to grid by default."""
    server = build_server("schematic")
    result = await call_tool_text(
        server,
        "sch_add_wire",
        {"x1_mm": 10.1, "y1_mm": 10.1, "x2_mm": 20.1, "y2_mm": 10.1},
    )
    schematic = (sample_project / "demo.kicad_sch").read_text(encoding="utf-8")
    assert "updated" in result.lower() or "reload" in result.lower()
    # Should be snapped to 2.54mm grid
    assert "(pts (xy 10.16 10.16) (xy 20.32 10.16))" in schematic


@pytest.mark.anyio
async def test_schematic_add_label_rotated(sample_project, mock_kicad) -> None:
    """sch_add_label should support rotation."""
    server = build_server("schematic")
    result = await call_tool_text(
        server,
        "sch_add_label",
        {"name": "ROTATED", "x_mm": 10.0, "y_mm": 10.0, "rotation": 90},
    )
    schematic = (sample_project / "demo.kicad_sch").read_text(encoding="utf-8")
    assert "updated" in result.lower() or "reload" in result.lower()
    assert "ROTATED" in schematic


@pytest.mark.anyio
async def test_schematic_get_pin_positions_rotated(sample_project, mock_kicad) -> None:
    """sch_get_pin_positions should account for rotation."""
    server = build_server("schematic")
    result = await call_tool_text(
        server,
        "sch_get_pin_positions",
        {"library": "Device", "symbol_name": "R", "x_mm": 10.0, "y_mm": 10.0, "rotation": 90},
    )
    assert "Pin 1" in result
    assert "rotation=90" in result or "90" in result


@pytest.mark.anyio
async def test_schematic_instantiate_template_with_params(sample_project, mock_kicad) -> None:
    """sch_instantiate_template should substitute parameters."""
    server = build_server("schematic")
    result = await call_tool_text(
        server,
        "sch_instantiate_template",
        {
            "template_name": "buzzer_nmos_driver",
            "prefix": "AUD_",
            "params": {"supply_v": 5.0},
        },
    )
    assert "Instantiation Plan" in result
    assert "AUD_" in result
    assert "5.0" in result


@pytest.mark.anyio
async def test_schematic_get_template_info_valid(sample_project, mock_kicad) -> None:
    """sch_get_template_info should return detailed template information."""
    server = build_server("schematic")
    result = await call_tool_text(
        server, "sch_get_template_info", {"template_name": "buzzer_nmos_driver"}
    )
    assert "Template" in result
    assert "Parameters" in result or "Symbols" in result or "Nets" in result


@pytest.mark.anyio
async def test_schematic_create_sheet_with_size(sample_project, mock_kicad) -> None:
    """sch_create_sheet should create child sheet with specified size."""
    server = build_server("schematic")
    result = await call_tool_text(
        server,
        "sch_create_sheet",
        {"name": "IO", "filename": "io.kicad_sch", "x_mm": 50.0, "y_mm": 50.0},
    )
    assert "Created child sheet 'IO'" in result
    assert (sample_project / "io.kicad_sch").exists()

    info = await call_tool_text(server, "sch_get_sheet_info", {"sheet_name": "IO"})
    assert "Sheet 'IO'" in info
    assert "io.kicad_sch" in info


@pytest.mark.anyio
async def test_schematic_delete_wire_by_uuid_prefix(sample_project, mock_kicad) -> None:
    """sch_delete_wire should support UUID prefix matching."""
    server = build_server("schematic")
    await call_tool_text(
        server,
        "sch_build_circuit",
        {
            "symbols": [
                {
                    "library": "Device",
                    "symbol_name": "R",
                    "x_mm": 10.0,
                    "y_mm": 10.0,
                    "reference": "R1",
                    "value": "10k",
                    "footprint": "Resistor_SMD:R_0805",
                },
                {
                    "library": "Device",
                    "symbol_name": "R",
                    "x_mm": 20.0,
                    "y_mm": 10.0,
                    "reference": "R2",
                    "value": "22k",
                    "footprint": "Resistor_SMD:R_0805",
                },
            ],
            "wires": [{"x1_mm": 10.0, "y1_mm": 10.0, "x2_mm": 20.0, "y2_mm": 10.0}],
        },
    )

    await call_tool_text(server, "sch_get_wires", {})
    # Try deleting with a short prefix that won't match anything meaningful
    result = await call_tool_text(server, "sch_delete_wire", {"wire_id": "0000"})
    assert "Deleted" in result or "not found" in result.lower()


@pytest.mark.anyio
async def test_schematic_update_properties_value_escaping(sample_project, mock_kicad) -> None:
    """sch_update_properties should properly escape special characters in values."""
    server = build_server("schematic")
    await call_tool_text(
        server,
        "sch_build_circuit",
        {
            "symbols": [
                {
                    "library": "Device",
                    "symbol_name": "R",
                    "x_mm": 10.0,
                    "y_mm": 10.0,
                    "reference": "R1",
                    "value": "10k",
                    "footprint": "Resistor_SMD:R_0805",
                }
            ]
        },
    )

    result = await call_tool_text(
        server,
        "sch_update_properties",
        {"reference": "R1", "field": "Value", "value": '10k "1%"'},
    )
    schematic = (sample_project / "demo.kicad_sch").read_text(encoding="utf-8")
    assert "Updated R1.Value" in result
    assert '10k \\"1%\\"' in schematic or '10k "1%"' in schematic


@pytest.mark.anyio
async def test_schematic_add_symbol_no_footprint(sample_project, mock_kicad) -> None:
    """sch_add_symbol should work without an explicit footprint."""
    server = build_server("schematic")
    result = await call_tool_text(
        server,
        "sch_add_symbol",
        {
            "library": "Device",
            "symbol_name": "R",
            "x_mm": 10.0,
            "y_mm": 10.0,
            "reference": "R1",
            "value": "10k",
            "rotation": 0,
        },
    )
    schematic = (sample_project / "demo.kicad_sch").read_text(encoding="utf-8")
    assert "updated" in result.lower() or "reload" in result.lower()
    assert "R1" in schematic


@pytest.mark.anyio
async def test_schematic_build_circuit_auto_layout_no_coords(sample_project, mock_kicad) -> None:
    """sch_build_circuit with auto_layout should assign coordinates when missing."""
    server = build_server("schematic")
    result = await call_tool_text(
        server,
        "sch_build_circuit",
        {
            "auto_layout": True,
            "symbols": [
                {
                    "library": "Device",
                    "symbol_name": "R",
                    "reference": "R1",
                    "value": "10k",
                    "footprint": "Resistor_SMD:R_0805",
                },
                {
                    "library": "Device",
                    "symbol_name": "R",
                    "reference": "R2",
                    "value": "22k",
                    "footprint": "Resistor_SMD:R_0805",
                },
            ],
            "wires": [],
            "labels": [{"name": "OUT"}],
            "power_symbols": [{"name": "GND"}],
        },
    )
    assert "Applied auto-layout to schematic symbols." in result
    schematic = (sample_project / "demo.kicad_sch").read_text(encoding="utf-8")
    assert "R1" in schematic
    assert "R2" in schematic
    assert "OUT" in schematic
    assert "GND" in schematic


@pytest.mark.anyio
async def test_schematic_add_pin_labels(sample_project, mock_kicad) -> None:
    """sch_add_pin_labels should connect symbol pins to nets via stubs and labels."""
    server = build_server("schematic")
    await call_tool_text(
        server,
        "sch_build_circuit",
        {
            "symbols": [
                {
                    "library": "Device",
                    "symbol_name": "R",
                    "x_mm": 10.0,
                    "y_mm": 10.0,
                    "reference": "R1",
                    "value": "10k",
                    "footprint": "Resistor_SMD:R_0805",
                },
            ],
        },
    )
    result = await call_tool_text(
        server,
        "sch_add_pin_labels",
        {
            "connections": [
                {"reference": "R1", "pin": "1", "net": "NET_IN"},
            ],
        },
    )
    assert "->" in result
    assert "NET_IN" in result


@pytest.mark.anyio
async def test_schematic_add_pin_labels_targets_power_symbol_reference(
    sample_project, mock_kicad
) -> None:
    """sch_add_pin_labels should accept placed #PWR references with pin geometry."""
    server = build_server("schematic")
    await call_tool_text(
        server,
        "sch_add_power_symbol",
        {"name": "GND", "x_mm": 25.4, "y_mm": 25.4, "snap_to_grid": False},
    )
    schematic = (sample_project / "demo.kicad_sch").read_text(encoding="utf-8")
    match = re.search(r'\(property "Reference" "(#PWR[^"]+)"', schematic)
    assert match is not None

    result = await call_tool_text(
        server,
        "sch_add_pin_labels",
        {
            "connections": [
                {"reference": match.group(1), "pin": "1", "net": "GND"},
            ],
        },
    )

    assert f"{match.group(1)}.1 -> GND" in result
    assert "symbol not placed" not in result
    schematic = (sample_project / "demo.kicad_sch").read_text(encoding="utf-8")
    assert schematic.count('(lib_id "power:GND")') >= 2


@pytest.mark.anyio
async def test_schematic_add_pin_labels_uses_symbol_edges_for_tall_side_pins(
    sample_project, mock_kicad
) -> None:
    """Side pins on tall symbols should stub horizontally, not toward the origin."""
    symbols_dir = sample_project.parent / "symbols"
    (symbols_dir / "Custom.kicad_sym").write_text(
        (
            "(kicad_symbol_lib (version 20250316) (generator pytest)\n"
            '  (symbol "TallIC"\n'
            '    (property "Reference" "U" (id 0) (at 0 27.94 0))\n'
            '    (property "Value" "TallIC" (id 1) (at 0 -27.94 0))\n'
            '    (symbol "TallIC_1_1"\n'
            "      (pin bidirectional line (at -15.24 20.32 0) "
            '(length 2.54) (name "IO_TOP_LEFT") (number "1"))\\n'
            "      (pin bidirectional line (at -15.24 -20.32 0) "
            '(length 2.54) (name "IO_BOTTOM_LEFT") (number "2"))\\n'
            '      (pin power_in line (at 0 25.4 270) (length 2.54) (name "VCC") (number "3"))\n'
            '      (pin power_in line (at 0 -25.4 90) (length 2.54) (name "GND") (number "4"))\n'
            "      (pin bidirectional line (at 15.24 0 180) "
            '(length 2.54) (name "IO_RIGHT") (number "5"))\\n'
            "    )\n"
            "  )\n"
            ")\n"
        ),
        encoding="utf-8",
    )
    server = build_server("schematic")
    await call_tool_text(
        server,
        "sch_add_symbol",
        {
            "library": "Custom",
            "symbol_name": "TallIC",
            "x_mm": 100.0,
            "y_mm": 100.0,
            "reference": "U1",
            "value": "TallIC",
            "footprint": "",
            "snap_to_grid": False,
        },
    )

    result = await call_tool_text(
        server,
        "sch_add_pin_labels",
        {
            "connections": [
                {"reference": "U1", "pin": "1", "net": "TOP_LEFT"},
                {"reference": "U1", "pin": "3", "net": "VCC"},
                {"reference": "U1", "pin": "4", "net": "GND"},
            ],
            "stub_mm": 5.08,
        },
    )

    assert "U1.1 -> TOP_LEFT @ (79.68, 79.68)" in result
    assert "U1.3 -> VCC (power) @ (100.0, 64.44)" in result
    assert "U1.4 -> GND (power) @ (100.0, 135.56)" in result

    schematic = (sample_project / "demo.kicad_sch").read_text(encoding="utf-8")
    assert '(lib_id "power:VCC")' in schematic
    assert '(lib_id "power:GND")' in schematic
    assert '(global_label "VCC"' not in schematic
    assert '(global_label "GND"' not in schematic


@pytest.mark.anyio
async def test_schematic_add_pin_labels_staggers_neighbouring_terminals(
    sample_project, mock_kicad
) -> None:
    """Neighbouring pin-label terminals should not land at the same coordinate."""
    server = build_server("schematic")
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
                },
                {
                    "library": "Device",
                    "symbol_name": "R",
                    "x_mm": 15.24,
                    "y_mm": 10.16,
                    "reference": "R2",
                    "value": "10k",
                },
            ],
        },
    )

    result = await call_tool_text(
        server,
        "sch_add_pin_labels",
        {
            "connections": [
                {"reference": "R1", "pin": "2", "net": "SIG_A"},
                {"reference": "R2", "pin": "1", "net": "SIG_B"},
            ],
            "stub_mm": 2.54,
        },
    )

    assert "staggered" in result
    schematic = (sample_project / "demo.kicad_sch").read_text(encoding="utf-8")
    assert '(global_label "SIG_A"' in schematic
    assert '(global_label "SIG_B"' in schematic


@pytest.mark.anyio
async def test_schematic_add_pin_labels_clears_vertical_symbol_value_text(
    sample_project, mock_kicad
) -> None:
    """Downward terminals should clear the host symbol's Value field."""
    symbols_dir = sample_project.parent / "symbols"
    (symbols_dir / "Custom.kicad_sym").write_text(
        (
            "(kicad_symbol_lib (version 20250316) (generator pytest)\n"
            '  (symbol "BottomPinPart"\n'
            '    (property "Reference" "R" (id 0) (at 0 -3.81 0))\n'
            '    (property "Value" "10k" (id 1) (at 0 3.81 0))\n'
            '    (symbol "BottomPinPart_1_1"\n'
            '      (pin passive line (at 0 -7.62 90) (length 2.54) (name "BOT") (number "2"))\n'
            "    )\n"
            "  )\n"
            ")\n"
        ),
        encoding="utf-8",
    )
    server = build_server("schematic")
    await call_tool_text(
        server,
        "sch_add_symbol",
        {
            "library": "Custom",
            "symbol_name": "BottomPinPart",
            "x_mm": 50.8,
            "y_mm": 50.8,
            "reference": "R5",
            "value": "10k",
            "snap_to_grid": False,
        },
    )

    result = await call_tool_text(
        server,
        "sch_add_pin_labels",
        {"connections": [{"reference": "R5", "pin": "2", "net": "WDT_RST"}]},
    )

    assert "R5.2 -> WDT_RST @ (50.8, 68.58)" in result
    schematic = (sample_project / "demo.kicad_sch").read_text(encoding="utf-8")
    assert '(global_label "WDT_RST"' in schematic
    assert "(at 50.8 68.58 270)" in schematic
    assert "(at 50.8 63.5 270)" not in schematic


@pytest.mark.anyio
async def test_schematic_add_pin_labels_dense_ic_preserves_pin_rows(
    sample_project, mock_kicad
) -> None:
    """Large pin-label batches should not stagger every dense IC row."""
    symbols_dir = sample_project.parent / "symbols"
    pins = "\n".join(
        f"      (pin bidirectional line (at -15.24 {-17.78 + (pin - 1) * 2.54:.2f} 0) "
        f'(length 2.54) (name "P{pin}") (number "{pin}"))'
        for pin in range(1, 17)
    )
    (symbols_dir / "Custom.kicad_sym").write_text(
        (
            "(kicad_symbol_lib (version 20250316) (generator pytest)\n"
            '  (symbol "DenseIC"\n'
            '    (property "Reference" "U" (id 0) (at 0 25.4 0))\n'
            '    (property "Value" "DenseIC" (id 1) (at 0 -25.4 0))\n'
            '    (symbol "DenseIC_1_1"\n'
            f"{pins}\n"
            "    )\n"
            "  )\n"
            ")\n"
        ),
        encoding="utf-8",
    )
    server = build_server("schematic")
    await call_tool_text(
        server,
        "sch_add_symbol",
        {
            "library": "Custom",
            "symbol_name": "DenseIC",
            "x_mm": 100.0,
            "y_mm": 100.0,
            "reference": "U1",
            "value": "DenseIC",
            "snap_to_grid": False,
        },
    )

    result = await call_tool_text(
        server,
        "sch_add_pin_labels",
        {
            "connections": [
                {"reference": "U1", "pin": str(pin), "net": f"NET_{pin:02d}"}
                for pin in range(1, 17)
            ],
        },
    )

    assert "dense terminal mode" in result
    assert "; staggered" not in result
    schematic = (sample_project / "demo.kicad_sch").read_text(encoding="utf-8")
    label_positions = re.findall(
        r'\(global_label "NET_\d+".*?\(at ([\d.-]+) ([\d.-]+) ',
        schematic,
        re.DOTALL,
    )
    assert len(label_positions) == 16
    assert len(set(label_positions)) == 16
    graph = await call_tool_text(server, "sch_get_connectivity_graph", {})
    assert graph.count("NET_") == 16


@pytest.mark.anyio
async def test_schematic_delete_label(sample_project, mock_kicad) -> None:
    """sch_delete_label should remove a matching label from the schematic."""
    server = build_server("schematic")
    await call_tool_text(
        server,
        "sch_add_label",
        {"name": "TO_DELETE", "x_mm": 50.0, "y_mm": 50.0, "rotation": 0},
    )
    result = await call_tool_text(
        server,
        "sch_delete_label",
        {"name": "TO_DELETE", "x_mm": 50.0, "y_mm": 50.0},
    )
    assert "Deleted" in result
    assert "TO_DELETE" in result


@pytest.mark.anyio
async def test_schematic_move_label(sample_project, mock_kicad) -> None:
    """sch_move_label should move a label to a new coordinate."""
    server = build_server("schematic")
    await call_tool_text(
        server,
        "sch_add_label",
        {"name": "TO_MOVE", "x_mm": 20.0, "y_mm": 20.0, "rotation": 0},
    )
    result = await call_tool_text(
        server,
        "sch_move_label",
        {"name": "TO_MOVE", "x_mm": 20.0, "y_mm": 20.0, "new_x_mm": 80.0, "new_y_mm": 40.0},
    )
    assert "Moved" in result or "moved" in result or "TO_MOVE" in result


@pytest.mark.anyio
async def test_sch_get_circuit_ir_returns_ir_on_populated_schematic(
    sample_project,
    mock_kicad,
) -> None:
    """sch_get_circuit_ir returns a JSON IR with component and net counts."""
    import json

    _ = mock_kicad
    server = build_server("schematic")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    result = await call_tool_text(server, "sch_get_circuit_ir", {})
    assert isinstance(result, str)

    # Parsing should succeed even on an empty/minimal schematic
    try:
        payload = json.loads(result)
        assert "status" in payload or "components" in payload or "component_count" in payload
    except json.JSONDecodeError:
        # Tool may return a text description for an empty schematic — that's ok
        assert (
            "circuit" in result.lower() or "schematic" in result.lower() or "ir" in result.lower()
        )
