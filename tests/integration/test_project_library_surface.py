from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from kicad_mcp import __version__
from kicad_mcp.server import build_server
from kicad_mcp.utils.component_search import ComponentRecord
from tests.conftest import call_tool_text, get_prompt_text, read_resource_text


@pytest.mark.anyio
async def test_project_resources_prompts_and_library_surface(
    sample_project: Path,
    mock_board,
    mock_kicad,
    monkeypatch,
) -> None:
    _ = mock_board, mock_kicad
    project_file = sample_project / "demo.kicad_pro"
    monkeypatch.setattr(
        "kicad_mcp.tools.project.find_recent_projects",
        lambda limit=10: [project_file],
    )

    server = build_server("full")

    text = await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})
    assert "Current project configuration" in text
    assert str(sample_project) in text

    info = await call_tool_text(server, "kicad_get_project_info", {})
    scan = await call_tool_text(server, "kicad_scan_directory", {"path": str(sample_project)})
    recent = await call_tool_text(server, "kicad_list_recent_projects", {})
    version = await call_tool_text(server, "kicad_get_version", {})
    help_text = await call_tool_text(server, "kicad_help", {})
    categories = await call_tool_text(server, "kicad_list_tool_categories", {})
    category_tools = await call_tool_text(
        server, "kicad_get_tools_in_category", {"category": "project"}
    )
    library_tools = await call_tool_text(
        server, "kicad_get_tools_in_category", {"category": "library"}
    )
    routing_tools = await call_tool_text(
        server, "kicad_get_tools_in_category", {"category": "routing"}
    )
    pcb_write_tools = await call_tool_text(
        server, "kicad_get_tools_in_category", {"category": "pcb_write"}
    )
    simulation_tools = await call_tool_text(
        server, "kicad_get_tools_in_category", {"category": "simulation"}
    )
    si_tools = await call_tool_text(
        server, "kicad_get_tools_in_category", {"category": "signal_integrity"}
    )
    power_tools = await call_tool_text(
        server, "kicad_get_tools_in_category", {"category": "power_integrity"}
    )
    emc_tools = await call_tool_text(server, "kicad_get_tools_in_category", {"category": "emc"})

    assert "Project directory" in info
    assert "Scan results" in scan
    assert "recent project" in recent.lower()
    assert "KiCad MCP Pro Server" in version
    assert f"v{__version__}" in version
    assert "Quick Start" in help_text
    assert "pcb_read" in categories
    assert "kicad_get_version" in category_tools
    assert "pcb_auto_place_by_schematic" in pcb_write_tools
    assert "pcb_set_keepout_zone" in pcb_write_tools
    assert "pcb_add_teardrops" in pcb_write_tools
    assert "lib_search_components" in library_tools
    assert "lib_get_component_details" in library_tools
    assert "lib_get_bom_with_pricing" in library_tools
    assert "route_autoroute_freerouting" in routing_tools
    assert "route_differential_pair" in routing_tools
    assert "tune_track_length [DEPRECATED]" in routing_tools
    assert "sim_run_operating_point" in simulation_tools
    assert "sim_check_stability" in simulation_tools
    assert "si_calculate_trace_impedance" in si_tools
    assert "si_check_differential_pair_skew" in si_tools
    assert "pdn_calculate_voltage_drop" in power_tools
    assert "pdn_generate_power_plane" in power_tools
    assert "emc_check_ground_plane_voids" in emc_tools
    assert "emc_run_full_compliance" in emc_tools

    created = await call_tool_text(
        server,
        "kicad_create_new_project",
        {"path": str(sample_project.parent), "name": "fresh_project"},
    )
    assert "Created project 'fresh_project'" in created

    project_resource = await read_resource_text(server, "kicad://project/info")
    board_summary = await read_resource_text(server, "kicad://board/summary")
    board_netlist = await read_resource_text(server, "kicad://board/netlist")
    first_pcb = await get_prompt_text(
        server,
        "first_pcb",
        {"component_count": "4", "board_size_mm": "20x20", "layers": "2"},
    )
    schematic_to_pcb = await get_prompt_text(server, "schematic_to_pcb", {})
    manufacturing = await get_prompt_text(server, "manufacturing_export", {})

    assert "Project directory:" in project_resource
    assert "Board summary" in board_summary
    assert "(kicad_pcb)" in board_netlist
    assert "20x20" in first_pcb
    assert "schematic capture" in schematic_to_pcb.lower()
    assert "manufacturing readiness" in manufacturing.lower()

    await call_tool_text(
        server,
        "sch_build_circuit",
        {
            "symbols": [
                {
                    "library": "Device",
                    "symbol_name": "R",
                    "x_mm": 20.0,
                    "y_mm": 20.0,
                    "reference": "R1",
                    "value": "10k resistor",
                    "footprint": "Resistor_SMD:R_0805",
                    "rotation": 0,
                },
                {
                    "library": "Device",
                    "symbol_name": "R",
                    "x_mm": 35.0,
                    "y_mm": 20.0,
                    "reference": "R2",
                    "value": "10k resistor",
                    "footprint": "Resistor_SMD:R_0805",
                    "rotation": 0,
                },
            ]
        },
    )

    class FakeComponentClient:
        def search(self, keyword, *, package=None, only_basic=True, limit=20):
            _ = (keyword, package, only_basic, limit)
            return [
                ComponentRecord(
                    source="jlcsearch",
                    lcsc_code="C25804",
                    mpn="0603WAF1002T5E",
                    package="0603",
                    description="10k resistor",
                    stock=37_165_617,
                    price=0.000842857,
                    is_basic=True,
                    is_preferred=False,
                ),
                ComponentRecord(
                    source="jlcsearch",
                    lcsc_code="C17414",
                    mpn="0805W8F1002T5E",
                    package="0805",
                    description="10k resistor",
                    stock=15_457_503,
                    price=0.001642857,
                    is_basic=True,
                    is_preferred=False,
                ),
            ]

        def get_part(self, lcsc_code_or_mpn):
            query = str(lcsc_code_or_mpn).upper()
            if query in {"C25804", "10K RESISTOR"}:
                return ComponentRecord(
                    source="jlcsearch",
                    lcsc_code="C25804",
                    mpn="0603WAF1002T5E",
                    package="0603",
                    description="10k resistor",
                    stock=37_165_617,
                    price=0.000842857,
                    is_basic=True,
                    is_preferred=False,
                )
            if query == "C17414":
                return ComponentRecord(
                    source="jlcsearch",
                    lcsc_code="C17414",
                    mpn="0805W8F1002T5E",
                    package="0805",
                    description="10k resistor",
                    stock=15_457_503,
                    price=0.001642857,
                    is_basic=True,
                    is_preferred=False,
                )
            return None

    monkeypatch.setattr(
        "kicad_mcp.tools.library._component_search_client",
        lambda source: FakeComponentClient(),
    )

    libraries = await call_tool_text(server, "lib_list_libraries", {})
    symbols = await call_tool_text(server, "lib_search_symbols", {"query": "resistor"})
    symbol_info = await call_tool_text(
        server, "lib_get_symbol_info", {"library": "Device", "symbol_name": "R"}
    )
    footprints = await call_tool_text(server, "lib_search_footprints", {"query": "0805"})
    footprint_list = await call_tool_text(
        server, "lib_list_footprints", {"library": "Resistor_SMD"}
    )
    rebuild = await call_tool_text(server, "lib_rebuild_index", {})
    footprint_info = await call_tool_text(
        server,
        "lib_get_footprint_info",
        {"library": "Resistor_SMD", "footprint": "R_0805"},
    )
    footprint_model = await call_tool_text(
        server,
        "lib_get_footprint_3d_model",
        {"library": "Resistor_SMD", "footprint": "R_0805"},
    )
    datasheet = await call_tool_text(
        server,
        "lib_get_datasheet_url",
        {"library": "Device", "symbol_name": "R"},
    )
    assigned_lcsc = await call_tool_text(
        server,
        "lib_assign_lcsc_to_symbol",
        {"reference": "R1", "lcsc_code": "25804"},
    )
    component_search = await call_tool_text(
        server,
        "lib_search_components",
        {"keyword": "10k resistor", "source": "jlcsearch"},
    )
    component_details = await call_tool_text(
        server,
        "lib_get_component_details",
        {"lcsc_code_or_mpn": "C25804", "source": "jlcsearch"},
    )
    bom = await call_tool_text(
        server,
        "lib_get_bom_with_pricing",
        {"quantity": 5, "source": "jlcsearch"},
    )
    stock = await call_tool_text(
        server,
        "lib_check_stock_availability",
        {"refs": ["R1", "R2"], "source": "jlcsearch"},
    )
    alternatives = await call_tool_text(
        server,
        "lib_find_alternative_parts",
        {"lcsc_code": "C25804", "tolerance_percent": 100.0, "source": "jlcsearch"},
    )
    custom = await call_tool_text(
        server,
        "lib_create_custom_symbol",
        {
            "name": "CustomU",
            "pins": [{"number": "1", "name": "IN"}, {"number": "2", "name": "OUT"}],
        },
    )

    assert "Symbol libraries" in libraries
    assert "Device:R" in symbols
    assert "Datasheet" in symbol_info
    assert "R_0805" in footprints
    assert "Footprints in Resistor_SMD" in footprint_list
    assert "Rebuilt the symbol index" in rebuild
    assert "3D model" in footprint_info
    assert "R_0805.wrl" in footprint_model
    assert datasheet == "https://example.com/r.pdf"
    assert "Assigned LCSC code 'C25804'" in assigned_lcsc
    assert "Live component matches" in component_search
    assert "C25804" in component_search
    assert "Component details from jlcsearch" in component_details
    assert "Live BOM with pricing from jlcsearch" in bom
    assert "Estimated total" in bom
    assert "Stock availability from jlcsearch" in stock
    assert "Alternative parts for C25804" in alternatives
    assert "C17414" in alternatives
    assert "Created custom symbol" in custom


