"""Thin FastMCP adapters for destructive schematic wire, symbol, and label edits."""

from __future__ import annotations

from dataclasses import dataclass

from mcp.server.fastmcp import FastMCP

from ..models.schematic import DeleteSymbolInput, DeleteWireInput, ModifyLabelInput
from ..schematic.destructive_edit import SchematicDestructiveEditService


@dataclass(frozen=True)
class SchematicDestructiveEditDependencies:
    """Destructive edit service injected by the schematic composition root."""

    service: SchematicDestructiveEditService


def register(mcp: FastMCP, dependencies: SchematicDestructiveEditDependencies) -> None:
    """Register destructive schematic edit tools."""
    service = dependencies.service

    @mcp.tool()
    def sch_delete_wire(wire_id: str) -> str:
        """Remove a specific wire segment using its UUID or unique UUID prefix."""
        payload = DeleteWireInput(wire_id=wire_id)
        return service.delete_wire(payload.wire_id)

    @mcp.tool()
    def sch_delete_symbol(reference: str) -> str:
        """Remove a placed symbol and any directly attached wire segments."""
        payload = DeleteSymbolInput(reference=reference)
        return service.delete_symbol(payload.reference)

    @mcp.tool()
    def sch_delete_label(name: str, x_mm: float, y_mm: float) -> str:
        """Delete label(s) (local/global/hierarchical) matching ``name`` at the
        given coordinate. Use sch_get_labels() to find exact names/positions."""
        return service.delete_label(name, x_mm, y_mm)

    @mcp.tool()
    def sch_delete_no_connect(x_mm: float, y_mm: float) -> str:
        """Delete the no-connect marker(s) at the given coordinate.
        Use sch_get_symbols()/sch_get_connectivity_graph() to find pin positions."""
        return service.delete_no_connect(x_mm, y_mm)

    @mcp.tool()
    def sch_move_label(
        name: str,
        x_mm: float,
        y_mm: float,
        new_x_mm: float,
        new_y_mm: float,
        new_rotation: int | None = None,
        snap_to_grid: bool = False,
    ) -> str:
        """Move the label matching ``name`` at (x_mm, y_mm) to a new coordinate,
        optionally re-rotating it. snap_to_grid defaults to False so the anchor
        can land exactly on a pin/wire endpoint."""
        return service.move_label(
            name,
            x_mm,
            y_mm,
            new_x_mm,
            new_y_mm,
            new_rotation,
            snap_to_grid,
        )

    @mcp.tool()
    def sch_modify_label(
        name: str,
        x_mm: float,
        y_mm: float,
        justify: str,
    ) -> str:
        """Set the text justification of an existing label (local/global/
        hierarchical) matching ``name`` at (x_mm, y_mm). Use sch_get_labels()
        to find exact names/positions.

        Global and hierarchical labels carry a directional icon at their
        anchor; KiCad centers unjustified text on that anchor, which overlaps
        the icon. Pass "left", "right", "top", "bottom", or a combination like
        "left top" to move the text clear of the icon, or "none" to restore
        KiCad's centered default.
        """
        payload = ModifyLabelInput(name=name, x_mm=x_mm, y_mm=y_mm, justify=justify)
        return service.modify_label(
            payload.name,
            payload.x_mm,
            payload.y_mm,
            payload.justify,
        )
