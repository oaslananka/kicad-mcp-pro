"""Tool routing and server profiles."""

from __future__ import annotations

from typing import TypedDict

from mcp.server.fastmcp import FastMCP


class ToolCategory(TypedDict):
    """Router metadata for a single tool category."""

    description: str
    tools: list[str]


EXPERIMENTAL_TOOL_NAMES: frozenset[str] = frozenset()
DEPRECATED_TOOL_NAMES: frozenset[str] = frozenset({"tune_track_length"})


def _display_tool_name(tool_name: str) -> str:
    suffixes: list[str] = []
    if tool_name in EXPERIMENTAL_TOOL_NAMES:
        suffixes.append("EXPERIMENTAL")
    if tool_name in DEPRECATED_TOOL_NAMES:
        suffixes.append("DEPRECATED")
    if not suffixes:
        return tool_name
    return f"{tool_name} [{' / '.join(suffixes)}]"


TOOL_CATEGORIES: dict[str, ToolCategory] = {
    "project": {
        "description": "Project setup, server discovery, and quick help.",
        "tools": [
            "kicad_set_project",
            "kicad_get_project_info",
            "kicad_list_recent_projects",
            "kicad_scan_directory",
            "kicad_create_new_project",
            "kicad_get_version",
            "kicad_list_tool_categories",
            "kicad_get_tools_in_category",
            "kicad_help",
        ],
    },
    "pcb_read": {
        "description": "Read PCB state including tracks, vias, footprints, nets, and layers.",
        "tools": [
            "pcb_get_board_summary",
            "pcb_get_tracks",
            "pcb_get_vias",
            "pcb_get_footprints",
            "pcb_get_nets",
            "pcb_get_zones",
            "pcb_get_shapes",
            "pcb_get_pads",
            "pcb_get_layers",
            "pcb_get_stackup",
            "pcb_get_selection",
            "pcb_get_board_as_string",
            "pcb_get_ratsnest",
            "pcb_get_design_rules",
        ],
    },
    "pcb_write": {
        "description": "Modify PCB geometry, sync initial footprints, and save board changes.",
        "tools": [
            "pcb_add_track",
            "pcb_add_tracks_bulk",
            "pcb_add_via",
            "pcb_add_segment",
            "pcb_add_circle",
            "pcb_add_rectangle",
            "pcb_add_text",
            "pcb_set_board_outline",
            "pcb_delete_items",
            "pcb_save",
            "pcb_refill_zones",
            "pcb_highlight_net",
            "pcb_set_net_class",
            "pcb_move_footprint",
            "pcb_set_footprint_layer",
            "pcb_sync_from_schematic",
        ],
    },
    "schematic": {
        "description": "Inspect and edit schematic files with hybrid IPC reload support.",
        "tools": [
            "sch_get_symbols",
            "sch_get_wires",
            "sch_get_labels",
            "sch_get_net_names",
            "sch_create_sheet",
            "sch_list_sheets",
            "sch_get_sheet_info",
            "sch_add_symbol",
            "sch_add_wire",
            "sch_add_label",
            "sch_add_global_label",
            "sch_add_hierarchical_label",
            "sch_add_power_symbol",
            "sch_add_bus",
            "sch_add_bus_wire_entry",
            "sch_add_no_connect",
            "sch_update_properties",
            "sch_build_circuit",
            "sch_get_pin_positions",
            "sch_route_wire_between_pins",
            "sch_get_connectivity_graph",
            "sch_trace_net",
            "sch_auto_place_symbols",
            "sch_check_power_flags",
            "sch_annotate",
            "sch_reload",
        ],
    },
    "library": {
        "description": "Search and inspect symbol/footprint libraries plus live component data.",
        "tools": [
            "lib_search_symbols",
            "lib_get_symbol_info",
            "lib_list_libraries",
            "lib_search_footprints",
            "lib_list_footprints",
            "lib_rebuild_index",
            "lib_get_footprint_info",
            "lib_get_footprint_3d_model",
            "lib_assign_footprint",
            "lib_create_custom_symbol",
            "lib_search_components",
            "lib_get_component_details",
            "lib_assign_lcsc_to_symbol",
            "lib_get_bom_with_pricing",
            "lib_check_stock_availability",
            "lib_find_alternative_parts",
            "lib_get_datasheet_url",
        ],
    },
    "export": {
        "description": "Produce manufacturing, review, and interchange exports.",
        "tools": [
            "run_drc",
            "run_erc",
            "validate_design",
            "export_gerber",
            "export_drill",
            "export_bom",
            "export_netlist",
            "export_spice_netlist",
            "export_pcb_pdf",
            "export_sch_pdf",
            "export_3d_step",
            "export_step",
            "export_3d_render",
            "export_pick_and_place",
            "export_ipc2581",
            "export_svg",
            "export_dxf",
            "export_manufacturing_package",
            "get_board_stats",
        ],
    },
    "validation": {
        "description": "Design validation, DFM checks, and rule inspection.",
        "tools": [
            "check_design_for_manufacture",
            "get_unconnected_nets",
            "get_courtyard_violations",
            "get_silk_to_pad_violations",
            "validate_footprints_vs_schematic",
        ],
    },
    "routing": {
        "description": (
            "Advanced routing helpers including FreeRouting orchestration and rule-file tuning."
        ),
        "tools": [
            "route_single_track",
            "route_from_pad_to_pad",
            "route_export_dsn",
            "route_import_ses",
            "route_autoroute_freerouting",
            "route_set_net_class_rules",
            "route_differential_pair",
            "route_tune_length",
            "tune_track_length",
            "tune_diff_pair_length",
        ],
    },
    "simulation": {
        "description": "Run SPICE operating-point, AC, transient, DC sweep, and stability checks.",
        "tools": [
            "sim_run_operating_point",
            "sim_run_ac_analysis",
            "sim_run_transient",
            "sim_run_dc_sweep",
            "sim_check_stability",
            "sim_add_spice_directive",
        ],
    },
}

PROFILE_CATEGORIES: dict[str, tuple[str, ...]] = {
    "full": tuple(TOOL_CATEGORIES.keys()),
    "minimal": ("project", "pcb_read", "export"),
    "pcb": ("project", "pcb_read", "pcb_write", "routing", "export", "validation"),
    "schematic": ("project", "schematic", "library", "export", "validation"),
    "manufacturing": ("project", "pcb_read", "export", "validation"),
}


def categories_for_profile(profile: str) -> tuple[str, ...]:
    """Resolve categories enabled by the named server profile."""
    return PROFILE_CATEGORIES.get(profile, PROFILE_CATEGORIES["full"])


def register(mcp: FastMCP) -> None:
    """Register category discovery tools."""

    @mcp.tool()
    def kicad_list_tool_categories() -> str:
        """List all available tool categories and capabilities."""
        lines = ["# KiCad MCP Pro Tool Categories", ""]
        for category, info in TOOL_CATEGORIES.items():
            tools = info["tools"]
            lines.append(f"## `{category}`")
            lines.append(str(info["description"]))
            lines.append(f"Tools: {len(tools)}")
            lines.append("")
        return "\n".join(lines)

    @mcp.tool()
    def kicad_get_tools_in_category(category: str) -> str:
        """Get the tool names available in a specific category."""
        info = TOOL_CATEGORIES.get(category)
        if info is None:
            available = ", ".join(sorted(TOOL_CATEGORIES))
            return f"Unknown category '{category}'. Available categories: {available}"

        lines = [f"# Tools in `{category}`", str(info["description"]), ""]
        for tool_name in info["tools"]:
            lines.append(f"- `{_display_tool_name(tool_name)}`")
        return "\n".join(lines)
