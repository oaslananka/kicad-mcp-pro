from __future__ import annotations

import pytest

from kicad_mcp.server import build_server
from tests.conftest import call_tool_text


@pytest.mark.anyio
async def test_schematic_add_label(sample_project, mock_kicad) -> None:
    server = build_server("schematic")
    text = await call_tool_text(
        server,
        "sch_add_label",
        {"name": "NET_A", "x_mm": 10.0, "y_mm": 10.0, "rotation": 0},
    )
    assert "updated" in text.lower() or "reload" in text.lower()
    labels = await call_tool_text(server, "sch_get_labels", {})
    assert "NET_A" in labels


@pytest.mark.anyio
async def test_schematic_string_values_are_escaped(sample_project, mock_kicad) -> None:
    server = build_server("schematic")

    await call_tool_text(
        server,
        "sch_add_label",
        {"name": 'NET(1)"A\\B', "x_mm": 10.0, "y_mm": 10.0, "rotation": 0},
    )

    schematic = (sample_project / "demo.kicad_sch").read_text(encoding="utf-8")
    labels = await call_tool_text(server, "sch_get_labels", {})
    assert '"NET(1)\\"A\\\\B"' in schematic
    assert 'NET(1)"A\\B' in labels


@pytest.mark.anyio
async def test_power_symbol_reference_is_hidden_and_value_offset(
    sample_project,
    mock_kicad,
) -> None:
    server = build_server("schematic")

    result = await call_tool_text(
        server,
        "sch_add_power_symbol",
        {"name": "GND", "x_mm": 20.0, "y_mm": 30.0, "rotation": 0},
    )

    schematic = (sample_project / "demo.kicad_sch").read_text(encoding="utf-8")
    assert "updated" in result.lower() or "reload" in result.lower()
    assert "Grid snap" in result
    assert '(property "Reference" "#PWR' in schematic
    assert "\t\t\t(at 20.32 36.83 0)" in schematic
    assert "\t\t\t(effects (font (size 1.27 1.27)) (hide yes))" in schematic
    assert '(property "Value" "GND"\n\t\t\t(at 20.32 35.56 0)' in schematic


@pytest.mark.anyio
async def test_build_circuit_accepts_power_symbol_mm_aliases(sample_project, mock_kicad) -> None:
    server = build_server("schematic")

    await call_tool_text(
        server,
        "sch_build_circuit",
        {
            "symbols": [],
            "wires": [],
            "labels": [],
            "power_symbols": [{"name": "GND", "x_mm": 20.0, "y_mm": 30.0, "rotation": 0}],
        },
    )

    schematic = (sample_project / "demo.kicad_sch").read_text(encoding="utf-8")
    assert '(lib_id "power:GND")' in schematic
    assert "\t\t(at 20.32 30.48 0)" in schematic


@pytest.mark.anyio
async def test_build_circuit_auto_layout_assigns_missing_coordinates(
    sample_project,
    mock_kicad,
) -> None:
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

    schematic = (sample_project / "demo.kicad_sch").read_text(encoding="utf-8")
    assert "Applied basic auto-layout" in result
    assert '(property "Reference" "R1"\n\t\t\t(at 50.8 46.99 0)' in schematic
    assert "\t\t(at 76.2 50.8 0)" in schematic
    assert "\t\t(at 50.8 68.58 0)" in schematic
    assert '(label "OUT"\n\t\t(at 50.8 86.36 0)' in schematic


