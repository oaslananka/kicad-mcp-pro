"""Pure planning and S-expression emission for hierarchical sheet pins.

KiCad joins a child sheet's ``hierarchical_label`` nodes to the parent sheet
symbol through ``(pin ...)`` nodes inside the parent's ``(sheet ...)`` block.
Without them the sheets are electrically separate: ERC reports
``hier_label_mismatch`` for every label, and a net that crosses sheets appears
twice in the netlist instead of once.

Everything in this module is text in, text or data out -- no file access, no
``kicad_sch_api``, no FastMCP. That is deliberate. A ``kicad_sch_api`` load/save
round trip of a real root schematic is node-count clean but silently drops
``(comment N ...)`` nodes from the ``title_block``, so sheet pins are spliced
into the document text instead of reserializing it. It also makes the geometry
exhaustively unit-testable without KiCad installed.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Final

PIN_TYPES: Final[tuple[str, ...]] = (
    "input",
    "output",
    "bidirectional",
    "tri_state",
    "passive",
)
EDGES: Final[tuple[str, ...]] = ("left", "right", "top", "bottom")

DEFAULT_PITCH_MM: Final = 2.54
DEFAULT_MARGIN_MM: Final = 2.54
DEFAULT_TEXT_HEIGHT_MM: Final = 1.27

_TAG_RE = re.compile(r"\(\s*([A-Za-z_][A-Za-z0-9_]*)")
_SHEET_RE = re.compile(r"\(sheet(?![A-Za-z0-9_])")
_TWO_FLOATS_RE = re.compile(r"\(\w+\s+(-?[\d.]+)\s+(-?[\d.]+)\s*\)")
_PROPERTY_RE = re.compile(r'\(property\s+"((?:[^"\\]|\\.)*)"\s+"((?:[^"\\]|\\.)*)"')
_PIN_HEAD_RE = re.compile(r'\(pin\s+"((?:[^"\\]|\\.)*)"\s+([A-Za-z_]+)')
_UUID_RE = re.compile(r'\(uuid\s+"([^"]*)"\s*\)')
_HIER_LABEL_RE = re.compile(
    r'\(hierarchical_label\s+"((?:[^"\\]|\\.)*)"\s*(?:\(shape\s+([A-Za-z_]+)\s*\))?'
)


@dataclass(frozen=True)
class SheetBlock:
    """One ``(sheet ...)`` block of a root schematic, with text spans."""

    name: str
    filename: str
    origin: tuple[float, float]
    size: tuple[float, float]
    pins: tuple[tuple[str, str, str], ...]
    """Existing pins as ``(name, pin_type, uuid)`` in file order."""
    start: int
    end: int
    size_span: tuple[int, int]
    """Character span of the sheet's own ``(size w h)`` node."""
    pin_spans: tuple[tuple[int, int], ...]
    """Whole-line spans of the existing ``(pin ...)`` blocks, parallel to ``pins``."""
    instances_start: int | None
    """Start of the ``(instances ...)`` node -- the anchor new pins go before."""


def _unescape(raw: str) -> str:
    return raw.replace('\\"', '"').replace("\\\\", "\\")


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _block_end(text: str, start: int) -> int:
    """Return the index just past the parenthesis closing the block at ``start``.

    String-aware: parentheses inside a quoted KiCad string do not count, and a
    backslash escape inside a string is skipped whole.
    """
    depth = 0
    in_string = False
    index = start
    while index < len(text):
        char = text[index]
        if in_string:
            if char == "\\":
                index += 2
                continue
            if char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return index + 1
        index += 1
    raise ValueError("Unbalanced S-expression: no closing parenthesis found.")


def _children(text: str, start: int, end: int) -> Iterator[tuple[str, int, int]]:
    """Yield ``(tag, start, end)`` for the *direct* children of a block.

    Walking direct children is what keeps ``(size 1.27 1.27)`` inside a nested
    ``(effects (font ...))`` from being mistaken for the sheet's own size.
    """
    index = start + 1
    while index < end - 1:
        if text[index] == "(":
            child_end = _block_end(text, index)
            tag_match = _TAG_RE.match(text, index)
            yield (tag_match.group(1) if tag_match else "", index, child_end)
            index = child_end
        else:
            index += 1


