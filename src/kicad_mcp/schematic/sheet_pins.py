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
from collections.abc import Iterator
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
