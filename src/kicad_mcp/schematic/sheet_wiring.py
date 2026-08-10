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
    _snap,
    _text_width,
    edge_for_rotation,
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


_STUB_GEOMETRY: Final[dict[str, tuple[float, float, int, str]]] = {
    "right": (1.0, 0.0, 0, "left"),
    "left": (-1.0, 0.0, 0, "right"),
    "top": (0.0, -1.0, 90, "left"),
    "bottom": (0.0, 1.0, 90, "right"),
}
"""Per edge: unit direction of the stub, then the label's rotation and justify.

KiCad's y grows downward, so the "top" edge stubs towards smaller y. The
justification always points away from the sheet so label text never runs back
across the symbol body.
"""


@dataclass(frozen=True)
class StubPlacement:
    """One wire stub and the local label at its far end."""

    name: str
    sheet_name: str
    x1_mm: float
    y1_mm: float
    x2_mm: float
    y2_mm: float
    label_x_mm: float
    label_y_mm: float
    label_rotation: int
    label_justify: str
    action: str
    """``add`` or ``keep``."""


@dataclass(frozen=True)
class WiringPlan:
    """Every stub and label for a document, plus what could not be made right."""

    placements: tuple[StubPlacement, ...]
    orphans: tuple[str, ...]
    """Names that appear on only one sheet symbol; their label would dangle."""
    collisions: tuple[str, ...]
    notes: tuple[str, ...]


def plan_sheet_wiring(
    sheets: Sequence[SheetBlock],
    *,
    wired_points: Sequence[tuple[float, float]],
    grid_mm: float,
    stub_mm: float = DEFAULT_STUB_MM,
    text_height_mm: float = DEFAULT_TEXT_HEIGHT_MM,
) -> WiringPlan:
    """Plan a stub and a local label for every sheet pin in the document.

    Same-named local labels on one sheet are one net, so this connects sheets
    without routing a single wire between them.
    """
    occupied = {(round(x, 3), round(y, 3)) for x, y in wired_points}
    counts: dict[str, int] = {}
    for sheet in sheets:
        for pin in sheet.pins:
            counts[pin.name] = counts.get(pin.name, 0) + 1

    placements: list[StubPlacement] = []
    notes: list[str] = []
    vertical_present = False
    for sheet in sheets:
        for pin in sheet.pins:
            edge = edge_for_rotation(pin.rotation)
            if edge is None:
                notes.append(
                    f"Pin '{pin.name}' on sheet '{sheet.name}' has rotation "
                    f"{pin.rotation}, which is not one of KiCad's four edge "
                    "rotations; it was left unwired."
                )
                continue
            dx, dy, rotation, justify = _STUB_GEOMETRY[edge]
            vertical_present = vertical_present or rotation == 90
            x1 = _snap(pin.x_mm, grid_mm)
            y1 = _snap(pin.y_mm, grid_mm)
            x2 = _snap(pin.x_mm + dx * stub_mm, grid_mm)
            y2 = _snap(pin.y_mm + dy * stub_mm, grid_mm)
            action = "keep" if (round(x1, 3), round(y1, 3)) in occupied else "add"
            placements.append(
                StubPlacement(
                    name=pin.name,
                    sheet_name=sheet.name,
                    x1_mm=x1,
                    y1_mm=y1,
                    x2_mm=x2,
                    y2_mm=y2,
                    label_x_mm=x2,
                    label_y_mm=y2,
                    label_rotation=rotation,
                    label_justify=justify,
                    action=action,
                )
            )

    orphans = tuple(sorted(name for name, count in counts.items() if count < 2))
    collisions, heuristic_compared = _find_label_collisions(placements, text_height_mm)
    if collisions:
        notes.append(
            "Some labels overlap. Run sch_spread_sheets first to make room, or shorten the stubs."
        )
    # Disclosed only when the estimate actually shaped a conclusion (two labels
    # were compared, whether or not they turned out to overlap) -- mirroring
    # `plan_spread`'s `heuristic_drove_a_shift`. A lone label on its row has
    # nothing to compare against, so the width estimate was computed but never
    # used to decide anything; disclosing it there would be noise, and noise
    # trains people to skip the note when it actually matters.
    if heuristic_compared:
        notes.append(
            "Overlap was judged from an estimated text width "
            "(heuristic: 0.6 x font height per character), not a measured one."
        )
    if vertical_present:
        notes.append(
            "Vertical labels (from top/bottom edge pins) were not checked for "
            "overlap -- see _find_label_collisions. The sheet-pin importer only "
            "ever places pins on the left and right edges, so a top/bottom pin "
            "only exists after hand-editing; check those by eye."
        )
    return WiringPlan(
        placements=tuple(placements),
        orphans=orphans,
        collisions=collisions,
        notes=tuple(notes),
    )


