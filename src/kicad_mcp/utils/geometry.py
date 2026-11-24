"""Pure-domain schematic geometry: real symbol and text-field bounding boxes.

KiCad's file-level API does not expose rendered extents, so the placement and
readability engines historically approximated every symbol with a single fixed
half-size. That ignores two things that actually cause overlap and off-sheet
defects on rendered sheets:

* a symbol's real body/pin extent (a 48-pin MCU is not the size of an 0402), and
* the **text fields** (Reference, Value, …) that KiCad draws *outside* the body.

This module models both with no KiCad dependency, so it is fully unit-testable
and shared by the layout generator (``tools/schematic.py``) and the readability
QA engine (``models/visual_qa.py``). All coordinates are millimetres in KiCad's
schematic space (x right, y down).
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

# KiCad's default schematic text height (mm). Property fields and labels use it
# unless the symbol overrides the font size.
DEFAULT_FONT_MM = 1.27

# Mean glyph advance of KiCad's built-in stroke font as a fraction of the glyph
# height. The newstroke font is roughly square per glyph but renders with inter-
# glyph spacing; 0.66 matches eeschema's own text-extent estimate closely enough
# for clearance checks (it is intentionally a hair generous so boxes never under-
# state real width).
GLYPH_ASPECT = 0.66

# Extra width a bold field draws relative to a normal one.
_BOLD_WIDTH_FACTOR = 1.12


@dataclass(frozen=True, slots=True)
class Box:
    """An axis-aligned bounding box in millimetres."""

    x_min: float
    y_min: float
    x_max: float
    y_max: float

    @classmethod
    def from_center(cls, cx: float, cy: float, width: float, height: float) -> Box:
        half_w = abs(width) / 2.0
        half_h = abs(height) / 2.0
        return cls(cx - half_w, cy - half_h, cx + half_w, cy + half_h)

    @property
    def width(self) -> float:
        return self.x_max - self.x_min

    @property
    def height(self) -> float:
        return self.y_max - self.y_min

    @property
    def center(self) -> tuple[float, float]:
        return ((self.x_min + self.x_max) / 2.0, (self.y_min + self.y_max) / 2.0)

    @property
    def area(self) -> float:
        return max(0.0, self.width) * max(0.0, self.height)

    def expanded(self, margin_mm: float) -> Box:
        """Return a copy grown outward by ``margin_mm`` on every side."""
        return Box(
            self.x_min - margin_mm,
            self.y_min - margin_mm,
            self.x_max + margin_mm,
            self.y_max + margin_mm,
        )

    def contains_point(self, x: float, y: float) -> bool:
        return self.x_min <= x <= self.x_max and self.y_min <= y <= self.y_max

    def overlaps(self, other: Box, *, gap_mm: float = 0.0) -> bool:
        """Whether two boxes overlap, treating a clearance ``gap_mm`` as solid.

        ``gap_mm`` > 0 reports boxes that merely sit closer than the clearance as
        overlapping, which is what readability checks want (touching text is
        unreadable even before it strictly intersects).
        """
        return not (
            self.x_max + gap_mm <= other.x_min
            or other.x_max + gap_mm <= self.x_min
            or self.y_max + gap_mm <= other.y_min
            or other.y_max + gap_mm <= self.y_min
        )

    def intersection_area(self, other: Box) -> float:
        dx = min(self.x_max, other.x_max) - max(self.x_min, other.x_min)
        dy = min(self.y_max, other.y_max) - max(self.y_min, other.y_min)
        if dx <= 0.0 or dy <= 0.0:
            return 0.0
        return dx * dy

    def inside(self, container: Box, *, margin_mm: float = 0.0) -> bool:
        """Whether this box fits entirely within ``container`` (minus a margin)."""
        return (
            self.x_min >= container.x_min + margin_mm
            and self.y_min >= container.y_min + margin_mm
            and self.x_max <= container.x_max - margin_mm
            and self.y_max <= container.y_max - margin_mm
        )


def union(boxes: Iterable[Box]) -> Box | None:
    """Return the smallest box covering every input box, or ``None`` if empty."""
    items = list(boxes)
    if not items:
        return None
    return Box(
        min(b.x_min for b in items),
        min(b.y_min for b in items),
        max(b.x_max for b in items),
        max(b.y_max for b in items),
    )


def text_extent(
    text: str, font_mm: float = DEFAULT_FONT_MM, *, bold: bool = False
) -> tuple[float, float]:
    """Return the ``(width, height)`` a horizontal text string renders to (mm).

    Width is ``len(text) * font * GLYPH_ASPECT`` (bold widened slightly); height
    is the font size. Empty text has zero width so it never inflates a box.
    """
    glyphs = len(text)
    if glyphs == 0:
        return (0.0, 0.0)
    width = glyphs * font_mm * GLYPH_ASPECT
    if bold:
        width *= _BOLD_WIDTH_FACTOR
    return (width, font_mm)


@dataclass(frozen=True, slots=True)
class TextField:
    """A placed text field (Reference/Value/label) with KiCad justify + rotation.

    ``justify`` is the KiCad token set: any of ``left``/``right``/``top``/
    ``bottom`` (a blank set means centred on both axes, KiCad's default). ``angle``
    is the field rotation in degrees (0 or 180 horizontal, 90 or 270 vertical).
    """

    text: str
    x: float
    y: float
    angle: float = 0.0
    font_mm: float = DEFAULT_FONT_MM
    bold: bool = False
    justify: frozenset[str] = field(default_factory=frozenset)

    def box(self) -> Box:
        w, h = text_extent(self.text, self.font_mm, bold=self.bold)
        # Vertical text swaps the rendered footprint.
        if int(round(self.angle)) % 180 == 90:
            w, h = h, w
        just = self.justify
        # Horizontal anchoring: KiCad grows text away from a left/right justify.
        if "left" in just:
            x_min, x_max = self.x, self.x + w
        elif "right" in just:
            x_min, x_max = self.x - w, self.x
        else:
            x_min, x_max = self.x - w / 2.0, self.x + w / 2.0
        # Vertical anchoring: top/bottom justify, else centred on the baseline.
        if "top" in just:
            y_min, y_max = self.y, self.y + h
        elif "bottom" in just:
            y_min, y_max = self.y - h, self.y
        else:
            y_min, y_max = self.y - h / 2.0, self.y + h / 2.0
        return Box(x_min, y_min, x_max, y_max)


def horizontal_symbol_field_justify(justify: frozenset[str], symbol_angle: float) -> frozenset[str]:
    """Convert between native and sheet horizontal anchors (an involution).

    Native KiCad 10 SVG exports show that a horizontal field on a symbol
    rotated 90 or 180 degrees reverses its stored left/right alignment.
    At 0 and 270 degrees the stored horizontal anchor is already correct.
    """
    if symbol_angle % 360 not in {90, 180}:
        return justify
    flip = {"left": "right", "right": "left"}
    return frozenset(flip.get(token, token) for token in justify)


def parse_justify(tokens: str | Iterable[str] | None) -> frozenset[str]:
    """Normalise a KiCad ``(justify …)`` token list into a frozenset.

    Accepts the raw inner string (``"left bottom"``) or an iterable. Mirroring
    (``mirror``) and unknown tokens are dropped — only positional anchors matter
    for a bounding box.
    """
    if tokens is None:
        return frozenset()
    raw: Iterable[str]
    raw = tokens.split() if isinstance(tokens, str) else tokens
    keep = {"left", "right", "top", "bottom"}
    return frozenset(token for token in raw if token in keep)


def body_box_from_pins(
    pin_points: Sequence[tuple[float, float]],
    *,
    pad_mm: float = 1.27,
    min_half_mm: float = 1.27,
    center: tuple[float, float] | None = None,
) -> Box:
    """Estimate a symbol's body box from its absolute pin tip positions.

    Pins sit on the body outline, so their extent is a good lower bound for the
    drawn body; ``pad_mm`` adds the small margin between the pin tips and the
    rendered graphic. When a symbol exposes no pins, a ``min_half_mm`` square
    around ``center`` (or the origin) is returned so the box is never empty.
    """
    if pin_points:
        xs = [p[0] for p in pin_points]
        ys = [p[1] for p in pin_points]
        return Box(min(xs) - pad_mm, min(ys) - pad_mm, max(xs) + pad_mm, max(ys) + pad_mm)
    cx, cy = center if center is not None else (0.0, 0.0)
    return Box(cx - min_half_mm, cy - min_half_mm, cx + min_half_mm, cy + min_half_mm)


def symbol_extent(body: Box, fields: Iterable[TextField]) -> Box:
    """Merge a symbol's body box with its text-field boxes into one extent."""
    boxes = [body]
    boxes.extend(f.box() for f in fields if f.text)
    merged = union(boxes)
    # union() over a non-empty list (body is always present) never returns None.
    return merged if merged is not None else body


def boxes_overlap_pairs(
    boxes: Sequence[tuple[str, Box]], *, gap_mm: float = 0.0
) -> list[tuple[str, str, float]]:
    """Return ``(ref_a, ref_b, overlap_area)`` for every overlapping labelled box.

    A stable O(n²) sweep — schematic sheets hold tens to low hundreds of objects,
    so the simple form is preferred over an interval tree for determinism and
    clarity. Pairs are emitted in input order; ``gap_mm`` treats near-touching
    boxes as overlapping (area is the raw geometric intersection, which may be 0
    when only the clearance gap is violated).
    """
    pairs: list[tuple[str, str, float]] = []
    for i in range(len(boxes)):
        ref_a, box_a = boxes[i]
        for j in range(i + 1, len(boxes)):
            ref_b, box_b = boxes[j]
            if box_a.overlaps(box_b, gap_mm=gap_mm):
                pairs.append((ref_a, ref_b, box_a.intersection_area(box_b)))
    return pairs


def distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])