@pytest.mark.anyio
async def test_build_circuit_netlist_auto_layout_generates_wires(
    sample_project,
    mock_kicad,
) -> None:
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
            "nets": [
                {"name": "VIN", "endpoints": [{"reference": "R1", "pin": "1"}]},
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

    schematic = (sample_project / "demo.kicad_sch").read_text(encoding="utf-8")
    assert "Applied netlist-aware auto-layout" in result
    assert "generated 7 wire segment" in result
    assert '(label "VIN"' in schematic
    assert '(label "MID"' in schematic
    assert '(lib_id "power:GND")' in schematic
    assert "(pts (xy 53.34 50.8) (xy 86.36 50.8))" in schematic
    assert "(pts (xy 88.9 50.8) (xy 88.9 68.58))" in schematic


@pytest.mark.anyio
async def test_analyze_net_compilation_reports_routable_nets(
    sample_project,
    mock_kicad,
) -> None:
    server = build_server("schematic")

    result = await call_tool_text(
        server,
        "sch_analyze_net_compilation",
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
            "nets": [
                {"name": "VIN", "endpoints": [{"reference": "R1", "pin": "1"}]},
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

    assert "Net compilation analysis:" in result
    assert "- Nets requested: 3" in result
    assert "- Routable nets: 3" in result
    assert "- Unresolved nets: 0" in result
    assert "- Generated wire segments: 7" in result


@pytest.mark.anyio
async def test_analyze_net_compilation_reports_unresolved_endpoints(
    sample_project,
    mock_kicad,
) -> None:
    server = build_server("schematic")

    result = await call_tool_text(
        server,
        "sch_analyze_net_compilation",
        {
            "auto_layout": True,
            "symbols": [
                {
                    "library": "Device",
                    "symbol_name": "R",
                    "reference": "R1",
                    "value": "10k",
                    "footprint": "Resistor_SMD:R_0805",
                }
            ],
            "nets": [
                {
                    "name": "BROKEN_NET",
                    "endpoints": [
                        {"reference": "U9", "pin": "1"},
                        {"reference": "U10", "pin": "2"},
                    ],
                }
            ],
        },
    )

    assert "- Nets requested: 1" in result
    assert "- Routable nets: 0" in result
    assert "- Unresolved nets: 1" in result
    assert "BROKEN_NET" in result
    assert "U9.1" in result
    assert "U10.2" in result


@pytest.mark.anyio
async def test_build_circuit_netlist_auto_layout_raises_when_no_wires_resolve(
    sample_project,
    mock_kicad,
) -> None:
    server = build_server("schematic")

    with pytest.raises(Exception) as exc_info:
        await server.call_tool(
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
                    }
                ],
                "nets": [
                    {
                        "name": "BROKEN_NET",
                        "endpoints": [
                            {"reference": "U9", "pin": "1"},
                            {"reference": "U10", "pin": "2"},
                        ],
                    }
                ],
            },
        )

    error_text = str(exc_info.value)
    assert "could not generate any wire segments" in error_text
    assert "BROKEN_NET" in error_text
    assert "U9.1" in error_text
    assert "U10.2" in error_text


@pytest.mark.anyio
async def test_schematic_snap_to_grid_can_be_disabled(sample_project, mock_kicad) -> None:
    server = build_server("schematic")

    result = await call_tool_text(
        server,
        "sch_add_wire",
        {
            "x1_mm": 1.1,
            "y1_mm": 2.2,
            "x2_mm": 3.3,
            "y2_mm": 4.4,
            "snap_to_grid": False,
        },
    )

    schematic = (sample_project / "demo.kicad_sch").read_text(encoding="utf-8")
    assert "Grid snap" not in result
    assert "(pts (xy 1.1 2.2) (xy 3.3 4.4))" in schematic


@pytest.mark.anyio
async def test_schematic_pin_positions_use_electrical_pin_end(
    sample_project,
    mock_kicad,
) -> None:
    server = build_server("schematic")

    text = await call_tool_text(
        server,
        "sch_get_pin_positions",
        {"library": "Device", "symbol_name": "R", "x_mm": 10.16, "y_mm": 10.16},
    )

    assert "Pin 1: (7.6200, 10.1600)" in text
    assert "Pin 2: (12.7000, 10.1600)" in text


