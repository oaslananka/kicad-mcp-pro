"""Read-only, intentionally partial inspection of nominal circular PTH lands.

Nominal land geometry does not capture drill offset, plating, mask, copper weight,
or the manufacturer's finished hole registration. This module never approves fab.
"""

from __future__ import annotations

import math
import re

from .board_file import _iter_blocks

_PAD_HEADER = re.compile(r'^\(pad\s+(?:"([^"\\]*)"|(\S+))\s+thru_hole\s+(\w+)')
_REF = re.compile(r'\(property\s+"Reference"\s+"([^"\\]+)"')
_SIZE = re.compile(r"\(size\s+([\d.]+)\s+([\d.]+)\)")
_DRILL = re.compile(r"\(drill\s+([\d.]+)\)")


def _nominal_circular_ring_mm(pad: str, shape: str) -> float | None:
    """Only centered circular copper with a single round drill is bounded."""
    if shape != "circle":
        return None
    size = _SIZE.search(pad)
    drill = _DRILL.search(pad)
    if size is None or drill is None:
        return None
    x, y, hole = float(size.group(1)), float(size.group(2)), float(drill.group(1))
    if not all(math.isfinite(value) and value > 0 for value in (x, y, hole)):
        return None
    if not math.isclose(x, y, abs_tol=1e-7) or hole >= x:
        return None
    return (min(x, y) - hole) / 2


def audit_pth_annular_ring_lines(board_text: str, minimum_mm: float) -> list[str]:
    """Report definite nominal sub-threshold round lands, never claim PASS.

    Other PTH pad/drill shapes, custom primitives and slots count as unmeasured
    and retain the mandatory written-CAM acceptance gate.
    """
    if not math.isfinite(minimum_mm) or minimum_mm <= 0:
        raise ValueError("PTH annular minimum must be finite and positive.")
    inspected, unmeasured, below = 0, 0, []
    for footprint in _iter_blocks(board_text, "footprint"):
        reference = _REF.search(footprint)
        ref = reference.group(1) if reference else "unknown-reference"
        for pad in _iter_blocks(footprint, "pad"):
            match = _PAD_HEADER.match(pad)
            if match is None:
                continue
            number, shape = match.group(1) or match.group(2), match.group(3)
            ring = _nominal_circular_ring_mm(pad, shape)
            if ring is None:
                unmeasured += 1
                continue
            inspected += 1
            if ring < minimum_mm - 1e-7:
                below.append(
                    f"{ref} pad {number}: nominal ring {ring:.3f} mm < "
                    f"{minimum_mm:.3f} mm 2-layer/1-oz minimum"
                )
    lines = [f"- FAIL: JLCPCB nominal circular PTH {item}." for item in below[:20]]
    if len(below) > 20:
        lines.append(f"- FAIL: {len(below) - 20} more below-minimum nominal circular PTH pads.")
    lines.append(
        f"- WARN: Partial source-board PTH preflight: {inspected} circular pads measured, "
        f"{unmeasured} unmeasured PTH shapes/plated slots; {len(below)} below the "
        f"published 2-layer/1-oz nominal threshold. No physical drill-registration, "
        f"copper-weight, soldermask or plating acceptance; written CAM signoff required."
    )
    return lines
