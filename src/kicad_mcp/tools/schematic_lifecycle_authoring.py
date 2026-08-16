"""Thin FastMCP adapter for schematic lifecycle authoring."""

# pyright: reportUnusedFunction=false

from __future__ import annotations

from dataclasses import dataclass

from mcp.server.fastmcp import FastMCP

from ..schematic.lifecycle_authoring import SchematicLifecycleAuthoringService
from .metadata import headless_compatible, requires_kicad_running


@dataclass(frozen=True)
class SchematicLifecycleAuthoringDependencies:
    """Lifecycle service injected by the schematic composition root."""

    service: SchematicLifecycleAuthoringService


def register(mcp: FastMCP, dependencies: SchematicLifecycleAuthoringDependencies) -> None:
    """Register schematic lifecycle-authoring tools."""
    service = dependencies.service

    @mcp.tool()
    @headless_compatible
    def sch_add_jumper(
        x_mm: float,
        y_mm: float,
        pins: int = 2,
        open_by_default: bool = True,
        snap_to_grid: bool = True,
    ) -> str:
        """Add a jumper symbol to the schematic."""
        return service.add_jumper(
            x_mm=x_mm,
            y_mm=y_mm,
            pins=pins,
            open_by_default=open_by_default,
            snap_to_grid=snap_to_grid,
        )

    @mcp.tool()
    @mcp.tool()
    @mcp.tool()
    def sch_annotate(start_number: int = 1, order: str = "alpha") -> str:
        """Renumber schematic references sequentially."""
        return service.annotate(start_number=start_number, order=order)

    @mcp.tool()
    @requires_kicad_running
    def sch_reload() -> str:
        """Ask KiCad to reload the active schematic."""
        return service.reload()