@pytest.mark.anyio
async def test_schematic_pin_positions_follow_extended_base_symbol(
    sample_project,
    mock_kicad,
) -> None:
    server = build_server("schematic")

    text = await call_tool_text(
        server,
        "sch_get_pin_positions",
        {"library": "Extended", "symbol_name": "ChildTimer", "x_mm": 20.0, "y_mm": 20.0},
    )

    assert "Pin 1: (17.4600, 20.0000)" in text
    assert "Pin 2: (22.5400, 20.0000)" in text


@pytest.mark.anyio
async def test_schematic_add_symbol_embeds_extended_symbol_chain(
    sample_project,
    mock_kicad,
) -> None:
    server = build_server("schematic")

    await call_tool_text(
        server,
        "sch_add_symbol",
        {
            "library": "Extended",
            "symbol_name": "ChildTimer",
            "x_mm": 20.0,
            "y_mm": 20.0,
            "reference": "U1",
            "value": "ChildTimer",
            "footprint": "Package_DIP:DIP-8_W7.62mm",
            "rotation": 0,
        },
    )

    schematic = (sample_project / "demo.kicad_sch").read_text(encoding="utf-8")
    assert '(symbol "BaseTimer"' in schematic
    assert '(symbol "Extended:ChildTimer"' in schematic


@pytest.mark.anyio
async def test_schematic_pin_positions_support_multi_unit_inherited_symbols(
    sample_project,
    mock_kicad,
) -> None:
    server = build_server("schematic")

    text = await call_tool_text(
        server,
        "sch_get_pin_positions",
        {
            "library": "MultiUnit",
            "symbol_name": "DualChild",
            "x_mm": 40.0,
            "y_mm": 40.0,
            "rotation": 0,
            "unit": 2,
        },
    )

    assert "unit=2" in text
    assert "Pin 5: (32.3800, 42.5400)" in text
    assert "Pin 6: (32.3800, 37.4600)" in text
    assert "Pin 7: (47.6200, 40.0000)" in text


@pytest.mark.anyio
async def test_schematic_add_symbol_records_requested_unit(sample_project, mock_kicad) -> None:
    server = build_server("schematic")

    await call_tool_text(
        server,
        "sch_add_symbol",
        {
            "library": "MultiUnit",
            "symbol_name": "DualChild",
            "x_mm": 30.0,
            "y_mm": 30.0,
            "reference": "U2",
            "value": "DualChild",
            "footprint": "Package_DIP:DIP-8_W7.62mm",
            "rotation": 0,
            "unit": 2,
        },
    )

    schematic = (sample_project / "demo.kicad_sch").read_text(encoding="utf-8")
    symbols = await call_tool_text(server, "sch_get_symbols", {})
    assert "\t\t(unit 2)\n" in schematic
    assert '(reference "U2") (unit 2)' in schematic
    assert "U2 DualChild MultiUnit:DualChild" in symbols
    assert "unit=2" in symbols


@pytest.mark.anyio
async def test_schematic_invalid_unit_reports_available_units(sample_project, mock_kicad) -> None:
    server = build_server("schematic")

    text = await call_tool_text(
        server,
        "sch_get_pin_positions",
        {
            "library": "MultiUnit",
            "symbol_name": "DualChild",
            "x_mm": 40.0,
            "y_mm": 40.0,
            "rotation": 0,
            "unit": 4,
        },
    )

    assert "does not support unit 4" in text
    assert "Available units: 1, 2, 3" in text


@pytest.mark.anyio
async def test_build_circuit_netlist_auto_layout_supports_extended_symbols(
    sample_project,
    mock_kicad,
) -> None:
    server = build_server("schematic")

    result = await call_tool_text(
        server,
        "sch_build_circuit",
        {
            "auto_layout": True,
            "symbols": [
                {
                    "library": "Extended",
                    "symbol_name": "ChildTimer",
                    "reference": "U1",
                    "value": "Timer",
                    "footprint": "Package_DIP:DIP-8_W7.62mm",
                },
                {
                    "library": "Device",
                    "symbol_name": "R",
                    "reference": "R1",
                    "value": "10k",
                    "footprint": "Resistor_SMD:R_0805",
                },
            ],
            "nets": [
                {
                    "name": "SIG",
                    "endpoints": [
                        {"reference": "U1", "pin": "2"},
                        {"reference": "R1", "pin": "1"},
                    ],
                },
                {"name": "GND", "endpoints": [{"reference": "U1", "pin": "1"}]},
            ],
        },
    )

    schematic = (sample_project / "demo.kicad_sch").read_text(encoding="utf-8")
    assert "Applied netlist-aware auto-layout" in result
    assert '(symbol "BaseTimer"' in schematic
    assert '(symbol "Extended:ChildTimer"' in schematic
    assert '(lib_id "power:GND")' in schematic
    assert schematic.count("(wire") >= 2


