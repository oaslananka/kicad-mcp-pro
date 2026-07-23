"""Thin FastMCP adapters for schematic symbol property and placement mutations."""

from __future__ import annotations

from dataclasses import dataclass

from mcp.server.fastmcp import FastMCP

from ..models.schematic import MoveSymbolInput
from ..schematic.symbol_mutation import SchematicSymbolMutationService
from .metadata import headless_compatible


@dataclass(frozen=True)
class SchematicSymbolMutationDependencies:
    """Symbol mutation service injected by the schematic composition root."""

    service: SchematicSymbolMutationService


def register(mcp: FastMCP, dependencies: SchematicSymbolMutationDependencies) -> None:
    """Register non-destructive schematic symbol mutation tools."""
    service = dependencies.service

    @mcp.tool()
    @headless_compatible
    def sch_update_properties(reference: str, field: str, value: str) -> str:
        """Update a property on a placed symbol."""
        return service.update_properties(reference, field, value)

    @mcp.tool()
    @headless_compatible
    def sch_set_dnp(
        reference: str,
        enabled: bool = True,
        reason: str | None = None,
    ) -> str:
        """Set KiCad's native Do Not Populate flag on a placed symbol.

        When ``reason`` is given it is stored in the ``DNP Reason`` property so
        ``sch_get_population_status`` and variant BOMs can report why the part
        is unpopulated.
        """
        return service.set_dnp(reference, enabled, reason)

    @mcp.tool()
    @headless_compatible
    def sch_modify_property(reference: str, field: str, value: str) -> str:
        """Modify a schematic symbol property by reference."""
        return str(service.update_properties(reference, field, value))

    @mcp.tool()
    @headless_compatible
    def sch_move_symbol(
        reference: str,
        x_mm: float,
        y_mm: float,
        snap_to_grid: bool = True,
    ) -> str:
        """Move an existing symbol instance to a new absolute coordinate."""
        payload = MoveSymbolInput(
            reference=reference,
            x_mm=x_mm,
            y_mm=y_mm,
            snap_to_grid=snap_to_grid,
        )
        return service.move_symbol(
            payload.reference,
            payload.x_mm,
            payload.y_mm,
            payload.snap_to_grid,
        )
