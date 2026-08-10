"""Pure planning for connecting a root schematic's sheet symbols.

Sheet pins alone do not join two sheets. In KiCad a sheet pin ties a child's
hierarchical label to a point on the parent's sheet symbol, and nothing more --
two sheets become one net only when something in the parent connects their
pins. Matching names are not enough, unlike global labels.

This module plans that connection as the stub-then-label idiom: a short wire
outward from each sheet pin, with a local label carrying the pin's name at its
far end. Same-named local labels on one sheet are one net, so no wire has to
route around a sheet symbol -- which matters, because crossing wires in KiCad
merge geometrically into silent shorts.

Making room for those labels means moving sheet symbols, which is a different
job from placing the labels; the two are planned separately here and exposed as
two tools. Everything is data in, data out: no file access, no ``kicad_sch_api``,
no FastMCP.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from .sheet_pins import (
    DEFAULT_TEXT_HEIGHT_MM,
    SheetBlock,
    _ceil_to_grid,
    _text_width,
)

DEFAULT_STUB_MM: Final = 2.54
DEFAULT_SPREAD_MARGIN_MM: Final = 2.54

PAGE_MARGIN_MM: Final = 10.0
"""Reserved strip at the right edge.

KiCad's drawing frame and title block occupy space whose exact width depends on
the worksheet settings, which are not in the schematic file. Ten millimetres is
a deliberately conservative stand-in, not a measurement.
"""

PAPER_WIDTHS_MM: Final[dict[str, float]] = {
    "A4": 297.0,
    "A3": 420.0,
    "A2": 594.0,
    "A1": 841.0,
    "A0": 1189.0,
    "A": 279.4,
    "B": 431.8,
    "C": 558.8,
    "D": 863.6,
    "E": 1117.6,
}
"""Landscape widths. ``(paper "A4" portrait)`` swaps width and height."""


@dataclass(frozen=True)
class SheetColumn:
    """Sheets whose x-spans overlap, moved as a unit."""

    x_min: float
    x_max: float
    sheet_names: tuple[str, ...]


@dataclass(frozen=True)
class ColumnShift:
    """How far one column moves right. Sheets never move left or vertically."""

    sheet_names: tuple[str, ...]
    dx_mm: float


@dataclass(frozen=True)
class SpreadPlan:
    """A whole-document spread: all shifts, or none."""

    shifts: tuple[ColumnShift, ...]
    blocked: tuple[str, ...]
    """Sheets that must move but have something wired to a pin."""
    right_edge_mm: float
    overflow_mm: float
    """How far past the usable page edge the plan would reach; 0 if it fits."""
    notes: tuple[str, ...]


def group_columns(sheets: Sequence[SheetBlock]) -> tuple[SheetColumn, ...]:
    """Group sheets into visual columns by overlapping x-span."""
    ordered = sorted(sheets, key=lambda sheet: sheet.origin[0])
    columns: list[list[SheetBlock]] = []
    for sheet in ordered:
        left = sheet.origin[0]
        if columns and left < max(s.origin[0] + s.size[0] for s in columns[-1]):
            columns[-1].append(sheet)
            continue
        columns.append([sheet])
    return tuple(
        SheetColumn(
            x_min=min(s.origin[0] for s in group),
            x_max=max(s.origin[0] + s.size[0] for s in group),
            sheet_names=tuple(s.name for s in group),
        )
        for group in columns
    )


def _facing_width(
    sheets: Sequence[SheetBlock],
    names: Sequence[str],
    rotation: int,
    text_height_mm: float,
) -> float:
    labels = [
        pin.name
        for sheet in sheets
        if sheet.name in names
        for pin in sheet.pins
        if pin.rotation == rotation
    ]
    return _text_width(labels, text_height_mm)


def plan_spread(
    sheets: Sequence[SheetBlock],
    *,
    attached: Mapping[str, Sequence[str]],
    grid_mm: float,
    stub_mm: float = DEFAULT_STUB_MM,
    margin_mm: float = DEFAULT_SPREAD_MARGIN_MM,
    text_height_mm: float = DEFAULT_TEXT_HEIGHT_MM,
    min_gap_mm: float | None = None,
    page_width_mm: float | None = None,
) -> SpreadPlan:
    """Plan the column shifts that make room for stub labels.

    The requirement for each gap comes from the names that actually face each
    other across it -- the longest right-edge name on the left and the longest
    left-edge name on the right -- so a long name pointing away from the gap
    does not push the columns apart for nothing.

    ``margin_mm`` exists because the text width is estimated, not measured; with
    no margin, noise in that estimate decides whether a gap "fits".
    """
    columns = group_columns(sheets)
    notes: list[str] = []
    shifts: list[ColumnShift] = []
    accumulated = 0.0
    heuristic_drove_a_shift = False

    for left_col, right_col in zip(columns, columns[1:], strict=False):
        have = right_col.x_min - left_col.x_max
        if min_gap_mm is not None:
            need = min_gap_mm
        else:
            need = (
                2 * stub_mm
                + _facing_width(sheets, left_col.sheet_names, 0, text_height_mm)
                + _facing_width(sheets, right_col.sheet_names, 180, text_height_mm)
                + margin_mm
            )
            heuristic_drove_a_shift = heuristic_drove_a_shift or have < need
        if have < need:
            accumulated += _ceil_to_grid(need - have, grid_mm)
        if accumulated > 0:
            shifts.append(ColumnShift(sheet_names=right_col.sheet_names, dx_mm=accumulated))

    moving = {name for shift in shifts for name in shift.sheet_names}
    blocked = tuple(sorted(name for name in moving if attached.get(name)))
    if blocked:
        notes.append(
            "No sheet was moved: "
            + ", ".join(blocked)
            + " already has a wire on a pin, and moving a sheet would silently "
            "disconnect it. Delete those wires, or set the spacing by hand."
        )
        return SpreadPlan(
            shifts=(),
            blocked=blocked,
            right_edge_mm=max((s.origin[0] + s.size[0] for s in sheets), default=0.0),
            overflow_mm=0.0,
            notes=tuple(notes),
        )

    right_edge = 0.0
    for column in columns:
        dx = next(
            (s.dx_mm for s in shifts if s.sheet_names == column.sheet_names),
            0.0,
        )
        right_edge = max(right_edge, column.x_max + dx)

    # Disclosed before either return below: right_edge -- and so the overflow
    # figure computed from it -- was itself derived from the estimated text
    # width whenever a shift came from the heuristic, not just min_gap_mm.
    # Both the accepted plan and the rejected (overflow) one carry the number,
    # so both must carry the disclosure.
    if heuristic_drove_a_shift:
        notes.append(
            "Column spacing was derived from an estimated text width "
            "(heuristic: 0.6 x font height per character), not a measured one."
        )

    overflow = 0.0
    if page_width_mm is None:
        notes.append(
            "Paper size is unknown, so the page-edge check was skipped rather than guessed."
        )
    else:
        usable = page_width_mm - PAGE_MARGIN_MM
        if right_edge > usable:
            overflow = round(right_edge - usable, 4)
            notes.append(
                f"Spreading would reach x={right_edge:.2f} mm, {overflow:.2f} mm past "
                f"the usable edge at {usable:.2f} mm. Nothing was moved; widen the "
                "paper or shorten the stubs."
            )
            return SpreadPlan(
                shifts=(),
                blocked=(),
                right_edge_mm=right_edge,
                overflow_mm=overflow,
                notes=tuple(notes),
            )

    return SpreadPlan(
        shifts=tuple(shifts),
        blocked=(),
        right_edge_mm=right_edge,
        overflow_mm=overflow,
        notes=tuple(notes),
    )
