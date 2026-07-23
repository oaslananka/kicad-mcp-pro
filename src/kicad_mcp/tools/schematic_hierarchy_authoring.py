"""Thin FastMCP adapters for schematic hierarchy authoring."""

# pyright: reportUnusedFunction=false

from __future__ import annotations

from dataclasses import dataclass

from mcp.server.fastmcp import FastMCP

from ..models.schematic import CreateSheetInput, GlobalLabelInput, HierarchicalLabelInput
from ..schematic.hierarchy_authoring import SchematicHierarchyAuthoringService


@dataclass(frozen=True)
class SchematicHierarchyAuthoringDependencies:
    """Hierarchy-authoring service injected by the schematic composition root."""

    service: SchematicHierarchyAuthoringService


def register(mcp: FastMCP, dependencies: SchematicHierarchyAuthoringDependencies) -> None:
    """Register child-sheet and hierarchy-label authoring tools."""
    service = dependencies.service

    @mcp.tool()
    def sch_create_sheet(
        name: str,
        filename: str,
        x_mm: float,
        y_mm: float,
        snap_to_grid: bool = True,
    ) -> str:
        """Create a child schematic sheet and add it to the active top-level schematic."""
        payload = CreateSheetInput(
            name=name,
            filename=filename,
            x_mm=x_mm,
            y_mm=y_mm,
            snap_to_grid=snap_to_grid,
        )
        return service.create_sheet(
            payload.name,
            payload.filename,
            payload.x_mm,
            payload.y_mm,
            payload.snap_to_grid,
        )

    @mcp.tool()
    def sch_add_hierarchical_label(
        text: str | None = None,
        x_mm: float = 0.0,
        y_mm: float = 0.0,
        shape: str = "input",
        rotation: int = 0,
        snap_to_grid: bool = True,
        name: str | None = None,
        justify: str | None = None,
        sheet: str | None = None,
        sheet_file: str | None = None,
    ) -> str:
        """Add a hierarchical label, preserving the requested shape and rotation.

        By default the text is justified away from the directional icon based
        on ``rotation`` (0=left, 90=bottom, 180=right, 270=top) so it doesn't
        render on top of the icon. Pass ``justify`` to override, or "none" to
        force KiCad's centered default.
        """
        label_text = text or name
        if not label_text:
            raise ValueError("Either text or name parameter is required.")
        payload = HierarchicalLabelInput.model_validate(
            {
                "text": label_text,
                "x_mm": x_mm,
                "y_mm": y_mm,
                "shape": shape,
                "rotation": rotation,
                "snap_to_grid": snap_to_grid,
                "justify": justify,
            }
        )
        return service.add_hierarchical_label(
            payload.text,
            payload.x_mm,
            payload.y_mm,
            payload.shape,
            payload.rotation,
            payload.snap_to_grid,
            payload.justify,
            sheet,
            sheet_file,
        )

    @mcp.tool()
    def sch_add_global_label(
        text: str | None = None,
        x_mm: float = 0.0,
        y_mm: float = 0.0,
        shape: str = "bidirectional",
        rotation: int = 0,
        snap_to_grid: bool = True,
        name: str | None = None,
        justify: str | None = None,
        sheet: str | None = None,
        sheet_file: str | None = None,
    ) -> str:
        """Add a global label, preserving the requested shape and rotation.

        By default the text is justified away from the directional icon based
        on ``rotation`` (0=left, 90=bottom, 180=right, 270=top) so it doesn't
        render on top of the icon. Pass ``justify`` to override, or "none" to
        force KiCad's centered default.
        """
        label_text = text or name
        if not label_text:
            raise ValueError("Either text or name parameter is required.")
        payload = GlobalLabelInput.model_validate(
            {
                "text": label_text,
                "x_mm": x_mm,
                "y_mm": y_mm,
                "shape": shape,
                "rotation": rotation,
                "snap_to_grid": snap_to_grid,
                "justify": justify,
            }
        )
        return service.add_global_label(
            payload.text,
            payload.x_mm,
            payload.y_mm,
            payload.shape,
            payload.rotation,
            payload.snap_to_grid,
            payload.justify,
            sheet,
            sheet_file,
        )
