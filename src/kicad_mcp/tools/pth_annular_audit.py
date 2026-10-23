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
    if not math.isclose(x, y, abs_tol=1e-7):
        return None
    return (min(x, y) - hole) / 2


def _formatted_nominal_ring_comparison(ring: float, minimum_mm: float) -> str:
    # Keep ordinary reports concise but never print an apparent "0.180 < 0.180"
    # near a strict manufacturing threshold.
    precision = 7 if f"{ring:.3f}" == f"{minimum_mm:.3f}" else 3
    return f"{ring:.{precision}f} mm < {minimum_mm:.{precision}f} mm"


def _inspect_footprint_round_pth(
    footprint: str, reference: str, minimum_mm: float
) -> tuple[int, int, list[str]]:
    """Return measured/unmeasured count and nominal violations for one part."""
    inspected = unmeasured = 0
    failures: list[str] = []
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
            failures.append(
                f"{reference} pad {number}: nominal ring "
                f"{_formatted_nominal_ring_comparison(ring, minimum_mm)} "
                "2-layer/1-oz minimum"
            )
    return inspected, unmeasured, failures


def audit_pth_annular_ring_lines(board_text: str, minimum_mm: float) -> list[str]:
    """Report definite nominal sub-threshold round lands, never claim PASS.

    Other PTH pad/drill shapes, custom primitives and slots count as unmeasured
    and retain the mandatory written-CAM acceptance gate.
    """
    if not math.isfinite(minimum_mm) or minimum_mm <= 0:
        raise ValueError("PTH annular minimum must be finite and positive.")
    inspected, unmeasured = 0, 0
    below: list[str] = []
    below_by_reference: dict[str, int] = {}
    for footprint in _iter_blocks(board_text, "footprint"):
        reference = _REF.search(footprint)
        ref = reference.group(1) if reference else "unknown-reference"
        measured, unknown, footprint_failures = _inspect_footprint_round_pth(
            footprint, ref, minimum_mm
        )
        inspected += measured
        unmeasured += unknown
        below.extend(footprint_failures)
        if footprint_failures:
            below_by_reference[ref] = below_by_reference.get(ref, 0) + len(footprint_failures)
    lines = [f"- FAIL: JLCPCB nominal circular PTH {item}." for item in below[:20]]
    if len(below) > 20:
        lines.append(f"- FAIL: {len(below) - 20} more below-minimum nominal circular PTH pads.")
    if below_by_reference:
        count_summary = ", ".join(
            f"{ref}: {count}" for ref, count in sorted(below_by_reference.items())
        )
        lines.append(f"- WARN: Below-minimum nominal PTH counts by footprint: {count_summary}.")
    lines.append(
        f"- WARN: Partial source-board PTH preflight: {inspected} circular pads measured, "
        f"{unmeasured} unmeasured PTH shapes/plated slots; {len(below)} below the "
        f"published 2-layer/1-oz nominal threshold. No physical drill-registration, "
        f"copper-weight, soldermask or plating acceptance; written CAM signoff required."
    )
    return lines
