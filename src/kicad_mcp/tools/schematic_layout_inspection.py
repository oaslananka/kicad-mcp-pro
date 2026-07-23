"""Thin FastMCP adapters for schematic layout inspection."""

# pyright: reportUnusedFunction=false

from __future__ import annotations

from dataclasses import dataclass

from mcp.server.fastmcp import FastMCP

from ..schematic.layout_inspection import SchematicLayoutInspectionService
from .metadata import headless_compatible
from .schematic_constants import AUTO_LAYOUT_COLUMN_SPACING_MM, AUTO_LAYOUT_ROW_SPACING_MM


@dataclass(frozen=True)
class SchematicLayoutInspectionDependencies:
    """Layout-inspection service injected by the schematic composition root."""

    service: SchematicLayoutInspectionService


def register(mcp: FastMCP, dependencies: SchematicLayoutInspectionDependencies) -> None:
    """Register read-only schematic layout inspection tools."""
    service = dependencies.service

    @mcp.tool()
    @headless_compatible
    def sch_get_bounding_boxes() -> str:
        """Return the estimated bounding box of every symbol in the active schematic.

        Use this before calling sch_add_symbol or sch_build_circuit to understand
        which areas of the schematic sheet are already occupied.  The bounding boxes
        are heuristic estimates (KiCad does not expose exact extents via the file API)
        but are conservative enough to avoid overlap in practice.

        Returns:
            A table of all symbols with their centre position and estimated
            bounding-box corners (x_min, y_min, x_max, y_max) in mm, plus an
            occupied-area summary.
        """
        return service.bounding_boxes()

    @mcp.tool()
    @headless_compatible
    def sch_find_free_placement(
        count: int = 1,
        cell_width_mm: float = AUTO_LAYOUT_COLUMN_SPACING_MM,
        cell_height_mm: float = AUTO_LAYOUT_ROW_SPACING_MM,
        keepout_regions: list[tuple[float, float, float, float]] | None = None,
    ) -> str:
        """Find N collision-free placement coordinates for new symbols.

        Reads the current schematic, builds an occupancy grid from all existing
        symbols, and returns ``count`` coordinate pairs that do not overlap with
        any placed symbol.  Call this before sch_add_symbol to get safe (x, y)
        values.

        Args:
            count: Number of free coordinate slots to return (default 1, max 64).
            cell_width_mm: Grid cell width in mm (default 25.4 — one 10-mil grid unit).
            cell_height_mm: Grid cell height in mm (default 17.78).
            keepout_regions: Optional rectangular keepouts as
                ``[(x_min, y_min, x_max, y_max), ...]`` in mm.

        Returns:
            A list of (x_mm, y_mm) coordinate pairs, one per requested slot.
        """
        return service.free_placement(
            count,
            cell_width_mm,
            cell_height_mm,
            keepout_regions,
        )