def _line_span(text: str, start: int, end: int) -> tuple[int, int]:
    """Widen a span to whole lines, so deleting it leaves no stray indentation."""
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", end)
    return (line_start, len(text) if line_end == -1 else line_end + 1)


def _two_floats(text: str, start: int, end: int) -> tuple[float, float] | None:
    match = _TWO_FLOATS_RE.fullmatch(text[start:end].strip())
    if match is None:
        return None
    return (float(match.group(1)), float(match.group(2)))


def parse_hierarchical_labels(text: str) -> tuple[tuple[str, str], ...]:
    """Return ``(name, shape)`` for every hierarchical label, in file order.

    A label without an explicit ``(shape ...)`` defaults to ``input``, matching
    KiCad. ``label`` and ``global_label`` nodes are ignored: only hierarchical
    labels take part in the parent/child contract.
    """
    labels: list[tuple[str, str]] = []
    for match in _HIER_LABEL_RE.finditer(text):
        shape = match.group(2) or "input"
        labels.append((_unescape(match.group(1)), shape))
    return tuple(labels)


def parse_sheet_blocks(text: str) -> tuple[SheetBlock, ...]:
    """Return every ``(sheet ...)`` block of a schematic with its text spans.

    Blocks that lack a name, a position, or a size are skipped: they cannot be
    addressed or spliced safely.
    """
    blocks: list[SheetBlock] = []
    for match in _SHEET_RE.finditer(text):
        start = match.start()
        try:
            end = _block_end(text, start)
        except ValueError:
            continue

        name = ""
        filename = ""
        origin: tuple[float, float] | None = None
        size: tuple[float, float] | None = None
        size_span: tuple[int, int] | None = None
        pins: list[tuple[str, str, str]] = []
        pin_spans: list[tuple[int, int]] = []
        instances_start: int | None = None

        for tag, child_start, child_end in _children(text, start, end):
            if tag == "at" and origin is None:
                origin = _two_floats(text, child_start, child_end)
            elif tag == "size" and size is None:
                size = _two_floats(text, child_start, child_end)
                if size is not None:
                    size_span = (child_start, child_end)
            elif tag == "property":
                property_match = _PROPERTY_RE.match(text, child_start)
                if property_match is None:
                    continue
                key = _unescape(property_match.group(1))
                value = _unescape(property_match.group(2))
                if key == "Sheetname":
                    name = value
                elif key == "Sheetfile":
                    filename = value
            elif tag == "pin":
                head = _PIN_HEAD_RE.match(text, child_start)
                if head is None:
                    continue
                uuid_match = _UUID_RE.search(text, child_start, child_end)
                pins.append(
                    (
                        _unescape(head.group(1)),
                        head.group(2),
                        uuid_match.group(1) if uuid_match else "",
                    )
                )
                pin_spans.append(_line_span(text, child_start, child_end))
            elif tag == "instances" and instances_start is None:
                instances_start = child_start

        if not name or origin is None or size is None or size_span is None:
            continue

        blocks.append(
            SheetBlock(
                name=name,
                filename=filename,
                origin=origin,
                size=size,
                pins=tuple(pins),
                start=start,
                end=end,
                size_span=size_span,
                pin_spans=tuple(pin_spans),
                instances_start=instances_start,
            )
        )
    return tuple(blocks)


_TEXT_WIDTH_RATIO: Final = 0.6
"""Heuristic: average glyph advance as a fraction of the font height.

KiCad's stroke font has no fixed advance, so this only estimates how wide a pin
label renders. It is used solely to decide whether a sheet needs to get wider,
never to place anything.
"""

_EDGE_GEOMETRY: Final[dict[str, tuple[int, str]]] = {
    "right": (0, "right"),
    "bottom": (270, "left"),
    "left": (180, "left"),
    "top": (90, "right"),
}
"""Rotation and justification per edge, clockwise from right.

Taken from ``kicad_sch_api``'s own edge table so hand-placed pins and imported
pins render identically.

This is the only geometry ``placement_on_edge`` and ``plan_sheet_pins`` share.
The two deliberately part ways on where ``position_along_edge`` starts on the
left edge: ``placement_on_edge`` keeps kicad-sch-api's convention (measured
from the bottom), while ``plan_sheet_pins`` measures top-down so its left and
right columns read in the same direction. See each function's docstring for
why.
"""