@pytest.mark.anyio
async def test_schematic_surface(sample_project: Path, mock_kicad) -> None:
    _ = mock_kicad
    server = build_server("schematic")

    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    no_symbols = await call_tool_text(server, "sch_get_symbols", {})
    no_wires = await call_tool_text(server, "sch_get_wires", {})
    no_labels = await call_tool_text(server, "sch_get_labels", {})
    no_nets = await call_tool_text(server, "sch_get_net_names", {})

    assert "no symbols" in no_symbols.lower()
    assert "no wires" in no_wires.lower()
    assert "no labels" in no_labels.lower()
    assert "No named nets" in no_nets

    results = await asyncio.gather(
        call_tool_text(
            server,
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
        ),
        call_tool_text(
            server,
            "sch_add_wire",
            {"x1_mm": 10.0, "y1_mm": 10.0, "x2_mm": 20.0, "y2_mm": 10.0},
        ),
        call_tool_text(
            server,
            "sch_add_label",
            {"name": "NET_A", "x_mm": 15.0, "y_mm": 10.0, "rotation": 0},
        ),
        call_tool_text(
            server,
            "sch_add_power_symbol",
            {"name": "GND", "x_mm": 5.0, "y_mm": 5.0, "rotation": 0},
        ),
        call_tool_text(
            server,
            "sch_add_bus",
            {"x1_mm": 0.0, "y1_mm": 0.0, "x2_mm": 30.0, "y2_mm": 0.0},
        ),
        call_tool_text(
            server,
            "sch_add_bus_wire_entry",
            {"x_mm": 12.54, "y_mm": 0.0, "direction": "down_right"},
        ),
        call_tool_text(server, "sch_add_no_connect", {"x_mm": 25.0, "y_mm": 25.0}),
    )

    assert any("updated" in result.lower() or "reload" in result.lower() for result in results)

    assigned = await call_tool_text(
        server,
        "lib_assign_footprint",
        {"reference": "R1", "library": "Resistor_SMD", "footprint": "R_1206"},
    )
    props = await call_tool_text(
        server,
        "sch_update_properties",
        {"reference": "R1", "field": "Value", "value": "22k"},
    )
    symbols = await call_tool_text(server, "sch_get_symbols", {})
    wire_text = await call_tool_text(server, "sch_get_wires", {})
    labels = await call_tool_text(server, "sch_get_labels", {})
    nets = await call_tool_text(server, "sch_get_net_names", {})
    pins = await call_tool_text(
        server,
        "sch_get_pin_positions",
        {"library": "Device", "symbol_name": "R", "x_mm": 10.0, "y_mm": 10.0, "rotation": 0},
    )
    power = await call_tool_text(server, "sch_check_power_flags", {})
    annotated = await call_tool_text(server, "sch_annotate", {"start_number": 1, "order": "sheet"})
    built = await call_tool_text(
        server,
        "sch_build_circuit",
        {
            "symbols": [
                {
                    "library": "Device",
                    "symbol_name": "R",
                    "x_mm": 30.0,
                    "y_mm": 30.0,
                    "reference": "R9",
                    "value": "1k",
                    "footprint": "",
                    "rotation": 0,
                }
            ],
            "wires": [{"x1_mm": 30.0, "y1_mm": 30.0, "x2_mm": 35.0, "y2_mm": 30.0}],
            "labels": [{"name": "NET_B", "x_mm": 32.0, "y_mm": 30.0, "rotation": 0}],
            "power_symbols": [{"name": "GND", "x": 29.0, "y": 29.0, "rotation": 0}],
        },
    )
    reload_text = await call_tool_text(server, "sch_reload", {})
    sch_text = (sample_project / "demo.kicad_sch").read_text(encoding="utf-8")

    assert "Assigned footprint 'Resistor_SMD:R_1206'" in assigned
    assert "Updated R1.Value" in props
    assert "R1 22k" in symbols
    assert "footprint=Resistor_SMD:R_1206" in symbols
    assert "Wires" in wire_text
    assert "NET_A" in labels
    assert "NET_A" in nets
    assert "Pin 1" in pins
    assert "Pin 2" in pins
    assert "Pin A" not in pins
    assert "power flags" in power.lower()
    assert "Annotated" in annotated
    assert "reload" in built.lower() or "updated" in built.lower()
    assert "reload" in reload_text.lower() or "updated" in reload_text.lower()
    assert '(symbol "power:GND"' in sch_text
    assert '(symbol "GND_0_1"' in sch_text
    assert "power:GND_0_1" not in sch_text
