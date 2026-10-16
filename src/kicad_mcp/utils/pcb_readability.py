"""Headless PCB readability QA (off-board parts, silk and body overlap).

KiCad's DRC catches silkscreen clipping and courtyard overlap, but it needs a
running KiCad and is comparatively slow. This module is a fast, pure-domain
*first pass* that works straight from the parsed ``.kicad_pcb`` footprint map
(the structure ``_parse_board_footprint_blocks`` produces), with no KiCad
dependency. It mirrors the schematic readability engine and reuses the shared
:mod:`kicad_mcp.utils.geometry` primitives, so its findings line up with
``sch_visual_qa`` in spirit: things that make a *rendered board* hard to read or
assemble, surfaced before the authoritative DRC run.

Findings (advisory; DRC remains the sign-off authority):

* ``offboard_component`` — a footprint body extends past the board outline.
* ``ref_silk_overlap``    — two reference designators overlap on the silkscreen.
* ``body_overlap``        — two footprint bodies overlap (INFO; DRC courtyard is
  the precise check).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any

from .geometry import Box, TextField, boxes_overlap_pairs

FootprintMap = dict[str, dict[str, Any]]

_LEVEL_ORDER = {"PASS": 0, "INFO": 0, "WARN": 1, "FAIL": 2}

# Default KiCad silkscreen reference text height (mm) when a footprint does not
# override it.
DEFAULT_SILK_FONT_MM = 1.0

# Bodies/silk that intersect by less than this are treated as a harmless graze.
BODY_OVERLAP_MIN_AREA_MM2 = 1.0
SILK_OVERLAP_MIN_AREA_MM2 = 0.5


@dataclass(frozen=True, slots=True)
class PcbFinding:
    level: str
    code: str
    message: str
    ref: str = ""
    x: float | None = None
    y: float | None = None

    def as_dict(self) -> dict[str, object]:
        data: dict[str, object] = {"level": self.level, "code": self.code, "message": self.message}
        if self.ref:
            data["ref"] = self.ref
        if self.x is not None and self.y is not None:
            data["position"] = [self.x, self.y]
        return data


def _rotate(dx: float, dy: float, angle_deg: float) -> tuple[float, float]:
    rad = math.radians(angle_deg)
    cos_a, sin_a = math.cos(rad), math.sin(rad)
    return (dx * cos_a - dy * sin_a, dx * sin_a + dy * cos_a)


def _body_box(entry: dict[str, Any]) -> Box | None:
    x = entry.get("x_mm")
    y = entry.get("y_mm")
    w = entry.get("width_mm")
    h = entry.get("height_mm")
    if x is None or y is None or not w or not h:
        return None
    return Box.from_center(float(x), float(y), float(w), float(h))


def _reference_silk_box(reference: str, entry: dict[str, Any]) -> Box | None:
    """Build the absolute silkscreen text box of a footprint's reference."""
    block = str(entry.get("block", ""))
    fx = entry.get("x_mm")
    fy = entry.get("y_mm")
    if fx is None or fy is None or not block:
        return None
    match = re.search(
        r'\(property\s+"Reference"\s+"[^"]*"\s*\(at\s+([-\d.]+)\s+([-\d.]+)(?:\s+([-\d.]+))?\)',
        block,
    )
    if match is None:
        return None
    dx, dy = float(match.group(1)), float(match.group(2))
    prop_rot = float(match.group(3)) if match.group(3) else 0.0
    foot_rot = float(entry.get("rotation", 0) or 0)
    rdx, rdy = _rotate(dx, dy, foot_rot)
    abs_x, abs_y = float(fx) + rdx, float(fy) + rdy
    font_mm = DEFAULT_SILK_FONT_MM
    size = re.search(r"\(size\s+(-?[\d.]+)", block)
    if size:
        try:
            font_mm = float(size.group(1)) or DEFAULT_SILK_FONT_MM
        except ValueError:
            font_mm = DEFAULT_SILK_FONT_MM
    angle = foot_rot + prop_rot
    return TextField(reference, abs_x, abs_y, angle, font_mm).box()


def detect_offboard(
    footprints: FootprintMap, bounds: tuple[float, float, float, float] | None
) -> list[PcbFinding]:
    if bounds is None:
        return []
    board = Box(bounds[0], bounds[1], bounds[2], bounds[3])
    findings: list[PcbFinding] = []
    for reference, entry in sorted(footprints.items()):
        box = _body_box(entry)
        if box is None:
            continue
        if not box.inside(board):
            findings.append(
                PcbFinding(
                    "WARN",
                    "offboard_component",
                    f"Footprint {reference} extends outside the board outline "
                    f"(at {entry['x_mm']:.1f}, {entry['y_mm']:.1f}).",
                    ref=reference,
                    x=float(entry["x_mm"]),
                    y=float(entry["y_mm"]),
                )
            )
    return findings


def detect_body_overlap(footprints: FootprintMap) -> list[PcbFinding]:
    boxes: list[tuple[str, Box]] = []
    for reference, entry in sorted(footprints.items()):
        box = _body_box(entry)
        if box is not None:
            boxes.append((reference, box))
    findings: list[PcbFinding] = []
    for ref_a, ref_b, area in boxes_overlap_pairs(boxes):
        if area < BODY_OVERLAP_MIN_AREA_MM2:
            continue
        findings.append(
            PcbFinding(
                "INFO",
                "body_overlap",
                f"Footprints {ref_a} and {ref_b} bodies overlap (~{area:.1f} mm²); "
                "confirm courtyard clearance in DRC.",
                ref=ref_a,
            )
        )
    return findings


def detect_ref_silk_overlap(footprints: FootprintMap) -> list[PcbFinding]:
    boxes: list[tuple[str, Box]] = []
    for reference, entry in sorted(footprints.items()):
        box = _reference_silk_box(reference, entry)
        if box is not None:
            boxes.append((reference, box))
    findings: list[PcbFinding] = []
    for ref_a, ref_b, area in boxes_overlap_pairs(boxes):
        if area < SILK_OVERLAP_MIN_AREA_MM2:
            continue
        findings.append(
            PcbFinding(
                "WARN",
                "ref_silk_overlap",
                f"Reference designators {ref_a} and {ref_b} overlap on the silkscreen "
                f"(~{area:.1f} mm²). Move or hide one so both stay legible.",
                ref=ref_a,
            )
        )
    return findings


def rollup_status(findings: list[PcbFinding]) -> str:
    worst = max((_LEVEL_ORDER.get(f.level, 0) for f in findings), default=0)
    for level, rank in _LEVEL_ORDER.items():
        if rank == worst:
            return level
    return "PASS"


def run_pcb_readability(
    footprints: FootprintMap,
    bounds: tuple[float, float, float, float] | None,
) -> dict[str, object]:
    """Run every headless PCB readability check and return a structured report."""
    findings: list[PcbFinding] = []
    findings.extend(detect_offboard(footprints, bounds))
    findings.extend(detect_ref_silk_overlap(footprints))
    findings.extend(detect_body_overlap(footprints))
    return {
        "footprint_count": len(footprints),
        "board_bounds": list(bounds) if bounds else None,
        "status": rollup_status(findings),
        "findings": [f.as_dict() for f in findings],
    }