@dataclass(frozen=True)
class SheetPinPlacement:
    """One sheet pin, resolved to absolute schematic coordinates."""

    name: str
    pin_type: str
    edge: str
    x_mm: float
    y_mm: float
    rotation: int
    justify: str
    uuid: str
    """Existing pin's UUID, or ``""`` for a new pin the caller must stamp."""
    action: str
    """``add``, ``retype`` or ``keep``."""


@dataclass(frozen=True)
class SheetPinPlan:
    """The full, deterministic pin layout of one sheet symbol."""

    placements: tuple[SheetPinPlacement, ...]
    size: tuple[float, float]
    orphans: tuple[str, ...]
    conflicts: tuple[str, ...]
    overflow: tuple[str, ...]
    notes: tuple[str, ...]


def _snap(value: float, grid_mm: float) -> float:
    if grid_mm <= 0:
        return round(value, 4)
    return round(round(value / grid_mm) * grid_mm, 4)


def _ceil_to_grid(value: float, grid_mm: float) -> float:
    if grid_mm <= 0:
        return round(value, 4)
    steps = value / grid_mm
    rounded = round(steps)
    if abs(steps - rounded) < 1e-9:
        steps = rounded
    else:
        steps = int(steps) + 1
    return round(steps * grid_mm, 4)


def _is_on_grid(value: float, grid_mm: float) -> bool:
    if grid_mm <= 0:
        return True
    steps = value / grid_mm
    return abs(steps - round(steps)) < 1e-9


def _sort_key(name: str) -> tuple[str, str]:
    return (name.casefold(), name)


def _edge_extent(count: int, pitch_mm: float, margin_mm: float) -> float:
    if count == 0:
        return 0.0
    return 2 * margin_mm + (count - 1) * pitch_mm


def _edge_capacity(height_mm: float, pitch_mm: float, margin_mm: float) -> int:
    usable = height_mm - 2 * margin_mm
    if usable < 0:
        return 0
    if pitch_mm <= 0:
        return 1
    return int(usable / pitch_mm + 1e-9) + 1


def _text_width(names: Sequence[str], text_height_mm: float) -> float:
    longest = max((len(name) for name in names), default=0)
    return longest * _TEXT_WIDTH_RATIO * text_height_mm


def placement_on_edge(
    sheet: SheetBlock,
    name: str,
    pin_type: str,
    edge: str,
    position_along_edge: float,
    uuid: str,
) -> SheetPinPlacement:
    """Resolve one pin on any of the four edges to absolute coordinates.

    This is the manual-placement entry point: callers who already know where
    they want a pin, in kicad-sch-api's own coordinate convention, get exact
    parity with hand-placed pins. ``position_along_edge`` follows that
    convention, clockwise from the right edge: ``right`` measures from the
    top, ``bottom`` and ``top`` from the left, and ``left`` from the bottom.

    ``plan_sheet_pins`` deliberately does not use this convention for its
    left edge -- see its docstring and the note on ``_EDGE_GEOMETRY`` for why.
    """
    if pin_type not in PIN_TYPES:
        raise ValueError(f"Unknown sheet pin type '{pin_type}'. Use one of {', '.join(PIN_TYPES)}.")
    if edge not in _EDGE_GEOMETRY:
        raise ValueError(f"Unknown sheet edge '{edge}'. Use one of {', '.join(EDGES)}.")

    origin_x, origin_y = sheet.origin
    width, height = sheet.size
    rotation, justify = _EDGE_GEOMETRY[edge]
    if edge == "right":
        x_mm, y_mm = origin_x + width, origin_y + position_along_edge
    elif edge == "bottom":
        x_mm, y_mm = origin_x + position_along_edge, origin_y + height
    elif edge == "left":
        x_mm, y_mm = origin_x, origin_y + height - position_along_edge
    else:
        x_mm, y_mm = origin_x + position_along_edge, origin_y

    return SheetPinPlacement(
        name=name,
        pin_type=pin_type,
        edge=edge,
        x_mm=round(x_mm, 4),
        y_mm=round(y_mm, 4),
        rotation=rotation,
        justify=justify,
        uuid=uuid,
        action="add",
    )