@pytest.mark.anyio
async def test_build_circuit_netlist_auto_layout_uses_symbol_unit_for_routing(
    sample_project,
    mock_kicad,
) -> None:
    server = build_server("schematic")

    result = await call_tool_text(
        server,
        "sch_build_circuit",
        {
            "auto_layout": True,
            "symbols": [
                {
                    "library": "MultiUnit",
                    "symbol_name": "DualChild",
                    "reference": "U1",
                    "value": "Dual",
                    "footprint": "Package_DIP:DIP-8_W7.62mm",
                    "unit": 2,
                },
                {
                    "library": "Device",
                    "symbol_name": "R",
                    "reference": "R1",
                    "value": "10k",
                    "footprint": "Resistor_SMD:R_0805",
                },
            ],
            "nets": [
                {
                    "name": "OUT2",
                    "endpoints": [
                        {"reference": "U1", "pin": "7"},
                        {"reference": "R1", "pin": "1"},
                    ],
                },
                {
                    "name": "FB2",
                    "endpoints": [
                        {"reference": "U1", "pin": "6"},
                        {"reference": "R1", "pin": "2"},
                    ],
                },
            ],
        },
    )

    schematic = (sample_project / "demo.kicad_sch").read_text(encoding="utf-8")
    assert "Applied netlist-aware auto-layout" in result
    assert '(symbol "DualOpamp"' in schematic
    assert '(symbol "MultiUnit:DualChild"' in schematic
    assert '(label "OUT2"' in schematic
    assert '(label "FB2"' in schematic
    assert schematic.count("(wire") >= 3


@pytest.mark.anyio
async def test_build_circuit_netlist_auto_layout_resolves_pin_names_and_aliases(
    sample_project,
    mock_kicad,
) -> None:
    server = build_server("schematic")

    result = await call_tool_text(
        server,
        "sch_build_circuit",
        {
            "auto_layout": True,
            "symbols": [
                {
                    "library": "MultiUnit",
                    "symbol_name": "DualChild",
                    "reference": "U1",
                    "value": "Dual",
                    "footprint": "Package_DIP:DIP-8_W7.62mm",
                    "unit": 1,
                },
                {
                    "library": "Device",
                    "symbol_name": "R",
                    "reference": "R1",
                    "value": "10k",
                    "footprint": "Resistor_SMD:R_0805",
                },
            ],
            "nets": [
                {
                    "name": "OUT_ALIAS",
                    "endpoints": [
                        {"reference": "U1", "pin_name": "OUTA"},
                        {"reference": "R1", "pin": "1"},
                    ],
                },
                {
                    "name": "INPUT_ALIAS",
                    "endpoints": [
                        {"reference": "U1", "pin": "+A"},
                        {"reference": "R1", "pin": "2"},
                    ],
                },
            ],
        },
    )

    schematic = (sample_project / "demo.kicad_sch").read_text(encoding="utf-8")
    assert "Applied netlist-aware auto-layout" in result
    assert '(label "OUT_ALIAS"' in schematic
    assert '(label "INPUT_ALIAS"' in schematic
    assert schematic.count("(wire") >= 3


