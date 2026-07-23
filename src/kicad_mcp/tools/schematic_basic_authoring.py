"""Thin FastMCP adapters for basic schematic authoring tools."""

from __future__ import annotations

from dataclasses import dataclass

from mcp.server.fastmcp import FastMCP

from ..models.schematic import AddLabelInput, AddSymbolInput, AddWireInput
from ..schematic.basic_authoring import SchematicBasicAuthoringService
from .metadata import headless_compatible


@dataclass(frozen=True)
class SchematicBasicAuthoringDependencies:
    """Basic authoring service injected by the schematic composition root."""

    service: SchematicBasicAuthoringService


def register(mcp: FastMCP, dependencies: SchematicBasicAuthoringDependencies) -> None:
    """Register basic schematic symbol, wire, and label authoring tools."""
    service = dependencies.service

    def validated_add_symbol(
        library: str,
        symbol_name: str,
        x_mm: float,
        y_mm: float,
        reference: str,
        value: str,
        footprint: str,
        rotation: int,
        snap_to_grid: bool,
        unit: int,
        sheet: str | None,
        sheet_file: str | None,
    ) -> str:
        payload = AddSymbolInput(
            library=library,
            symbol_name=symbol_name,
            x_mm=x_mm,
            y_mm=y_mm,
            reference=reference,
            value=value,
            footprint=footprint,
            rotation=rotation,
            snap_to_grid=snap_to_grid,
            unit=unit,
        )
        return service.add_symbol(
            payload.library,
            payload.symbol_name,
            payload.x_mm,
            payload.y_mm,
            payload.reference,
            payload.value,
            payload.footprint,
            payload.rotation,
            payload.snap_to_grid,
            payload.unit,
            sheet,
            sheet_file,
        )

    @mcp.tool()
    @headless_compatible
    def sch_add_symbol(
        library: str,
        symbol_name: str,
        x_mm: float,
        y_mm: float,
        reference: str,
        value: str,
        footprint: str = "",
        rotation: int = 0,
        snap_to_grid: bool = True,
        unit: int = 1,
        sheet: str | None = None,
        sheet_file: str | None = None,
    ) -> str:
        """Add a schematic symbol at an absolute coordinate.

        Coordinates snap to the 1.27 mm / 50 mil schematic grid by default; set
        snap_to_grid=False only when an exact off-grid coordinate is intentional."""
        return validated_add_symbol(
            library,
            symbol_name,
            x_mm,
            y_mm,
            reference,
            value,
            footprint,
            rotation,
            snap_to_grid,
            unit,
            sheet,
            sheet_file,
        )

    @mcp.tool()
    @headless_compatible
    def sch_add_component(
        library: str,
        symbol_name: str,
        x_mm: float,
        y_mm: float,
        reference: str,
        value: str,
        footprint: str = "",
        rotation: int = 0,
        snap_to_grid: bool = True,
        unit: int = 1,
        sheet: str | None = None,
        sheet_file: str | None = None,
    ) -> str:
        """Add a schematic component through the hybrid IPC reload path."""
        return validated_add_symbol(
            library,
            symbol_name,
            x_mm,
            y_mm,
            reference,
            value,
            footprint,
            rotation,
            snap_to_grid,
            unit,
            sheet,
            sheet_file,
        )

    @mcp.tool()
    def sch_add_wire(
        x1_mm: float,
        y1_mm: float,
        x2_mm: float,
        y2_mm: float,
        snap_to_grid: bool = True,
        sheet: str | None = None,
        sheet_file: str | None = None,
    ) -> str:
        """Add a schematic wire, snapping endpoints to the 1.27 mm / 50 mil grid by default."""
        payload = AddWireInput(
            x1_mm=x1_mm,
            y1_mm=y1_mm,
            x2_mm=x2_mm,
            y2_mm=y2_mm,
            snap_to_grid=snap_to_grid,
        )
        return service.add_wire(
            payload.x1_mm,
            payload.y1_mm,
            payload.x2_mm,
            payload.y2_mm,
            payload.snap_to_grid,
            sheet,
            sheet_file,
        )

    @mcp.tool()
    def sch_add_label(
        name: str | None = None,
        x_mm: float = 0.0,
        y_mm: float = 0.0,
        rotation: int = 0,
        snap_to_grid: bool = True,
        text: str | None = None,
        justify: str | None = None,
        sheet: str | None = None,
        sheet_file: str | None = None,
    ) -> str:
        """Add a schematic label, snapping its anchor to the 1.27 mm / 50 mil grid by default.

        ``justify`` overrides KiCad's centered default (e.g. "left", "right",
        "top", "bottom", "left top"); local labels have no directional icon so
        centered text is usually correct and this is rarely needed."""
        label_text = name or text
        if not label_text:
            raise ValueError("Either name or text parameter is required.")
        payload = AddLabelInput(
            name=label_text,
            x_mm=x_mm,
            y_mm=y_mm,
            rotation=rotation,
            snap_to_grid=snap_to_grid,
            justify=justify,
        )
        return service.add_label(
            payload.name,
            payload.x_mm,
            payload.y_mm,
            payload.rotation,
            payload.snap_to_grid,
            payload.justify,
            sheet,
            sheet_file,
        )

    @mcp.tool()
    def sch_add_power_symbol(
        name: str,
        x_mm: float,
        y_mm: float,
        rotation: int = 0,
        snap_to_grid: bool = True,
        sheet: str | None = None,
        sheet_file: str | None = None,
    ) -> str:
        """Add a power symbol, snapping its anchor to the 1.27 mm / 50 mil grid by default."""
        return service.add_power_symbol(
            name,
            x_mm,
            y_mm,
            rotation,
            snap_to_grid,
            sheet,
            sheet_file,
        )