def plan_sheet_pins(
    labels: Sequence[tuple[str, str]],
    sheet: SheetBlock,
    *,
    grid_mm: float,
    pitch_mm: float = DEFAULT_PITCH_MM,
    margin_mm: float = DEFAULT_MARGIN_MM,
    text_height_mm: float = DEFAULT_TEXT_HEIGHT_MM,
    grow_sheet: bool = True,
) -> SheetPinPlan:
    """Lay out every pin of one sheet symbol from its child's labels.

    Inputs go on the left edge and everything else on the right, alphabetically
    within each edge. The layout covers *all* pins, not only the new ones: KiCad
    measures a left-edge pin from the bottom of the sheet, so growing the sheet
    would silently move any left pin whose offset was left untouched.

    Left-edge pins are placed top-down (``origin_y + margin + index * pitch``),
    not in kicad-sch-api's bottom-relative convention that ``placement_on_edge``
    follows. Both columns must run in the same direction -- otherwise the left
    column would read bottom-to-top while the right reads top-to-bottom -- so
    this function does not call ``placement_on_edge`` for its left edge. See
    the note on ``_EDGE_GEOMETRY`` for the full picture.
    """
    desired: dict[str, str] = {}
    conflicts: list[str] = []
    for raw_name, raw_shape in labels:
        shape = raw_shape if raw_shape in PIN_TYPES else "input"
        if raw_name in desired:
            if desired[raw_name] != shape and raw_name not in conflicts:
                conflicts.append(raw_name)
            continue
        desired[raw_name] = shape

    existing = {name: (pin_type, uuid) for name, pin_type, uuid in sheet.pins}
    orphans = tuple(sorted((name for name in existing if name not in desired), key=_sort_key))

    entries: list[tuple[str, str, str, str]] = []
    for name in sorted(set(desired) | set(existing), key=_sort_key):
        if name in desired:
            pin_type = desired[name]
            action = (
                "add"
                if name not in existing
                else ("keep" if existing[name][0] == pin_type else "retype")
            )
        else:
            pin_type = existing[name][0]
            action = "keep"
        entries.append((name, pin_type, existing.get(name, ("", ""))[1], action))

    left = [entry for entry in entries if entry[1] == "input"]
    right = [entry for entry in entries if entry[1] != "input"]

    origin_x, origin_y = sheet.origin
    width, height = sheet.size
    notes: list[str] = []
    overflow: list[str] = []

    if grow_sheet:
        needed_height = max(
            _edge_extent(len(left), pitch_mm, margin_mm),
            _edge_extent(len(right), pitch_mm, margin_mm),
        )
        height = max(height, _ceil_to_grid(needed_height, grid_mm))
        needed_width = (
            _text_width([entry[0] for entry in left], text_height_mm)
            + _text_width([entry[0] for entry in right], text_height_mm)
            + margin_mm
        )
        width = max(width, _ceil_to_grid(needed_width, grid_mm))
        if width > sheet.size[0]:
            notes.append(
                "Sheet width was grown from an estimated text width "
                "(heuristic: 0.6 x font height per character), not a measured one."
            )
    else:
        capacity = _edge_capacity(height, pitch_mm, margin_mm)
        overflow = sorted(
            [entry[0] for entry in left[capacity:]] + [entry[0] for entry in right[capacity:]],
            key=_sort_key,
        )
        left, right = left[:capacity], right[:capacity]

    if not _is_on_grid(origin_x, grid_mm):
        notes.append(
            f"Sheet origin x={origin_x} is not on the {grid_mm} mm grid, so its edge pins "
            "cannot be either. Run sch_align_to_grid before wiring."
        )
    if pitch_mm > 0 and grid_mm > 0 and not _is_on_grid(pitch_mm / grid_mm, 1.0):
        notes.append(
            f"Pin pitch {pitch_mm} mm is not a multiple of the {grid_mm} mm grid; "
            "positions were snapped individually."
        )

    placements: list[SheetPinPlacement] = []
    for edge, column in (("left", left), ("right", right)):
        x_mm = origin_x if edge == "left" else round(origin_x + width, 4)
        rotation, justify = _EDGE_GEOMETRY[edge]
        for index, (name, pin_type, uuid, action) in enumerate(column):
            placements.append(
                SheetPinPlacement(
                    name=name,
                    pin_type=pin_type,
                    edge=edge,
                    x_mm=x_mm,
                    y_mm=_snap(origin_y + margin_mm + index * pitch_mm, grid_mm),
                    rotation=rotation,
                    justify=justify,
                    uuid=uuid,
                    action=action,
                )
            )

    return SheetPinPlan(
        placements=tuple(placements),
        size=(round(width, 4), round(height, 4)),
        orphans=orphans,
        conflicts=tuple(conflicts),
        overflow=tuple(overflow),
        notes=tuple(notes),
    )


