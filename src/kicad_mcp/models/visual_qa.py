"""Headless visual-QA for schematics (issue #153).

Detects readability defects that ERC cannot catch — label collisions, symbol and
text overlap, off-sheet items, title-block gaps and dense label fanout — directly
from the ``.kicad_sch`` S-expression geometry, with no rendering dependency. When
a PNG render (``sch_render_png``, #115) is available it can be attached as
evidence, but every check here works purely from file geometry so the engine runs
anywhere, including fully headless CI.

The overlap checks model **real geometry**: a symbol's drawn body (from the cached
``lib_symbols`` graphics/pins) and its **visible text fields** (Reference/Value),
plus the real rendered extent of every label. This is what catches the text- and
field-overlap defects a pin-anchor-only check silently passed. The shared
geometry primitives live in :mod:`kicad_mcp.utils.geometry`.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from ..utils.geometry import (
    DEFAULT_FONT_MM,
    Box,
    TextField,
    body_box_from_pins,
    boxes_overlap_pairs,
    parse_justify,
    symbol_extent,
    union,
)
from .contract_verifier import extract_balanced_block

# Landscape paper extents (mm); portrait swaps width/height. Mirrors the table in
# tools/schematic.py but kept local so this pure module stays dependency-free.
PAPER_SIZES_MM: dict[str, tuple[float, float]] = {
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
    "USLetter": (279.4, 215.9),
    "USLegal": (355.6, 215.9),
}
DEFAULT_PAPER = "A4"

_LEVEL_ORDER = {"PASS": 0, "INFO": 0, "WARN": 1, "FAIL": 2}

# Two labels closer than this (anchor distance) are treated as overlapping by the
# legacy anchor check kept for backward compatibility.
LABEL_OVERLAP_TOLERANCE_MM = 1.0
# A label with this many close neighbours marks a dense, hard-to-read fanout.
DENSE_FANOUT_RADIUS_MM = 5.0
DENSE_FANOUT_NEIGHBOURS = 6

# Geometry thresholds. Boxes that intersect by less than this are treated as a
# harmless near-touch rather than a defect — real stacked text/bodies overlap by
# several mm², while legal tight layouts only graze by a fraction of one.
TEXT_OVERLAP_MIN_AREA_MM2 = 1.0
SYMBOL_OVERLAP_MIN_AREA_MM2 = 1.0

# KiCad hides these property fields by default, so they are not drawn and must not
# contribute to a symbol's visible text extent.
_HIDDEN_BY_DEFAULT_FIELDS = frozenset({"Footprint", "Datasheet"})


@dataclass(frozen=True, slots=True)
class VisualFinding:
    """A single readability finding with optional object ref/position."""

    level: str
    code: str
    message: str
    ref: str = ""
    x: float | None = None
    y: float | None = None

    def as_dict(self) -> dict[str, object]:
        data: dict[str, object] = {
            "level": self.level,
            "code": self.code,
            "message": self.message,
        }
        if self.ref:
            data["ref"] = self.ref
        if self.x is not None and self.y is not None:
            data["position"] = [self.x, self.y]
        return data


@dataclass(frozen=True, slots=True)
class LabelItem:
    text: str
    x: float
    y: float
    kind: str
    angle: float = 0.0
    font_mm: float = DEFAULT_FONT_MM
    justify: frozenset[str] = frozenset()

    def box(self) -> Box:
        return TextField(
            self.text, self.x, self.y, self.angle, self.font_mm, justify=self.justify
        ).box()


@dataclass(frozen=True, slots=True)
class SymbolItem:
    reference: str
    lib_id: str
    x: float
    y: float


@dataclass(frozen=True, slots=True)
class PlacedSymbol:
    """A placed symbol instance with its real body box and visible text fields."""

    reference: str
    lib_id: str
    x: float
    y: float
    angle: float
    body: Box
    fields: tuple[TextField, ...]

    def extent(self) -> Box:
        return symbol_extent(self.body, self.fields)


def parse_paper_extent(sch_text: str) -> tuple[float, float]:
    """Return the (width, height) of the sheet in millimetres."""

    match = re.search(r'\(paper\s+"([^"]+)"((?:\s+[\w.]+)*)\)', sch_text)
    if match is None:
        return PAPER_SIZES_MM[DEFAULT_PAPER]
    name = match.group(1)
    rest = match.group(2).split()
    numbers = [float(token) for token in rest if _is_number(token)]
    if name == "User" and len(numbers) >= 2:
        return numbers[0], numbers[1]
    width, height = PAPER_SIZES_MM.get(name, PAPER_SIZES_MM[DEFAULT_PAPER])
    if "portrait" in rest:
        width, height = height, width
    return width, height


def _is_number(token: str) -> bool:
    try:
        float(token)
    except ValueError:
        return False
    return True


def _rotate_local(x: float, y: float, angle_deg: float) -> tuple[float, float]:
    """Map a symbol-library local point to a placement-relative offset.

    Mirrors ``get_pin_positions``: schematic space inverts the library y axis, so
    the relative offset is ``rotate(x, -y, angle)``.
    """
    radians = math.radians(angle_deg)
    cos_a = math.cos(radians)
    sin_a = math.sin(radians)
    ly = -y
    return (x * cos_a - ly * sin_a, x * sin_a + ly * cos_a)


def _extent_of_points(points: list[tuple[float, float]]) -> Box | None:
    if not points:
        return None
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return Box(min(xs), min(ys), max(xs), max(ys))


def parse_lib_symbol_local_points(sch_text: str) -> dict[str, list[tuple[float, float]]]:
    """Return ``{lib_id: [local body points]}`` from the cached ``lib_symbols``.

    Collects the coordinates of every graphic (rectangle/polyline/circle/arc) and
    pin in each cached library symbol. These are local symbol-library coordinates;
    callers transform them per placement. Symbols absent from the cache (older
    files, hand-written fixtures) simply do not appear in the map.
    """
    lib_match = re.search(r"\(lib_symbols\b", sch_text)
    if lib_match is None:
        return {}
    lib_block = extract_balanced_block(sch_text, lib_match.start())

    bodies: dict[str, list[tuple[float, float]]] = {}
    for sym_match in re.finditer(r'\(symbol\s+"([^"]+)"', lib_block):
        name = sym_match.group(1)
        # Only the top-level library entries carry a "Lib:Name" id; the nested
        # graphic units are named "Lib_0_1" etc. and are scanned via the block.
        if ":" not in name:
            continue
        block = extract_balanced_block(lib_block, sym_match.start())
        bodies[name] = _collect_symbol_local_points(block)
    return bodies


def _collect_symbol_local_points(block: str) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    for start_x, start_y, end_x, end_y in re.findall(
        r"\(rectangle\s+\(start\s+(-?[\d.]+)\s+(-?[\d.]+)\)\s+\(end\s+(-?[\d.]+)\s+(-?[\d.]+)\)",
        block,
    ):
        points.append((float(start_x), float(start_y)))
        points.append((float(end_x), float(end_y)))
    for xy_x, xy_y in re.findall(r"\(xy\s+(-?[\d.]+)\s+(-?[\d.]+)\)", block):
        points.append((float(xy_x), float(xy_y)))
    for cx, cy, radius in re.findall(
        r"\(circle\s+\(center\s+(-?[\d.]+)\s+(-?[\d.]+)\)\s+\(radius\s+(-?[\d.]+)\)",
        block,
    ):
        cxf, cyf, rf = float(cx), float(cy), float(radius)
        points.extend([(cxf - rf, cyf - rf), (cxf + rf, cyf + rf)])
    for px, py, angle, length in re.findall(
        r"\(pin\s+\w+\s+\w+\s+\(at\s+(-?[\d.]+)\s+(-?[\d.]+)\s+(-?[\d.]+)\)\s+\(length\s+(-?[\d.]+)\)",
        block,
    ):
        pxf, pyf, angf, lenf = float(px), float(py), float(angle), float(length)
        points.append((pxf, pyf))
        # Include the body-side end so the pin stub is covered either way.
        rad = math.radians(angf)
        points.append((pxf - lenf * math.cos(rad), pyf - lenf * math.sin(rad)))
    return points


def _instance_body_box(
    lib_id: str,
    x: float,
    y: float,
    angle: float,
    local_points: dict[str, list[tuple[float, float]]],
) -> Box:
    points = local_points.get(lib_id)
    if not points:
        # No cached graphic: a small square keeps the box non-empty without
        # over-stating extent for symbols we cannot measure.
        return body_box_from_pins([], min_half_mm=DEFAULT_FONT_MM, center=(x, y))
    transformed: list[tuple[float, float]] = []
    for px, py in points:
        rx, ry = _rotate_local(px, py, angle)
        transformed.append((x + rx, y + ry))
    box = _extent_of_points(transformed)
    if box is None:
        return body_box_from_pins([], center=(x, y))
    # A symbol defined only by collinear pins (e.g. a 2-pin part with no body
    # rectangle) yields a degenerate zero-width/height line; give it a minimum
    # extent so overlap checks still see a real footprint.
    min_full = 2 * DEFAULT_FONT_MM
    if box.width < min_full or box.height < min_full:
        cx, cy = box.center
        half_w = max(box.width, min_full) / 2.0
        half_h = max(box.height, min_full) / 2.0
        return Box(cx - half_w, cy - half_h, cx + half_w, cy + half_h)
    return box


def _parse_effects(prop_block: str) -> tuple[float, frozenset[str], bool]:
    """Return ``(font_mm, justify, hidden)`` for a property/effects block."""
    font_mm = DEFAULT_FONT_MM
    size_match = re.search(r"\(font[^)]*\(size\s+(-?[\d.]+)", prop_block)
    if size_match:
        try:
            font_mm = float(size_match.group(1)) or DEFAULT_FONT_MM
        except ValueError:
            font_mm = DEFAULT_FONT_MM
    justify_match = re.search(r"\(justify\s+([^)]*)\)", prop_block)
    justify = parse_justify(justify_match.group(1)) if justify_match else frozenset()
    hidden = bool(re.search(r"\(hide\s+yes\)", prop_block)) or bool(
        re.search(r"\(effects\b[^)]*\bhide\b", prop_block)
    )
    return font_mm, justify, hidden


def _parse_instance_fields(symbol_block: str) -> tuple[str, list[TextField]]:
    """Return ``(reference, visible_text_fields)`` for a placed symbol block."""
    reference = ""
    fields: list[TextField] = []
    cursor = 0
    while True:
        idx = symbol_block.find('(property "', cursor)
        if idx < 0:
            break
        prop_block = extract_balanced_block(symbol_block, idx)
        cursor = idx + max(len(prop_block), 1)
        head = re.match(
            r'\(property\s+"([^"]*)"\s+"([^"]*)"\s+\(at\s+(-?[\d.]+)\s+(-?[\d.]+)\s+(-?[\d.]+)\)',
            prop_block,
        )
        if head is None:
            continue
        name, text, fx, fy, fang = head.groups()
        if name == "Reference":
            reference = text
        font_mm, justify, hidden = _parse_effects(prop_block)
        if hidden or name in _HIDDEN_BY_DEFAULT_FIELDS or not text:
            continue
        fields.append(TextField(text, float(fx), float(fy), float(fang), font_mm, justify=justify))
    return reference, fields


def parse_placed_symbols(sch_text: str) -> list[PlacedSymbol]:
    """Extract every placed symbol with its real body box and visible fields."""
    local_points = parse_lib_symbol_local_points(sch_text)
    placed: list[PlacedSymbol] = []
    for match in re.finditer(r"\(symbol\s+\(lib_", sch_text):
        block = extract_balanced_block(sch_text, match.start())
        at_match = re.search(r"\(at\s+(-?[\d.]+)\s+(-?[\d.]+)\s*(-?[\d.]+)?", block)
        lib_match = re.search(r'\(lib_id\s+"([^"]+)"', block)
        if at_match is None or lib_match is None:
            continue
        x = float(at_match.group(1))
        y = float(at_match.group(2))
        angle = float(at_match.group(3)) if at_match.group(3) else 0.0
        lib_id = lib_match.group(1)
        reference, fields = _parse_instance_fields(block)
        body = _instance_body_box(lib_id, x, y, angle, local_points)
        placed.append(PlacedSymbol(reference, lib_id, x, y, angle, body, tuple(fields)))
    return placed


def parse_labels(sch_text: str) -> list[LabelItem]:
    """Extract local/global/hierarchical labels with their positions.

    Global/hierarchical labels commonly carry an explicit ``(justify ...)``
    override (see ``label_block`` in ``tools/schematic.py``) so their icon
    doesn't overlap the text; reading the real token keeps overlap detection
    in sync with what KiCad actually renders instead of assuming center.
    """

    # Global/hierarchical labels normally carry a (shape ...) token between
    # their name and (at ...) (see label_block in tools/schematic.py); skip it
    # so shaped labels aren't silently missed by every downstream QA check.
    patterns = {
        "local": r'\(label\s+"([^"]*)"\s+\(at\s+(-?[\d.]+)\s+(-?[\d.]+)\s*(-?[\d.]+)?',
        "global": (
            r'\(global_label\s+"([^"]*)"\s+(?:\(shape\s+\w+\)\s+)?'
            r"\(at\s+(-?[\d.]+)\s+(-?[\d.]+)\s*(-?[\d.]+)?"
        ),
        "hierarchical": (
            r'\(hierarchical_label\s+"([^"]*)"\s+(?:\(shape\s+\w+\)\s+)?'
            r"\(at\s+(-?[\d.]+)\s+(-?[\d.]+)\s*(-?[\d.]+)?"
        ),
    }
    labels: list[LabelItem] = []
    for kind, pattern in patterns.items():
        for match in re.finditer(pattern, sch_text):
            angle = float(match.group(4)) if match.group(4) else 0.0
            block = extract_balanced_block(sch_text, match.start())
            justify_match = re.search(r"\(justify\s+([^)]*)\)", block) if block else None
            justify = parse_justify(justify_match.group(1)) if justify_match else frozenset()
            labels.append(
                LabelItem(
                    match.group(1),
                    float(match.group(2)),
                    float(match.group(3)),
                    kind,
                    angle,
                    justify=justify,
                )
            )
    return labels


def parse_symbols(sch_text: str) -> list[SymbolItem]:
    """Extract placed symbol instances with their reference and position."""

    symbols: list[SymbolItem] = []
    for match in re.finditer(r"\(symbol\s+\(lib_", sch_text):
        block = extract_balanced_block(sch_text, match.start())
        at_match = re.search(r"\(at\s+(-?[\d.]+)\s+(-?[\d.]+)", block)
        if at_match is None:
            continue
        lib_match = re.search(r'\(lib_id\s+"([^"]+)"', block)
        ref_match = re.search(r'\(property\s+"Reference"\s+"([^"]*)"', block)
        symbols.append(
            SymbolItem(
                reference=ref_match.group(1) if ref_match else "",
                lib_id=lib_match.group(1) if lib_match else "",
                x=float(at_match.group(1)),
                y=float(at_match.group(2)),
            )
        )
    return symbols


def detect_label_collisions(
    labels: list[LabelItem], min_overlap_area_mm2: float = TEXT_OVERLAP_MIN_AREA_MM2
) -> list[VisualFinding]:
    """Flag pairs of labels whose rendered text boxes overlap.

    Models the real text extent (length × font), not just the anchor point, so a
    pair of long labels a few mm apart that visibly collide is caught where the
    legacy anchor check passed them. Boxes that merely graze by less than
    ``min_overlap_area_mm2`` are treated as a harmless near-touch (abutting bus
    labels) rather than a defect.
    """

    boxes = [(str(i), label.box()) for i, label in enumerate(labels)]
    findings: list[VisualFinding] = []
    for idx_a, idx_b, area in boxes_overlap_pairs(boxes):
        if area < min_overlap_area_mm2:
            continue
        a = labels[int(idx_a)]
        b = labels[int(idx_b)]
        distance = math.hypot(a.x - b.x, a.y - b.y)
        findings.append(
            VisualFinding(
                "WARN",
                "label_overlap",
                f"Labels '{a.text}' and '{b.text}' overlap (~{distance:.2f} mm apart).",
                ref=a.text,
                x=a.x,
                y=a.y,
            )
        )
    return findings


def detect_symbol_overlap(symbols: list[PlacedSymbol]) -> list[VisualFinding]:
    """Flag placed symbols whose drawn bodies overlap by a meaningful area."""

    boxes = [(str(i), symbol.body) for i, symbol in enumerate(symbols)]
    findings: list[VisualFinding] = []
    for idx_a, idx_b, area in boxes_overlap_pairs(boxes):
        if area < SYMBOL_OVERLAP_MIN_AREA_MM2:
            continue
        a = symbols[int(idx_a)]
        b = symbols[int(idx_b)]
        name_a = a.reference or a.lib_id or "symbol"
        name_b = b.reference or b.lib_id or "symbol"
        findings.append(
            VisualFinding(
                "WARN",
                "symbol_overlap",
                f"Symbols {name_a} and {name_b} overlap (~{area:.1f} mm² of body). "
                "Move them apart so the rendered sheet stays readable.",
                ref=name_a,
                x=a.x,
                y=a.y,
            )
        )
    return findings


def detect_text_overlap(
    symbols: list[PlacedSymbol], labels: list[LabelItem]
) -> list[VisualFinding]:
    """Flag visible symbol fields and labels that overlap across objects.

    Fields belonging to the *same* symbol are skipped (Reference above Value is by
    design); this catches one symbol's value landing on a neighbour's reference,
    or a label dropped on top of a part's text — the dominant rendered-sheet
    defect ERC never sees.
    """

    owners: list[str] = []
    boxes: list[tuple[str, Box]] = []
    for s_idx, symbol in enumerate(symbols):
        for field in symbol.fields:
            owners.append(f"S{s_idx}")
            boxes.append((f"{symbol.reference or symbol.lib_id}:{field.text}", field.box()))
    for label in labels:
        owners.append(f"L{len(owners)}")
        boxes.append((f"label:{label.text}", label.box()))

    findings: list[VisualFinding] = []
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            if owners[i] == owners[j]:
                continue
            ref_a, box_a = boxes[i]
            ref_b, box_b = boxes[j]
            if not box_a.overlaps(box_b):
                continue
            area = box_a.intersection_area(box_b)
            if area < TEXT_OVERLAP_MIN_AREA_MM2:
                continue
            cx, cy = box_a.center
            findings.append(
                VisualFinding(
                    "WARN",
                    "text_overlap",
                    f"Text '{ref_a}' overlaps '{ref_b}' (~{area:.1f} mm²). "
                    "Reposition the field or symbol so the text is legible.",
                    ref=ref_a,
                    x=cx,
                    y=cy,
                )
            )
    return findings


def detect_offsheet(
    symbols: list[SymbolItem],
    labels: list[LabelItem],
    extent: tuple[float, float],
) -> list[VisualFinding]:
    """Flag symbols/labels whose anchor sits outside the sheet boundary.

    Legacy anchor-based check retained for direct callers and tests;
    :func:`detect_offsheet_boxes` is the bounding-box-aware variant used by the
    full QA run.
    """

    width, height = extent
    findings: list[VisualFinding] = []
    for symbol in symbols:
        if not (0.0 <= symbol.x <= width and 0.0 <= symbol.y <= height):
            name = symbol.reference or symbol.lib_id or "symbol"
            findings.append(
                VisualFinding(
                    "WARN",
                    "offsheet_symbol",
                    f"Symbol {name} is outside the {width:.0f}x{height:.0f} mm sheet "
                    f"(at {symbol.x:.1f}, {symbol.y:.1f}).",
                    ref=symbol.reference,
                    x=symbol.x,
                    y=symbol.y,
                )
            )
    for label in labels:
        if not (0.0 <= label.x <= width and 0.0 <= label.y <= height):
            findings.append(
                VisualFinding(
                    "WARN",
                    "offsheet_label",
                    f"Label '{label.text}' is outside the sheet (at {label.x:.1f}, {label.y:.1f}).",
                    ref=label.text,
                    x=label.x,
                    y=label.y,
                )
            )
    return findings


def detect_offsheet_boxes(
    symbols: list[PlacedSymbol],
    labels: list[LabelItem],
    extent: tuple[float, float],
) -> list[VisualFinding]:
    """Flag symbols/labels whose **rendered extent** leaves the sheet boundary."""

    width, height = extent
    sheet = Box(0.0, 0.0, width, height)
    findings: list[VisualFinding] = []
    for symbol in symbols:
        if not symbol.extent().inside(sheet):
            name = symbol.reference or symbol.lib_id or "symbol"
            findings.append(
                VisualFinding(
                    "WARN",
                    "offsheet_symbol",
                    f"Symbol {name} extends outside the {width:.0f}x{height:.0f} mm sheet "
                    f"(at {symbol.x:.1f}, {symbol.y:.1f}).",
                    ref=symbol.reference,
                    x=symbol.x,
                    y=symbol.y,
                )
            )
    for label in labels:
        if not label.box().inside(sheet):
            findings.append(
                VisualFinding(
                    "WARN",
                    "offsheet_label",
                    f"Label '{label.text}' extends outside the sheet "
                    f"(at {label.x:.1f}, {label.y:.1f}).",
                    ref=label.text,
                    x=label.x,
                    y=label.y,
                )
            )
    return findings


def detect_dense_fanout(
    labels: list[LabelItem],
    radius_mm: float = DENSE_FANOUT_RADIUS_MM,
    neighbours: int = DENSE_FANOUT_NEIGHBOURS,
) -> list[VisualFinding]:
    """Flag tight clusters of labels that are likely unreadable when rendered."""

    findings: list[VisualFinding] = []
    reported: set[int] = set()
    for i, anchor in enumerate(labels):
        if i in reported:
            continue
        close = [
            j
            for j, other in enumerate(labels)
            if j != i and math.hypot(anchor.x - other.x, anchor.y - other.y) <= radius_mm
        ]
        if len(close) >= neighbours:
            reported.update(close)
            reported.add(i)
            findings.append(
                VisualFinding(
                    "INFO",
                    "dense_label_fanout",
                    f"{len(close) + 1} labels cluster within {radius_mm:.0f} mm near "
                    f"({anchor.x:.1f}, {anchor.y:.1f}); rendering may be unreadable.",
                    x=anchor.x,
                    y=anchor.y,
                )
            )
    return findings


def check_title_block(sch_text: str) -> list[VisualFinding]:
    """Report missing title-block fields (title is WARN, others advisory)."""

    match = re.search(r"\(title_block\b", sch_text)
    if match is None:
        return [
            VisualFinding("WARN", "title_block_missing", "Schematic has no title block (advisory).")
        ]
    block = extract_balanced_block(sch_text, match.start())
    findings: list[VisualFinding] = []
    title = re.search(r'\(title\s+"([^"]*)"', block)
    if title is None or not title.group(1).strip():
        findings.append(VisualFinding("WARN", "title_block_title", "Title block has no title."))
    for field_name in ("rev", "date", "company"):
        field_match = re.search(rf'\({field_name}\s+"([^"]*)"', block)
        if field_match is None or not field_match.group(1).strip():
            findings.append(
                VisualFinding(
                    "INFO", f"title_block_{field_name}", f"Title block has no {field_name}."
                )
            )
    return findings


def rollup_status(findings: list[VisualFinding]) -> str:
    worst = 0
    for finding in findings:
        worst = max(worst, _LEVEL_ORDER.get(finding.level, 0))
    for level, rank in _LEVEL_ORDER.items():
        if rank == worst:
            return level
    return "PASS"


def run_visual_qa(sch_text: str, *, render_path: str = "") -> dict[str, object]:
    """Run every headless readability check and return a structured report."""

    extent = parse_paper_extent(sch_text)
    labels = parse_labels(sch_text)
    symbols = parse_symbols(sch_text)
    placed = parse_placed_symbols(sch_text)

    findings: list[VisualFinding] = []
    findings.extend(detect_label_collisions(labels))
    findings.extend(detect_symbol_overlap(placed))
    findings.extend(detect_text_overlap(placed, labels))
    findings.extend(detect_offsheet_boxes(placed, labels, extent))
    findings.extend(detect_dense_fanout(labels))
    findings.extend(check_title_block(sch_text))

    report: dict[str, object] = {
        "paper_mm": [extent[0], extent[1]],
        "symbol_count": len(symbols),
        "label_count": len(labels),
        "status": rollup_status(findings),
        "findings": [finding.as_dict() for finding in findings],
    }
    if render_path:
        report["render"] = render_path
    return report


__all__ = [
    "Box",
    "LabelItem",
    "PlacedSymbol",
    "SymbolItem",
    "VisualFinding",
    "check_title_block",
    "detect_dense_fanout",
    "detect_label_collisions",
    "detect_offsheet",
    "detect_offsheet_boxes",
    "detect_symbol_overlap",
    "detect_text_overlap",
    "parse_labels",
    "parse_paper_extent",
    "parse_placed_symbols",
    "parse_symbols",
    "rollup_status",
    "run_visual_qa",
    "union",
]
