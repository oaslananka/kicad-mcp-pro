"""Shared constants for the schematic tool domain (issue #161).

Extracted verbatim from the monolithic ``schematic.py`` so the schematic tools
have a single, import-light source of truth for grid sizes, paper dimensions,
auto-layout spacing, power-net naming and the public tool-name list. Keeping these
here lets future domain submodules and the router share them without importing the
heavy registration module. This is the first incremental slice of the #161 split;
behaviour and values are unchanged.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Grid / snap
# ---------------------------------------------------------------------------

SCHEMATIC_GRID_MM = 2.54
SNAP_TOLERANCE_MM = 1e-6

# ---------------------------------------------------------------------------
# Auto-layout defaults
# ---------------------------------------------------------------------------

AUTO_LAYOUT_ORIGIN_X_MM = 50.8
AUTO_LAYOUT_ORIGIN_Y_MM = 50.8
AUTO_LAYOUT_COLUMN_SPACING_MM = 25.4
AUTO_LAYOUT_ROW_SPACING_MM = 17.78
AUTO_LAYOUT_COLUMNS = 4

# ---------------------------------------------------------------------------
# Sheet geometry defaults
# ---------------------------------------------------------------------------

DEFAULT_SHEET_WIDTH_MM = 30.48
DEFAULT_SHEET_HEIGHT_MM = 20.32

# Margin inside the sheet border kept free of symbols.
_SHEET_MARGIN_MM = 15.0

# ---------------------------------------------------------------------------
# Netlist layout helpers
# ---------------------------------------------------------------------------

NETLIST_LAYOUT_COLUMN_SPACING_MM = 38.1
NETLIST_LAYOUT_ROW_SPACING_MM = 35.56
NETLIST_LABEL_OFFSET_MM = 10.16
NETLIST_POWER_OFFSET_MM = 17.78

# ---------------------------------------------------------------------------
# KiCad paper sizes (landscape, mm).  Used for sheet-boundary clamping.
# ---------------------------------------------------------------------------

PAPER_SIZES_MM: dict[str, tuple[float, float]] = {
    "A4": (297.0, 210.0),
    "A3": (420.0, 297.0),
    "A2": (594.0, 420.0),
    "A1": (841.0, 594.0),
    "A0": (1189.0, 841.0),
    "A": (279.4, 215.9),  # ANSI A (letter)
    "B": (431.8, 279.4),  # ANSI B (tabloid)
    "C": (558.8, 431.8),
    "D": (863.6, 558.8),
    "E": (1117.6, 863.6),
    "USLetter": (279.4, 215.9),
    "USLegal": (355.6, 215.9),
}

# ---------------------------------------------------------------------------
# Power-net naming conventions
# ---------------------------------------------------------------------------

POWER_NET_NAMES = {
    "GND",
    "GNDA",
    "GNDD",
    "VCC",
    "VDD",
    "VSS",
    "+1V8",
    "+2V5",
    "+3V3",
    "+5V",
    "+12V",
    "-5V",
    "-12V",
    "VBUS_5V",
    "VPOE_5V",
    "VBAT",
    "5V_SYS",
    "3V3_DIG",
    "3V3_ANA",
    "VRTC",
}

ORIGIN_PIN_POWER_SYMBOL_NAMES = POWER_NET_NAMES | {
    "PWR_FLAG",
    "GNDPWR",
    "GNDREF",
    "Earth",
    "Earth_Protective",
    "Earth_Clean",
    "VAA",
    "VDD",
    "VDDA",
    "VDDD",
    "VEE",
    "VSSA",
    "VSSD",
}

# ---------------------------------------------------------------------------
# State directory
# ---------------------------------------------------------------------------

_SCHEMATIC_STATE_DIRNAME = ".kicad-mcp"

# ---------------------------------------------------------------------------
# Public tool name list (forward-declared here so registration and the router can
# both import it without pulling in the heavy registration module).
# ---------------------------------------------------------------------------

SCHEMATIC_PUBLIC_TOOL_NAMES = (
    "sch_get_symbols",
    "sch_get_wires",
    "sch_get_labels",
    "sch_get_net_names",
    "sch_add_symbol",
    "sch_add_wire",
    "sch_add_label",
    "sch_add_power_symbol",
    "sch_add_bus",
    "sch_add_bus_wire_entry",
    "sch_add_no_connect",
    "sch_update_properties",
    "sch_build_circuit",
    "sch_get_pin_positions",
    "sch_check_power_flags",
    "sch_annotate",
    "sch_reload",
    "sch_live_preview",
    "sch_create_sheet",
    "sch_add_hierarchical_label",
    "sch_add_global_label",
    "sch_list_sheets",
    "sch_get_sheet_info",
    "sch_route_wire_between_pins",
    "sch_add_missing_junctions",
    "sch_get_connectivity_graph",
    "sch_trace_net",
    "sch_auto_place_symbols",
    "sch_autoplace_fields",
    "sch_fix_readability",
)