def _format_mm(value: float) -> str:
    """Format a millimetre value the way KiCad writes it: no trailing zeros."""
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    if text in ("", "-", "-0"):
        return "0"
    return text


def sheet_pin_block(placement: SheetPinPlacement, indent: str = "\t\t") -> str:
    """Render one ``(pin ...)`` node, newline-terminated, in KiCad's node order."""
    inner = indent + "\t"
    return (
        f'{indent}(pin "{_escape(placement.name)}" {placement.pin_type}\n'
        f"{inner}(at {_format_mm(placement.x_mm)} {_format_mm(placement.y_mm)}"
        f" {placement.rotation})\n"
        f"{inner}(effects\n"
        f"{inner}\t(font\n"
        f"{inner}\t\t(size {_format_mm(DEFAULT_TEXT_HEIGHT_MM)}"
        f" {_format_mm(DEFAULT_TEXT_HEIGHT_MM)})\n"
        f"{inner}\t)\n"
        f"{inner}\t(justify {placement.justify})\n"
        f"{inner})\n"
        f'{inner}(uuid "{placement.uuid}")\n'
        f"{indent})\n"
    )


def _line_start(text: str, index: int) -> int:
    return text.rfind("\n", 0, index) + 1


def _indent_of(text: str, index: int) -> str:
    line_start = _line_start(text, index)
    return text[line_start:index]


def _require_anchor(sheet: SheetBlock) -> int:
    if sheet.instances_start is None:
        raise ValueError(
            f"Sheet '{sheet.name}' has no (instances ...) node, so there is no safe place "
            "to write pins. Open it once in KiCad, or recreate it with sch_create_sheet."
        )
    return sheet.instances_start


def _splice(text: str, sheet: SheetBlock, edits: list[tuple[int, int, str]]) -> str:
    """Apply ``(start, end, replacement)`` edits inside one sheet block."""
    block = text[sheet.start : sheet.end]
    for start, end, replacement in sorted(edits, key=lambda edit: edit[0], reverse=True):
        local_start, local_end = start - sheet.start, end - sheet.start
        block = block[:local_start] + replacement + block[local_end:]
    return text[: sheet.start] + block + text[sheet.end :]


def apply_plan(text: str, sheet: SheetBlock, plan: SheetPinPlan) -> str:
    """Write a whole plan into one sheet block: new size, all pins, nothing else.

    Existing ``(pin ...)`` nodes are removed and re-emitted from the plan, which
    is what keeps left-edge pins correct when the sheet grows. Nothing outside
    the sheet block is touched, so the document's ``title_block`` survives
    untouched -- unlike a kicad-sch-api round trip.
    """
    anchor = _require_anchor(sheet)
    edits: list[tuple[int, int, str]] = [
        (
            sheet.size_span[0],
            sheet.size_span[1],
            f"(size {_format_mm(plan.size[0])} {_format_mm(plan.size[1])})",
        )
    ]
    edits.extend((start, end, "") for start, end in sheet.pin_spans)
    indent = _indent_of(text, anchor)
    rendered = "".join(sheet_pin_block(placement, indent) for placement in plan.placements)
    line_start = _line_start(text, anchor)
    edits.append((line_start, line_start, rendered))
    return _splice(text, sheet, edits)


def insert_pin(text: str, sheet: SheetBlock, placement: SheetPinPlacement) -> str:
    """Add a single pin to a sheet block without touching size or other pins."""
    if any(name == placement.name for name, _type, _uuid in sheet.pins):
        raise ValueError(
            f"Sheet '{sheet.name}' already has a pin named '{placement.name}'. "
            "Use sch_import_sheet_pins to reconcile it with the child sheet."
        )
    anchor = _require_anchor(sheet)
    indent = _indent_of(text, anchor)
    line_start = _line_start(text, anchor)
    return _splice(text, sheet, [(line_start, line_start, sheet_pin_block(placement, indent))])
