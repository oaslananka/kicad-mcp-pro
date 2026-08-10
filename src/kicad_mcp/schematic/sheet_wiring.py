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

import itertools
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from .sheet_pins import (
    DEFAULT_TEXT_HEIGHT_MM,
    SheetBlock,
    SheetPinRecord,
    _ceil_to_grid,
    _format_mm,
    _is_on_grid,
    _snap,
    _text_width,
    check_edits_non_overlapping,
    edge_for_rotation,
    parse_sheet_blocks,
)

DEFAULT_STUB_MM: Final = 2.54
DEFAULT_SPREAD_MARGIN_MM: Final = 2.54

PAGE_MARGIN_MM: Final = 10.0
"""Reserved strip at the right edge.

KiCad's drawing frame and title block occupy space whose exact width depends on
the worksheet settings, which are not in the schematic file. Ten millimetres is
a deliberately conservative stand-in, not a measurement.
"""

PAPER_SIZES_MM: Final[dict[str, tuple[float, float]]] = {
    "A4": (297.0, 210.0),
    "A3": (420.0, 297.0),
    "A2": (594.0, 420.0),
    "A1": (841.0, 594.0),
    "A0": (1189.0, 841.0),
    "A": (279.4, 215.9),
    "B": (431.8, 279.4),
    "C": (558.8, 431.8),
    "D": (863.6, 558.8),
    "E": (1117.6, 863.6),
}
"""Landscape ``(width, height)`` pairs for named KiCad paper sizes."""

PAPER_WIDTHS_MM: Final[dict[str, float]] = {name: size[0] for name, size in PAPER_SIZES_MM.items()}
"""Landscape widths retained for callers that only need the default orientation."""

_PAPER_RE = re.compile(r'\(paper\s+"([^"]+)"(?:\s+(portrait))?', re.IGNORECASE)


def page_width_mm(text: str) -> float | None:
    """Return the effective page width, respecting KiCad's optional portrait flag."""
    match = _PAPER_RE.search(text)
    if match is None:
        return None
    size = PAPER_SIZES_MM.get(match.group(1).upper())
    if size is None:
        return None
    landscape_width, landscape_height = size
    return landscape_height if match.group(2) else landscape_width


def _coord_key(x: float, y: float) -> tuple[float, float]:
    """Normalize coordinates to the four-decimal precision emitted by this package."""
    return round(float(x), 4), round(float(y), 4)


def attached_pin_names(
    sheets: Sequence[SheetBlock],
    wired_points: Sequence[tuple[float, float]],
) -> dict[str, list[str]]:
    """Return sheet pin names that have a wire endpoint at the same emitted coordinate."""
    occupied = {_coord_key(x, y) for x, y in wired_points}
    attached: dict[str, list[str]] = {}
    for sheet in sheets:
        names = [pin.name for pin in sheet.pins if _coord_key(pin.x_mm, pin.y_mm) in occupied]
        if names:
            attached[sheet.name] = names
    return attached


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


def _required_gap(
    sheets: Sequence[SheetBlock],
    left_col: SheetColumn,
    right_col: SheetColumn,
    *,
    stub_mm: float,
    margin_mm: float,
    text_height_mm: float,
    min_gap_mm: float | None,
) -> tuple[float, bool]:
    """Return the required gap and whether it came from the text-width estimate."""
    if min_gap_mm is not None:
        return min_gap_mm, False
    required = (
        2 * stub_mm
        + _facing_width(sheets, left_col.sheet_names, 0, text_height_mm)
        + _facing_width(sheets, right_col.sheet_names, 180, text_height_mm)
        + margin_mm
    )
    return required, True


def _column_shifts(
    sheets: Sequence[SheetBlock],
    columns: Sequence[SheetColumn],
    *,
    grid_mm: float,
    stub_mm: float,
    margin_mm: float,
    text_height_mm: float,
    min_gap_mm: float | None,
) -> tuple[tuple[ColumnShift, ...], bool]:
    """Return cumulative rightward shifts and whether an estimate drove a shift."""
    shifts: list[ColumnShift] = []
    accumulated = 0.0
    heuristic_drove_a_shift = False
    for left_col, right_col in zip(columns, columns[1:], strict=False):
        have = right_col.x_min - left_col.x_max
        need, estimated = _required_gap(
            sheets,
            left_col,
            right_col,
            stub_mm=stub_mm,
            margin_mm=margin_mm,
            text_height_mm=text_height_mm,
            min_gap_mm=min_gap_mm,
        )
        if have < need:
            accumulated += _ceil_to_grid(need - have, grid_mm)
            heuristic_drove_a_shift = heuristic_drove_a_shift or estimated
        if accumulated > 0:
            shifts.append(ColumnShift(sheet_names=right_col.sheet_names, dx_mm=accumulated))
    return tuple(shifts), heuristic_drove_a_shift


