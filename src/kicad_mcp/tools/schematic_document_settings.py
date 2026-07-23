"""Thin FastMCP adapters for schematic document settings."""

# pyright: reportUnusedFunction=false

from __future__ import annotations

from dataclasses import dataclass

from mcp.server.fastmcp import FastMCP

from ..schematic.document_settings import SchematicDocumentSettingsService
from .metadata import headless_compatible


@dataclass(frozen=True)
class SchematicDocumentSettingsDependencies:
    """Document-settings service injected by the schematic composition root."""

    service: SchematicDocumentSettingsService


def register(mcp: FastMCP, dependencies: SchematicDocumentSettingsDependencies) -> None:
    """Register schematic title-block and paper-size tools."""
    service = dependencies.service

    @mcp.tool()
    @headless_compatible
    def sch_set_title_block_info(
        sheet: str | None = None,
        sheet_file: str | None = None,
        title: str | None = None,
        rev: str | None = None,
        date: str | None = None,
        company: str | None = None,
        comment1: str | None = None,
        comment2: str | None = None,
        comment3: str | None = None,
        comment4: str | None = None,
        dry_run: bool = False,
    ) -> str:
        """Set schematic title block fields on the root sheet or a child sheet.

        Unspecified fields are preserved. Use ``sheet`` for a named child sheet
        or ``sheet_file`` for a specific ``.kicad_sch`` file; omit both to target
        the active root schematic.
        """
        return service.set_title_block_info(
            sheet,
            sheet_file,
            title,
            rev,
            date,
            company,
            comment1,
            comment2,
            comment3,
            comment4,
            dry_run,
        )

    @mcp.tool()
    @headless_compatible
    def sch_set_sheet_size(paper: str = "A3") -> str:
        """Change the schematic sheet (paper) size.

        Use this when the current sheet is too small to fit all symbols — for
        example after ``sch_auto_place_functional`` warns that symbols were
        placed outside the sheet boundary, or when you receive a screenshot
        showing components outside the red sheet border.

        Supported sizes (landscape): A4, A3, A2, A1, A0, A (letter), B, C, D, E,
        USLetter, USLegal.

        After resizing you should call ``sch_auto_place_functional`` again so
        that symbols are re-distributed across the larger sheet.

        Args:
            paper: Target paper size keyword (default "A3").

        Returns:
            Confirmation with old and new dimensions.
        """
        return service.set_sheet_size(paper)

    @mcp.tool()
    @headless_compatible
    def sch_auto_resize_sheet() -> str:
        """Automatically grow the sheet to fit all currently placed symbols.

        Reads the bounding box of all placed symbols and selects the smallest
        standard paper size (A4 → A3 → A2 → A1) that contains them with the
        configured margin.  If the current sheet already fits, reports that no
        change is needed.

        Returns:
            The chosen paper size and new dimensions, or a message if the
            current size is already sufficient.
        """
        return service.auto_resize_sheet()