@pytest.mark.anyio
async def test_library_assign_footprint_updates_schematic(sample_project, mock_kicad) -> None:
    server = build_server("schematic")
    await server.call_tool(
        "sch_add_symbol",
        {
            "library": "Device",
            "symbol_name": "R",
            "x_mm": 10.0,
            "y_mm": 10.0,
            "reference": "R1",
            "value": "10k",
            "footprint": "",
            "rotation": 0,
        },
    )
    text = await call_tool_text(
        server,
        "lib_assign_footprint",
        {"reference": "R1", "library": "Resistor_SMD", "footprint": "R_0805"},
    )
    assert "Assigned footprint" in text


@pytest.mark.anyio
async def test_schematic_update_property_escapes_quotes(sample_project, mock_kicad) -> None:
    server = build_server("schematic")
    await server.call_tool(
        "sch_add_symbol",
        {
            "library": "Device",
            "symbol_name": "R",
            "x_mm": 10.0,
            "y_mm": 10.0,
            "reference": "R1",
            "value": "10k",
            "footprint": "",
            "rotation": 0,
        },
    )

    text = await call_tool_text(
        server,
        "sch_update_properties",
        {"reference": "R1", "field": "Value", "value": '10k "1%"'},
    )

    schematic = (sample_project / "demo.kicad_sch").read_text(encoding="utf-8")
    assert "Updated R1.Value" in text
    assert '(property "Value" "10k \\"1%\\""' in schematic


@pytest.mark.anyio
async def test_analyze_net_compilation_reports_pin_alias_matches(
    sample_project,
    mock_kicad,
) -> None:
    server = build_server("schematic")

    result = await call_tool_text(
        server,
        "sch_analyze_net_compilation",
        {
            "auto_layout": True,
            "symbols": [
                {
                    "library": "MultiUnit",
                    "symbol_name": "DualChild",
                    "reference": "U1",
                    "value": "Dual",
                    "footprint": "Package_DIP:DIP-8_W7.62mm",
                    "unit": 1,
                },
                {
                    "library": "Device",
                    "symbol_name": "R",
                    "reference": "R1",
                    "value": "10k",
                    "footprint": "Resistor_SMD:R_0805",
                },
            ],
            "nets": [
                {
                    "name": "ALIAS_NET",
                    "endpoints": [
                        {"reference": "U1", "pin": "OUTA"},
                        {"reference": "R1", "pin": "1"},
                    ],
                }
            ],
        },
    )

    assert "- Pin alias matches: 1" in result
    assert "- Unresolved nets: 0" in result


@pytest.mark.anyio
async def test_schematic_create_and_inspect_child_sheets(sample_project, mock_kicad) -> None:
    server = build_server("schematic")

    result = await call_tool_text(
        server,
        "sch_create_sheet",
        {"name": "Power", "filename": "power.kicad_sch", "x_mm": 40.64, "y_mm": 50.8},
    )

    assert "Created child sheet 'Power'" in result
    assert (sample_project / "power.kicad_sch").exists()

    listing = await call_tool_text(server, "sch_list_sheets", {})
    assert "Power -> power.kicad_sch" in listing
    assert "size=(30.48, 20.32)" in listing

    info = await call_tool_text(server, "sch_get_sheet_info", {"sheet_name": "Power"})
    assert "Sheet 'Power'" in info
    assert "- File: power.kicad_sch" in info
    assert "- Page: 2" in info


@pytest.mark.anyio
async def test_schematic_global_and_hierarchical_labels_preserve_shape(
    sample_project,
    mock_kicad,
) -> None:
    server = build_server("schematic")

    await call_tool_text(
        server,
        "sch_add_global_label",
        {"text": "VCC", "x_mm": 25.4, "y_mm": 25.4, "shape": "output"},
    )
    await call_tool_text(
        server,
        "sch_add_hierarchical_label",
        {"text": "SIG", "x_mm": 30.48, "y_mm": 30.48, "shape": "bidirectional"},
    )

    schematic = (sample_project / "demo.kicad_sch").read_text(encoding="utf-8")
    assert '(global_label "VCC"' in schematic
    assert "\t\t(shape output)\n" in schematic
    assert '(hierarchical_label "SIG"' in schematic
    assert "\t\t(shape bidirectional)\n" in schematic


