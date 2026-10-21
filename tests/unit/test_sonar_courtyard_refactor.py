"""Preserve KiCad courtyard geometry semantics across helper extraction."""

from __future__ import annotations

from typing import Any

import pytest

from kicad_mcp.tools.board_file import _absolute_courtyard_bounds_mm
from kicad_mcp.tools.validation import _PlacementEvaluator


@pytest.mark.parametrize(
    ("geometry", "expected"),
    [
        (
            '(fp_circle (center 1 2) (end 4 2) (layer "F.CrtYd"))',
            (8.0, 19.0, 14.0, 25.0),
        ),
        (
            '(fp_line (start 0 0) (end 2 2) (layer "B.CrtYd"))',
            (10.0, 20.0, 12.0, 22.0),
        ),
        (
            '(fp_rect (start -1 -2) (end 3 4) (layer "F.CrtYd"))',
            (9.0, 18.0, 13.0, 24.0),
        ),
        (
            '(fp_rect (start -1 -2) (end 3 4) (layer "F.SilkS"))',
            None,
        ),
        (
            '(fp_circle (end 4 2) (layer "F.CrtYd"))',
            None,
        ),
        (
            '(fp_arc (start 0 0) (end 2 2) (layer "B.CrtYd"))',
            None,
        ),
        (
            '(fp_poly (pts (xy 0 0) (xy 2 2)) (layer "F.CrtYd"))',
            None,
        ),
    ],
)
def test_courtyard_shape_still_uses_conservative_fallback(
    geometry: str,
    expected: tuple[float, float, float, float] | None,
) -> None:
    assert _absolute_courtyard_bounds_mm(f"(footprint {geometry})", (10, 20, 0)) == expected


def test_courtyard_unknown_root_still_defers_to_fallback() -> None:
    body = '(fp_rect (start 1 1) (end 2 2) (layer "F.CrtYd"))'
    assert _absolute_courtyard_bounds_mm(body, None) is None


def test_courtyard_rotation_180_preserves_offset() -> None:
    body = '(fp_rect (start 1 2) (end 3 4) (layer "F.CrtYd"))'
    assert _absolute_courtyard_bounds_mm(body, (10, 20, 180)) == (7.0, 16.0, 9.0, 18.0)


def _footprint(
    bbox: tuple[float, float, float, float] | None,
    *,
    name: str = "Package:Test",
    xy: tuple[float, float] | None = None,
) -> dict[str, Any]:
    if bbox is None:
        return {
            "name": name,
            "x_mm": None,
            "y_mm": None,
            "width_mm": 2,
            "height_mm": 2,
            "courtyard_bounds_mm": None,
        }
    x0, y0, x1, y1 = bbox
    return {
        "name": name,
        "x_mm": (x0 + x1) / 2 if xy is None else xy[0],
        "y_mm": (y0 + y1) / 2 if xy is None else xy[1],
        "width_mm": x1 - x0,
        "height_mm": y1 - y0,
        "courtyard_bounds_mm": bbox,
    }


def _evaluate(
    footprints: dict[str, dict[str, Any]],
) -> tuple[tuple[list[str], list[str], list[str]], list[str]]:
    evaluator = _PlacementEvaluator.__new__(_PlacementEvaluator)
    evaluator.footprints = footprints
    evaluator.min_x = evaluator.min_y = 0
    evaluator.max_x = evaluator.max_y = 20
    evaluator.warnings = []
    return evaluator._evaluate_geometry_and_overlaps(), evaluator.warnings


def test_courtyard_overlap_reports_sorted_pairs_only_once() -> None:
    result, warnings = _evaluate(
        {
            "U3": _footprint((3, 3, 6, 6)),
            "R1": _footprint((5, 5, 8, 8)),
            "U2": _footprint((10, 10, 12, 12)),
        }
    )
    assert result == ([], ["R1/U3"], [])
    assert warnings == []


def test_touching_edges_are_not_courtyard_overlaps() -> None:
    result, warnings = _evaluate(
        {
            "U1": _footprint((1, 1, 5, 5)),
            "R1": _footprint((5, 1, 7, 5)),
        }
    )
    assert result == ([], [], [])
    assert warnings == []


def test_absent_position_is_reported_but_not_compared() -> None:
    result, warnings = _evaluate({"U1": _footprint(None), "R1": _footprint((1, 1, 3, 3))})
    assert result == (["U1"], [], [])
    assert warnings == []


def test_connector_outside_bounds_warns_without_fabrication_failure() -> None:
    result, warnings = _evaluate({"J2": _footprint((17, 5, 25, 8), name="TerminalBlock:Test")})
    assert result == ([], [], [])
    assert len(warnings) == 1
    assert "J2" in warnings[0]


def test_unknown_courtyard_fallback_uses_footprint_center() -> None:
    entry = _footprint((6, 6, 10, 10), xy=(8, 8))
    entry["courtyard_bounds_mm"] = None
    result, warnings = _evaluate({"U5": entry})
    assert result == ([], [], [])
    assert warnings == []


def test_nonconnector_outside_is_hard_error() -> None:
    result, warnings = _evaluate({"R7": _footprint((19, 5, 24, 7))})
    assert result == ([], [], ["R7"])
    assert warnings == []