def _spread_right_edge(columns: Sequence[SheetColumn], shifts: Sequence[ColumnShift]) -> float:
    shift_by_column = {shift.sheet_names: shift.dx_mm for shift in shifts}
    return max(
        (column.x_max + shift_by_column.get(column.sheet_names, 0.0) for column in columns),
        default=0.0,
    )


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
    """Plan whole-column shifts that make room for stub labels without moving wired sheets."""
    columns = group_columns(sheets)
    shifts, heuristic_drove_a_shift = _column_shifts(
        sheets,
        columns,
        grid_mm=grid_mm,
        stub_mm=stub_mm,
        margin_mm=margin_mm,
        text_height_mm=text_height_mm,
        min_gap_mm=min_gap_mm,
    )
    moving = {name for shift in shifts for name in shift.sheet_names}
    blocked = tuple(sorted(name for name in moving if attached.get(name)))
    if blocked:
        note = (
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
            notes=(note,),
        )

    right_edge = _spread_right_edge(columns, shifts)
    notes: list[str] = []
    if heuristic_drove_a_shift:
        notes.append(
            "Column spacing was derived from an estimated text width "
            "(heuristic: 1.1 x font height per character), not a measured one."
        )

    if page_width_mm is None:
        notes.append(
            "Paper size is unknown, so the page-edge check was skipped rather than guessed."
        )
        return SpreadPlan(tuple(shifts), (), right_edge, 0.0, tuple(notes))

    usable = page_width_mm - PAGE_MARGIN_MM
    overflow = max(round(right_edge - usable, 4), 0.0)
    if overflow:
        notes.append(
            f"Spreading would reach x={right_edge:.2f} mm, {overflow:.2f} mm past "
            f"the usable edge at {usable:.2f} mm. Nothing was moved; widen the "
            "paper or shorten the stubs."
        )
        return SpreadPlan((), (), right_edge, overflow, tuple(notes))
    return SpreadPlan(tuple(shifts), (), right_edge, 0.0, tuple(notes))


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


def _sheet_pin_pairs(sheets: Sequence[SheetBlock]) -> list[tuple[str, SheetPinRecord]]:
    return [(sheet.name, pin) for sheet in sheets for pin in sheet.pins]


def _plan_stub_placement(
    sheet_name: str,
    pin: SheetPinRecord,
    *,
    occupied: set[tuple[float, float]],
    grid_mm: float,
    stub_mm: float,
) -> tuple[StubPlacement | None, tuple[str, ...], bool]:
    edge = edge_for_rotation(pin.rotation)
    if edge is None:
        note = (
            f"Pin '{pin.name}' on sheet '{sheet_name}' has rotation {pin.rotation}, "
            "which is not one of KiCad's four edge rotations; it was left unwired."
        )
        return None, (note,), False

    dx, dy, rotation, justify = _STUB_GEOMETRY[edge]
    notes: list[str] = []
    if not (_is_on_grid(pin.x_mm, grid_mm) and _is_on_grid(pin.y_mm, grid_mm)):
        notes.append(
            f"Pin '{pin.name}' on sheet '{sheet_name}' is at ({pin.x_mm}, {pin.y_mm}), "
            f"which is not on the {grid_mm} mm grid. Run sch_align_to_grid before wiring."
        )

    x1, y1 = pin.x_mm, pin.y_mm
    x2 = _snap(pin.x_mm + dx * stub_mm, grid_mm) if dx else pin.x_mm
    y2 = _snap(pin.y_mm + dy * stub_mm, grid_mm) if dy else pin.y_mm
    placement = StubPlacement(
        name=pin.name,
        sheet_name=sheet_name,
        x1_mm=x1,
        y1_mm=y1,
        x2_mm=x2,
        y2_mm=y2,
        label_x_mm=x2,
        label_y_mm=y2,
        label_rotation=rotation,
        label_justify=justify,
        action="keep" if _coord_key(x1, y1) in occupied else "add",
    )
    return placement, tuple(notes), rotation == 90


def plan_sheet_wiring(
    sheets: Sequence[SheetBlock],
    *,
    wired_points: Sequence[tuple[float, float]],
    grid_mm: float,
    stub_mm: float = DEFAULT_STUB_MM,
    text_height_mm: float = DEFAULT_TEXT_HEIGHT_MM,
) -> WiringPlan:
    """Plan a stub and local label for every addressable sheet pin in the document."""
    occupied = {_coord_key(x, y) for x, y in wired_points}
    pairs = _sheet_pin_pairs(sheets)
    counts = Counter(pin.name for _sheet_name, pin in pairs)
    placements: list[StubPlacement] = []
    notes: list[str] = []
    vertical_present = False

    for sheet_name, pin in pairs:
        placement, pin_notes, is_vertical = _plan_stub_placement(
            sheet_name,
            pin,
            occupied=occupied,
            grid_mm=grid_mm,
            stub_mm=stub_mm,
        )
        notes.extend(pin_notes)
        vertical_present = vertical_present or is_vertical
        if placement is not None:
            placements.append(placement)

    orphans = tuple(sorted(name for name, count in counts.items() if count < 2))
    collisions, heuristic_compared = _find_label_collisions(placements, text_height_mm)
    if collisions:
        notes.append(
            "Some labels overlap. Run sch_spread_sheets first to make room, or shorten the stubs."
        )
    if heuristic_compared:
        notes.append(
            "Overlap was judged from an estimated text width "
            "(heuristic: 1.1 x font height per character), not a measured one."
        )
    if vertical_present:
        notes.append(
            "Vertical labels (from top/bottom edge pins) were not checked for "
            "overlap -- see _find_label_collisions. The sheet-pin importer only "
            "ever places pins on the left and right edges, so a top/bottom pin "
            "only exists after hand-editing; check those by eye."
        )
    return WiringPlan(tuple(placements), orphans, collisions, tuple(notes))