@pytest.mark.anyio
async def test_schematic_route_wire_between_pins_updates_connectivity_graph(
    sample_project,
    mock_kicad,
) -> None:
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

    route_text = await call_tool_text(
        server,
        "sch_route_wire_between_pins",
        {"ref1": "R1", "pin1": "2", "ref2": "R2", "pin2": "1"},
    )
    await call_tool_text(
        server,
        "sch_add_label",
        {"name": "MID", "x_mm": 12.7, "y_mm": 10.16, "rotation": 0},
    )

    graph = await call_tool_text(server, "sch_get_connectivity_graph", {})
    schematic = (sample_project / "demo.kicad_sch").read_text(encoding="utf-8")

    assert "Routed 1 wire segment" in route_text
    assert "(pts (xy 12.7 10.16) (xy 17.78 10.16))" in schematic
    assert "MID" in graph
    assert "R1:2" in graph
    assert "R2:1" in graph


@pytest.mark.anyio
async def test_schematic_trace_net_reports_child_sheet_matches(sample_project, mock_kicad) -> None:
    server = build_server("schematic")

    await call_tool_text(
        server,
        "sch_create_sheet",
        {"name": "Power", "filename": "power.kicad_sch", "x_mm": 40.64, "y_mm": 50.8},
    )
    await call_tool_text(
        server,
        "sch_create_sheet",
        {"name": "Control", "filename": "control.kicad_sch", "x_mm": 81.28, "y_mm": 50.8},
    )
    await call_tool_text(
        server,
        "sch_add_global_label",
        {"text": "VIN", "x_mm": 20.32, "y_mm": 20.32, "shape": "input"},
    )

    child_template = (
        "(kicad_sch\n"
        "\t(version 20250316)\n"
        '\t(generator "pytest")\n'
        '\t(uuid "11111111-1111-1111-1111-111111111111")\n'
        '\t(paper "A4")\n'
        "\t(lib_symbols)\n"
        '\t(hierarchical_label "VIN"\n'
        "\t\t(shape input)\n"
        "\t\t(at 10.16 10.16 0)\n"
        "\t\t(effects (font (size 1.27 1.27)))\n"
        '\t\t(uuid "22222222-2222-2222-2222-222222222222")\n'
        "\t)\n"
        "\t(sheet_instances\n"
        '\t\t(path "/" (page "1"))\n'
        "\t)\n"
        "\t(embedded_fonts no)\n"
        ")\n"
    )
    (sample_project / "power.kicad_sch").write_text(child_template, encoding="utf-8")
    (sample_project / "control.kicad_sch").write_text(child_template, encoding="utf-8")

    trace = await call_tool_text(server, "sch_trace_net", {"net_name": "VIN"})

    assert "Trace for net 'VIN':" in trace
    assert "Top level match" in trace
    assert "Child sheet matches:" in trace
    assert "Power" in trace
    assert "Control" in trace


@pytest.mark.anyio
async def test_schematic_auto_place_symbols_repositions_requested_references(
    sample_project,
    mock_kicad,
) -> None:
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
                    "footprint": "Resistor_SMD:R_0805",
                },
                {
                    "library": "Device",
                    "symbol_name": "R",
                    "x_mm": 10.16,
                    "y_mm": 20.32,
                    "reference": "R2",
                    "value": "22k",
                    "footprint": "Resistor_SMD:R_0805",
                },
            ],
        },
    )

    result = await call_tool_text(
        server,
        "sch_auto_place_symbols",
        {"symbol_list": ["R1", "R2"], "strategy": "linear"},
    )
    symbols = await call_tool_text(server, "sch_get_symbols", {})

    assert "Auto-placed 2 symbol(s) using the linear strategy." in result
    assert "R1 10k Device:R @ (50.80, 50.80)" in symbols
    assert "R2 22k Device:R @ (76.20, 50.80)" in symbols


