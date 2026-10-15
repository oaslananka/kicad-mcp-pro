"""Symbol text-field auto-placement (KiCad ``autoplace_fields`` analogue).

KiCad's eeschema places a symbol's Reference/Value text on the side of the body
with the most free space, away from pins and wires, so the rendered sheet stays
legible. The file-level API does not expose that algorithm, so the layout
generator historically left fields wherever the agent dropped them — which is the
root cause of the "Reference sitting on top of a neighbour's Value" defects.

This module reproduces the placement decision as a pure function over geometry:
given a symbol's body box, its pin tip positions and the surrounding obstacle
boxes, it returns a clearance-aware ``(x, y, justify)`` for each field. It has no
KiCad dependency, so it is unit-testable, and it shares the
:mod:`kicad_mcp.utils.geometry` primitives with the readability QA engine so a
field this module places passes that engine's overlap checks by construction.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .geometry import DEFAULT_FONT_MM, Box, TextField

# Gap between the body edge and the nearest field, and between stacked fields.
DEFAULT_FIELD_MARGIN_MM = 1.27
DEFAULT_LINE_PITCH_MM = 1.778  # one schematic grid step between stacked lines

# Side preference when several sides are equally clear. KiCad favours placing
# text to the right, then above, matching most engineers' reading habit.
_SIDE_ORDER = ("right", "top", "left", "bottom")


@dataclass(frozen=True, slots=True)
class FieldSpec:
    """A field to place: its logical name, rendered text and font size."""

    name: str
    text: str
    font_mm: float = DEFAULT_FONT_MM
    bold: bool = False


@dataclass(frozen=True, slots=True)
class FieldPlacement:
    """The chosen position for one field."""

    name: str
    x: float
    y: float
    angle: float
    justify: frozenset[str]

    def text_field(self, text: str, font_mm: float, *, bold: bool = False) -> TextField:
        return TextField(text, self.x, self.y, self.angle, font_mm, bold=bold, justify=self.justify)


def pin_sides(body: Box, pin_points: Sequence[tuple[float, float]]) -> frozenset[str]:
    """Return the set of body edges (``top``/``bottom``/``left``/``right``) a pin exits.

    A pin is attributed to the edge it is closest to; this tells the placer which
    sides carry wires and should be avoided when there is a free alternative.
    """
    sides: set[str] = set()
    for px, py in pin_points:
        # Attribute the pin to the edge it projects past; an interior pin (rare)
        # falls to its nearest edge so it is still avoided.
        if px <= body.x_min:
            sides.add("left")
        elif px >= body.x_max:
            sides.add("right")
        elif py <= body.y_min:
            sides.add("top")
        elif py >= body.y_max:
            sides.add("bottom")
        else:
            gaps = {
                "left": abs(px - body.x_min),
                "right": abs(px - body.x_max),
                "top": abs(py - body.y_min),
                "bottom": abs(py - body.y_max),
            }
            sides.add(min(gaps, key=lambda k: gaps[k]))
    return frozenset(sides)


def _stacked_boxes_for_side(
    side: str,
    body: Box,
    specs: Sequence[FieldSpec],
    *,
    margin_mm: float,
    pitch_mm: float,
) -> list[tuple[float, float, frozenset[str]]]:
    """Return ``(x, y, justify)`` for each field stacked along ``side``."""
    cx, cy = body.center
    placements: list[tuple[float, float, frozenset[str]]] = []
    line_h = max((s.font_mm for s in specs), default=DEFAULT_FONT_MM)
    total_h = pitch_mm * max(len(specs) - 1, 0)

    if side in ("left", "right"):
        justify = frozenset({"left"}) if side == "right" else frozenset({"right"})
        x = body.x_max + margin_mm if side == "right" else body.x_min - margin_mm
        start_y = cy - total_h / 2.0
        for i, _spec in enumerate(specs):
            placements.append((x, start_y + i * pitch_mm, justify))
    else:  # top / bottom — stack vertically, centred horizontally
        justify = frozenset()
        if side == "top":
            base_y = body.y_min - margin_mm - line_h / 2.0
            for i, _spec in enumerate(specs):
                placements.append((cx, base_y - (len(specs) - 1 - i) * pitch_mm, justify))
        else:
            base_y = body.y_max + margin_mm + line_h / 2.0
            for i, _spec in enumerate(specs):
                placements.append((cx, base_y + i * pitch_mm, justify))
    return placements


def _side_cost(
    side: str,
    boxes: list[Box],
    obstacles: Sequence[Box],
    avoid_sides: frozenset[str],
) -> tuple[float, float, int]:
    """Score a side: lower is better.

    The cost is ``(pin_conflict, overlap_area, preference_rank)`` compared
    lexicographically — never put text where a pin/wire exits if another side is
    free, then minimise obstacle overlap, then fall back to the reading-order
    preference.
    """
    overlap = 0.0
    for box in boxes:
        for obstacle in obstacles:
            overlap += box.intersection_area(obstacle)
    pin_conflict = 1.0 if side in avoid_sides else 0.0
    rank = _SIDE_ORDER.index(side) if side in _SIDE_ORDER else len(_SIDE_ORDER)
    return (pin_conflict, overlap, rank)


def autoplace_fields(
    body: Box,
    pin_points: Sequence[tuple[float, float]],
    obstacles: Sequence[Box],
    specs: Sequence[FieldSpec],
    *,
    margin_mm: float = DEFAULT_FIELD_MARGIN_MM,
    pitch_mm: float = DEFAULT_LINE_PITCH_MM,
) -> list[FieldPlacement]:
    """Place each field on the clearest body side, away from pins and obstacles.

    ``obstacles`` are the boxes the fields must avoid (neighbouring symbol bodies
    and their already-placed fields, plus this symbol's own body). The returned
    placements are ordered to match ``specs``. Fields with empty text are skipped
    in the layout but still returned (anchored at the body centre) so callers can
    rely on a 1:1 mapping.
    """
    visible = [s for s in specs if s.text]
    avoid = pin_sides(body, pin_points)

    best_cost: tuple[float, float, int] | None = None
    best_coords: list[tuple[float, float, frozenset[str]]] = []
    for side in _SIDE_ORDER:
        coords = _stacked_boxes_for_side(
            side, body, visible, margin_mm=margin_mm, pitch_mm=pitch_mm
        )
        boxes = [
            TextField(spec.text, x, y, 0.0, spec.font_mm, bold=spec.bold, justify=just).box()
            for spec, (x, y, just) in zip(visible, coords, strict=True)
        ]
        cost = _side_cost(side, boxes, obstacles, avoid)
        if best_cost is None or cost < best_cost:
            best_cost = cost
            best_coords = coords

    placements: list[FieldPlacement] = []
    coord_iter = iter(best_coords)
    for spec in specs:
        if spec.text:
            x, y, just = next(coord_iter)
            placements.append(FieldPlacement(spec.name, x, y, 0.0, just))
        else:
            cx, cy = body.center
            placements.append(FieldPlacement(spec.name, cx, cy, 0.0, frozenset()))
    return placements


def field_extent(specs: Sequence[FieldSpec], placements: Sequence[FieldPlacement]) -> Box | None:
    """Return the merged box of the placed, non-empty fields (for clearance use)."""
    boxes: list[Box] = []
    for spec, placement in zip(specs, placements, strict=True):
        if not spec.text:
            continue
        boxes.append(placement.text_field(spec.text, spec.font_mm, bold=spec.bold).box())
    if not boxes:
        return None
    merged = boxes[0]
    for box in boxes[1:]:
        merged = Box(
            min(merged.x_min, box.x_min),
            min(merged.y_min, box.y_min),
            max(merged.x_max, box.x_max),
            max(merged.y_max, box.y_max),
        )
    return merged