type _LabelSpan = tuple[float, float, StubPlacement]


def _horizontal_label_rows(
    placements: Sequence[StubPlacement],
) -> dict[float, list[StubPlacement]]:
    rows: dict[float, list[StubPlacement]] = {}
    for placement in placements:
        if placement.label_rotation == 0:
            rows.setdefault(round(placement.label_y_mm, 4), []).append(placement)
    return rows


def _label_span(placement: StubPlacement, text_height_mm: float) -> _LabelSpan:
    width = _text_width([placement.name], text_height_mm)
    if placement.label_justify == "left":
        return placement.label_x_mm, placement.label_x_mm + width, placement
    return placement.label_x_mm - width, placement.label_x_mm, placement


def _collision_description(first: _LabelSpan, second: _LabelSpan) -> str | None:
    a_lo, a_hi, a = first
    b_lo, b_hi, b = second
    lo, hi = max(a_lo, b_lo), min(a_hi, b_hi)
    if lo >= hi:
        return None
    return (
        f"'{a.name}' on '{a.sheet_name}' and '{b.name}' on '{b.sheet_name}' "
        f"overlap by {hi - lo:.2f} mm at y={a.label_y_mm:.2f} mm"
    )


def _find_label_collisions(
    placements: Sequence[StubPlacement],
    text_height_mm: float,
) -> tuple[tuple[str, ...], bool]:
    """Report every overlapping pair of horizontal labels and whether any pair was compared."""
    found: list[str] = []
    compared = False
    for _y, row in sorted(_horizontal_label_rows(placements).items()):
        if len(row) < 2:
            continue
        compared = True
        spans = sorted(
            (_label_span(placement, text_height_mm) for placement in row), key=lambda x: x[0]
        )
        for first, second in itertools.combinations(spans, 2):
            description = _collision_description(first, second)
            if description is not None:
                found.append(description)
    return tuple(found), compared


def _pin_shift_edits(
    block: SheetBlock,
    dx_mm: float,
) -> tuple[list[tuple[int, int, str]], list[tuple[str, str]]]:
    edits: list[tuple[int, int, str]] = []
    skipped: list[tuple[str, str]] = []
    for pin, (pin_start, pin_end) in zip(block.pins, block.pin_at_spans, strict=True):
        if pin_start == pin_end:
            skipped.append((block.name, pin.name))
            continue
        new_pin_x = round(pin.x_mm + dx_mm, 4)
        edits.append(
            (
                pin_start,
                pin_end,
                f"(at {_format_mm(new_pin_x)} {_format_mm(pin.y_mm)} {pin.rotation})",
            )
        )
    return edits, skipped


def _sheet_shift_edits(
    block: SheetBlock,
    dx_mm: float,
) -> tuple[list[tuple[int, int, str]], list[tuple[str, str]]]:
    new_x = round(block.origin[0] + dx_mm, 4)
    edits = [
        (
            block.at_span[0],
            block.at_span[1],
            f"(at {_format_mm(new_x)} {_format_mm(block.origin[1])})",
        )
    ]
    pin_edits, skipped = _pin_shift_edits(block, dx_mm)
    edits.extend(pin_edits)
    return edits, skipped


def apply_spread_shifts(
    text: str,
    dx_by_sheet: Mapping[str, float],
    *,
    subject: str,
) -> tuple[str, tuple[tuple[str, str], ...]]:
    """Apply only sheet/pin ``(at ...)`` rewrites for a validated spread plan."""
    blocks = {block.name: block for block in parse_sheet_blocks(text)}
    edits: list[tuple[int, int, str]] = []
    skipped: list[tuple[str, str]] = []
    for name, dx_mm in dx_by_sheet.items():
        block = blocks.get(name)
        if block is None:
            raise ValueError(f"Sheet '{name}' disappeared before the spread write.")
        block_edits, block_skipped = _sheet_shift_edits(block, dx_mm)
        edits.extend(block_edits)
        skipped.extend(block_skipped)

    check_edits_non_overlapping(edits, subject)
    updated = text
    for start, end, replacement in sorted(edits, key=lambda edit: edit[0], reverse=True):
        updated = updated[:start] + replacement + updated[end:]
    return updated, tuple(skipped)
