"""Preserve externally placed symbols when reserving netlist layout cells."""

from __future__ import annotations

from kicad_mcp.tools.schematic import (
    AUTO_LAYOUT_ORIGIN_X_MM,
    AUTO_LAYOUT_ORIGIN_Y_MM,
    _existing_netlist_occupied_cells,
)


def test_existing_netlist_occupied_cells_excludes_unpositioned_symbols() -> None:
    symbols = [
        {
            "reference": "U1",
            "x_mm": AUTO_LAYOUT_ORIGIN_X_MM,
            "y_mm": AUTO_LAYOUT_ORIGIN_Y_MM,
        },
        {
            "reference": "U2",
            "x_mm": AUTO_LAYOUT_ORIGIN_X_MM + 25.4,
            "y_mm": AUTO_LAYOUT_ORIGIN_Y_MM + 17.78,
        },
        {"reference": "R1"},
        {"reference": "R2", "x_mm": None, "y_mm": None},
    ]
    actual = _existing_netlist_occupied_cells(symbols, 25.4, 17.78)
    assert actual == {(0, 0), (1, 1)}