# ── sch_build_circuit ──────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_build_circuit_empty(sample_project, mock_kicad) -> None:
    """sch_build_circuit with all empty lists must not raise."""
    server = build_server("schematic")
    text = await call_tool_text(
        server,
        "sch_build_circuit",
        {"symbols": [], "wires": [], "labels": [], "power_symbols": []},
    )
    # Any success response is acceptable
    assert text is not None


@pytest.mark.anyio
async def test_build_circuit_symbol_missing_fields_raises(sample_project, mock_kicad) -> None:
    """sch_build_circuit raises a clear ValidationError when required symbol fields are absent."""
    from pydantic import ValidationError

    server = build_server("schematic")
    with pytest.raises((ValidationError, Exception)) as exc_info:
        await server.call_tool(
            "sch_build_circuit",
            {
                "symbols": [{}],  # all required fields missing
                "wires": [],
                "labels": [],
                "power_symbols": [],
            },
        )
    # The error must mention the missing field names — not a bare KeyError
    assert "library" in str(exc_info.value) or "symbol_name" in str(exc_info.value)


@pytest.mark.anyio
async def test_build_circuit_wire_missing_fields_raises(sample_project, mock_kicad) -> None:
    """Wire dicts without required coords raise a clear ValidationError."""
    from pydantic import ValidationError

    server = build_server("schematic")
    with pytest.raises((ValidationError, Exception)) as exc_info:
        await server.call_tool(
            "sch_build_circuit",
            {"symbols": [], "wires": [{}], "labels": [], "power_symbols": []},
        )
    error_text = str(exc_info.value)
    assert any(field in error_text for field in ("x1_mm", "y1_mm", "x2_mm", "y2_mm"))


@pytest.mark.anyio
async def test_build_circuit_label_missing_fields_raises(sample_project, mock_kicad) -> None:
    """Label dicts without required fields raise a clear ValidationError."""
    from pydantic import ValidationError

    server = build_server("schematic")
    with pytest.raises((ValidationError, Exception)) as exc_info:
        await server.call_tool(
            "sch_build_circuit",
            {"symbols": [], "wires": [], "labels": [{}], "power_symbols": []},
        )
    error_text = str(exc_info.value)
    assert any(field in error_text for field in ("name", "x_mm", "y_mm"))


@pytest.mark.anyio
async def test_build_circuit_power_symbol_missing_fields_raises(sample_project, mock_kicad) -> None:
    """Power symbol dicts without required fields raise a clear ValidationError."""
    from pydantic import ValidationError

    server = build_server("schematic")
    with pytest.raises((ValidationError, Exception)) as exc_info:
        await server.call_tool(
            "sch_build_circuit",
            {"symbols": [], "wires": [], "labels": [], "power_symbols": [{}]},
        )
    error_text = str(exc_info.value)
    assert any(field in error_text for field in ("name", "x", "y"))


@pytest.mark.anyio
async def test_build_circuit_full_resistor(sample_project, mock_kicad) -> None:
    """sch_build_circuit places a resistor with a wire and a label end-to-end."""
    server = build_server("schematic")
    text = await call_tool_text(
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
                    "rotation": 0,
                }
            ],
            "wires": [{"x1_mm": 7.46, "y1_mm": 10.0, "x2_mm": 5.0, "y2_mm": 10.0}],
            "labels": [{"name": "NET_A", "x_mm": 5.0, "y_mm": 10.0, "rotation": 0}],
            "power_symbols": [],
        },
    )
    # Success or KiCad-not-connected message — either is acceptable in CI
    assert text is not None

    # Verify schematic file was written with the expected content
    import os
    from pathlib import Path

    sch_file = next(Path(os.environ["KICAD_MCP_PROJECT_DIR"]).glob("*.kicad_sch"))
    content = sch_file.read_text(encoding="utf-8")
    assert "Device:R" in content
    assert "R1" in content
    assert "NET_A" in content
