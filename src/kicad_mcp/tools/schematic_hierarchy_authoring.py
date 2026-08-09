"""Thin FastMCP adapters for schematic hierarchy authoring."""

# pyright: reportUnusedFunction=false

from __future__ import annotations

from dataclasses import dataclass

from mcp.server.fastmcp import FastMCP

from ..models.schematic import (
    CreateSheetInput,
    GlobalLabelInput,
    HierarchicalLabelInput,
    ImportSheetPinsInput,
    SheetPinInput,
)
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
        sheet_pins: list[tuple[str, str]] | None = None,
    ) -> str:
        """Create a child schematic sheet and add it to the active top-level schematic.

        Optional ``sheet_pins`` is a list of ``(name, type)`` pairs laid out by
        the same rules as ``sch_import_sheet_pins``.
        """
        payload = CreateSheetInput(
            name=name,
            filename=filename,
            x_mm=x_mm,
            y_mm=y_mm,
            snap_to_grid=snap_to_grid,
            sheet_pins=sheet_pins or [],
        )
        return service.create_sheet(
            payload.name,
            payload.filename,
            payload.x_mm,
            payload.y_mm,
            payload.snap_to_grid,
            tuple(payload.sheet_pins),
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

    @mcp.tool()
    def sch_add_sheet_pin(
        sheet: str,
        name: str,
        pin_type: str = "input",
        edge: str = "left",
        position_along_edge: float = 2.54,
    ) -> str:
        """Add one hierarchical sheet pin to a sheet symbol at an explicit position.

        ``position_along_edge`` runs clockwise from the right edge: ``right``
        measures from the top, ``bottom`` and ``top`` from the left, and ``left``
        from the bottom. Use ``sch_import_sheet_pins`` to derive every pin from
        the child sheet instead of placing them one by one.
        """
        payload = SheetPinInput.model_validate(
            {
                "sheet": sheet,
                "name": name,
                "pin_type": pin_type,
                "edge": edge,
                "position_along_edge": position_along_edge,
            }
        )
        return service.add_sheet_pin(
            payload.sheet,
            payload.name,
            payload.pin_type,
            payload.edge,
            payload.position_along_edge,
        )

    @mcp.tool()
    def sch_import_sheet_pins(
        sheet: str | None = None,
        grow_sheet: bool = True,
        dry_run: bool = False,
    ) -> str:
        """Mirror each child sheet's hierarchical labels as pins on its sheet symbol.

        This is KiCad's "Import Sheet Pins" without the GUI: without these pins
        the sheets are electrically separate, ERC reports ``hier_label_mismatch``
        for every label, and a net that crosses sheets appears twice in the
        netlist. Inputs are laid out on the left edge and every other pin type on
        the right, alphabetically; the sheet symbol grows taller if it must.

        Every pin of a touched sheet is re-laid-out, including existing ones,
        because KiCad measures left-edge pins from the bottom -- so a growing
        sheet would otherwise move them. Existing pins keep their name, type
        source and UUID; pins without a matching label are reported, never
        deleted. Sheet width growth uses an estimated text width (heuristic:
        0.6 x font height per character), not a measured one.

        Leave ``sheet`` empty to process every child sheet. Use ``dry_run`` to
        see the report without writing.
        """
        payload = ImportSheetPinsInput.model_validate(
            {"sheet": sheet, "grow_sheet": grow_sheet, "dry_run": dry_run}
        )
        return service.import_sheet_pins(payload.sheet, payload.grow_sheet, payload.dry_run)