def _find_label_collisions(
    placements: Sequence[StubPlacement],
    text_height_mm: float,
) -> tuple[tuple[str, ...], bool]:
    """Report pairs of horizontal labels whose text would overlap.

    Only labels with ``label_rotation == 0`` (from left/right edge pins) are
    checked. Vertical labels (``label_rotation == 90``, from top/bottom edge
    pins) are skipped outright, not approximated: this module's own placement
    rule never produces a top/bottom pin (see ``_STUB_GEOMETRY``), so a
    vertical label only exists after someone hand-edits a pin's rotation, and
    correctly judging its text-flow direction under a 90-degree rotation plus
    KiCad's own justify convention is not something this function can verify
    without a live render -- guessing wrong would be worse than not checking,
    because it would report false confidence instead of no answer.
    ``plan_sheet_wiring`` discloses this gap once, in its notes, whenever any
    vertical label is present, so it is never silently unhandled.

    Returns the collision descriptions, and whether a real comparison was
    attempted at all (two same-row labels, whether or not they overlapped) --
    callers use the second value to decide whether the text-width heuristic
    actually shaped this plan's conclusion.
    """
    rows: dict[float, list[StubPlacement]] = {}
    for placement in placements:
        if placement.label_rotation != 0:
            continue
        # Rounded to the same four decimal places `_snap` itself emits (see
        # `sheet_pins._is_placed_at`'s "compared at the emitted precision"
        # rationale): two labels meant to share a row always come from the
        # same grid-snapped y, so this only absorbs float noise -- it never
        # merges rows that were meant to differ, nor splits ones that match.
        rows.setdefault(round(placement.label_y_mm, 4), []).append(placement)

    found: list[str] = []
    compared = False
    for _y, row in sorted(rows.items()):
        if len(row) < 2:
            continue
        compared = True
        spans: list[tuple[float, float, StubPlacement]] = []
        for placement in row:
            width = _text_width([placement.name], text_height_mm)
            if placement.label_justify == "left":
                spans.append((placement.label_x_mm, placement.label_x_mm + width, placement))
            else:
                spans.append((placement.label_x_mm - width, placement.label_x_mm, placement))
        spans.sort(key=lambda item: item[0])

        # Sweep by the running rightmost edge seen so far, not by comparing
        # each span only to its immediate predecessor: after the sort, a wide
        # label that swallows two shorter ones downstream would otherwise be
        # reported against just the first of them, silently missing the
        # second overlap.
        reach_hi, reach_owner = spans[0][1], spans[0][2]
        for lo, hi, placement in spans[1:]:
            if lo < reach_hi:
                found.append(
                    f"'{reach_owner.name}' on '{reach_owner.sheet_name}' and "
                    f"'{placement.name}' on '{placement.sheet_name}' overlap by "
                    f"{reach_hi - lo:.2f} mm at y={reach_owner.label_y_mm:.2f} mm"
                )
            if hi > reach_hi:
                reach_hi, reach_owner = hi, placement
    return tuple(found), compared
