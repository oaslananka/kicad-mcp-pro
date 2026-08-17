"""Thin FastMCP adapters for schematic hierarchy authoring."""

# pyright: reportUnusedFunction=false

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from ..models.schematic import (
    CreateSheetInput,
    DeleteSheetInput,
    GlobalLabelInput,
    HierarchicalLabelInput,
    ImportSheetPinsInput,
    MoveSheetInput,
    SheetPinInput,
    SpreadSheetsInput,
    WireSheetPinsInput,
)
from ..schematic.hierarchy_authoring import SchematicHierarchyAuthoringService

_SheetPinPair = Annotated[list[str], Field(min_length=2, max_length=2)]
"""One ``[name, pin_type]`` pair as a fixed-length array, not a tuple.

A ``tuple[str, str]`` annotation makes FastMCP emit an inner array schema with
``prefixItems`` and no ``items``, which stricter MCP hosts reject; the adapter
normalizes back to tuples before the service sees them.
"""


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
        sheet_pins: list[_SheetPinPair] | None = None,
    ) -> str:
        """Create a child schematic sheet and add it to the active top-level schematic.

        Optional ``sheet_pins`` is a list of ``[name, type]`` two-element arrays,
        laid out by the same rules as ``sch_import_sheet_pins``.
        """
        normalized_pins = [] if sheet_pins is None else [(pair[0], pair[1]) for pair in sheet_pins]
        payload = CreateSheetInput(
            name=name,
            filename=filename,
            x_mm=x_mm,
            y_mm=y_mm,
            snap_to_grid=snap_to_grid,
            sheet_pins=normalized_pins,
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
    def sch_move_sheet(
        name: str,
        x_mm: float,
        y_mm: float,
        snap_to_grid: bool = True,
    ) -> str:
        """Move the hierarchical sheet named ``name`` (its ``Sheetname``) to a new anchor.

        Only the sheet's ``(at ...)`` anchor and its pins move; each pin keeps its
        offset and rotation. Size, styling, UUIDs and the child file are untouched.
        """
        payload = MoveSheetInput(name=name, x_mm=x_mm, y_mm=y_mm, snap_to_grid=snap_to_grid)
        return service.move_sheet(payload.name, payload.x_mm, payload.y_mm, payload.snap_to_grid)

    @mcp.tool()
    def sch_delete_sheet(name: str) -> str:
        """Remove the hierarchical sheet named ``name`` (its ``Sheetname``) from the parent.

        Deletes the whole ``(sheet ...)`` block including its instance/path
        bookkeeping -- the inverse of ``sch_create_sheet``. The child file is left
        in place. Reports if the name is not found.
        """
        return service.delete_sheet(DeleteSheetInput(name=name).name)

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

        Limitations, all deliberate:

        - The position is used exactly as given. It is **not** snapped to the
          schematic grid, so a pin placed off-grid will have no wire snap to it.
          ``sch_import_sheet_pins`` does snap.
        - A position past the end of an edge is accepted, which puts the pin
          off the sheet symbol -- ``position_along_edge=1000.0`` on a 20 mm
          sheet yields y around -949. Nothing warns.
        - ``top`` and ``bottom`` pins survive here, but ``sch_import_sheet_pins``
          only ever places pins on ``left`` and ``right``. A later import
          relocates a hand-placed top or bottom pin to one of those two edges.
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
        sheet would otherwise move them. An existing pin keeps its name and its
        UUID, and is moved to wherever this layout puts it; its type is changed
        if the child sheet's label shape now says something else. Pins without a
        matching label are reported, never deleted. Only the ``left`` and
        ``right`` edges are used, so a pin hand-placed on ``top`` or ``bottom``
        with ``sch_add_sheet_pin`` is relocated. The report counts added,
        retyped, moved and unchanged pins separately.

        ``grow_sheet`` (default on) lets the sheet symbol grow to fit its pins:
        taller for the fuller edge, and wider if the estimated label text of the
        two columns would collide. The sheet never shrinks and never moves.
        Width growth uses an estimated text width (heuristic: 1.1 x font height
        per character), not a measured one, and says so in the report. Turning
        ``grow_sheet`` off keeps the size fixed, and any sheet whose pins then do
        not fit is skipped **entirely** -- reported, with nothing written for it
        -- rather than partially written. A half-pinned sheet is worse than an
        unchanged one.

        Leave ``sheet`` empty to process every child sheet. Use ``dry_run`` to
        see the report without writing.
        """
        payload = ImportSheetPinsInput.model_validate(
            {"sheet": sheet, "grow_sheet": grow_sheet, "dry_run": dry_run}
        )
        return service.import_sheet_pins(payload.sheet, payload.grow_sheet, payload.dry_run)

    @mcp.tool()
    def sch_spread_sheets(
        min_gap_mm: float | None = None,
        margin_mm: float = 2.54,
        dry_run: bool = False,
    ) -> str:
        """Move sheet-symbol columns apart to make room for stub-and-label wiring.

        Sheets are grouped into columns by overlapping x-span, and only whole
        columns move -- and only to the right, never left and never vertically.
        Run this **before** ``sch_wire_sheet_pins``, not after: it refuses to
        move a sheet already wired on a pin, since that would silently
        disconnect the wire (KiCad joins on exact coordinate equality), and
        ``sch_wire_sheet_pins`` wires every pin it touches by default. If any
        sheet that must move has a wired pin, the **whole** spread is refused,
        not just that sheet's own column, since a partial spread would leave
        the untouched columns' stub-and-label layout unplanned for.

        With ``min_gap_mm`` unset, the gap required between two neighboring
        columns is derived from the pin names that actually face each other
        across it (the longest right-edge name on the left, the longest
        left-edge name on the right), plus ``margin_mm``. That per-character
        width is an *estimate* (1.1 x font height per character), not a
        measured one, so the margin absorbs noise in the estimate; the report
        says so whenever the estimate drove a move. Set ``min_gap_mm`` to use a
        fixed gap instead and skip the estimate entirely.

        An unrecognized paper size skips the page-edge overflow check --
        disclosed as skipped, never guessed. A pin whose ``(at ...)`` node
        can't be read is left in place and reported, never rewritten blind.

        Use ``dry_run`` to see the report without writing.
        """
        payload = SpreadSheetsInput.model_validate(
            {"min_gap_mm": min_gap_mm, "margin_mm": margin_mm, "dry_run": dry_run}
        )
        return service.spread_sheets(payload.min_gap_mm, payload.margin_mm, payload.dry_run)

    @mcp.tool()
    def sch_wire_sheet_pins(
        sheet: str | None = None,
        stub_mm: float = 2.54,
        dry_run: bool = False,
    ) -> str:
        """Connect sheet pins by giving each one a wire stub and a local label.

        A sheet pin alone joins nothing -- two sheets become one net only once
        something in the parent schematic connects their pins, and matching
        names are not enough (unlike global labels). This writes a short wire
        stub out of every sheet pin, then a **local** label carrying the pin's
        name at the far end. Same-named local labels on one sheet are one net;
        that is what actually joins the sheets, not the pins themselves, and no
        wire ever has to route between sheet symbols (crossing wires in KiCad
        merge geometrically into silent shorts).

        Run ``sch_spread_sheets`` first, not after: once a pin is wired here,
        ``sch_spread_sheets`` refuses to move any sheet with a wire on one of
        its pins, and since this tool wires every pin it touches by default,
        running it first leaves ``sch_spread_sheets`` nothing it can move.

        A pin that already has a wire on it is left alone. A pin name that
        appears on only one sheet symbol is reported rather than silently
        skipped, because its label would dangle with no matching net to join.
        Label overlap is judged from an *estimated* text width (1.1 x font
        height per character), not a measured one, and the report says so
        whenever that estimate was actually used to decide something. Labels
        from top- and bottom-edge pins are not checked for overlap at all --
        judging a vertical label's text-flow direction correctly would need a
        live render this tool doesn't have, and a wrong guess would be worse
        than no check; the report calls this out whenever such a pin exists.

        ``sheet``, if given, limits which sheet's pins get a *new* stub and
        label; every sheet's pins still count toward orphan and overlap
        detection, since a name only "matches" once its counterpart elsewhere
        in the document is known. Use ``dry_run`` to see the report without
        writing.
        """
        payload = WireSheetPinsInput.model_validate(
            {"sheet": sheet, "stub_mm": stub_mm, "dry_run": dry_run}
        )
        return service.wire_sheet_pins(payload.sheet, payload.stub_mm, payload.dry_run)
