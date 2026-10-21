"""Courtyard geometry is positioned from the pad origin, not box-centred there."""

from kicad_mcp.tools.board_file import _absolute_courtyard_bounds_mm
from kicad_mcp.tools.validation import _PlacementEvaluator


def _footprint(
    bbox: tuple[float, float, float, float],
    *,
    name: str = "Package_SMD:Test",
) -> dict[str, object]:
    x0, y0, x1, y1 = bbox
    return {
        "name": name,
        "x_mm": (x0 + x1) / 2,
        "y_mm": (y0 + y1) / 2,
        "width_mm": x1 - x0,
        "height_mm": y1 - y0,
        "courtyard_bounds_mm": bbox,
    }


def _evaluate(footprints: dict[str, dict[str, object]]):
    evaluator = _PlacementEvaluator.__new__(_PlacementEvaluator)
    evaluator.footprints = footprints
    evaluator.min_x, evaluator.min_y = 0.0, 0.0
    evaluator.max_x, evaluator.max_y = 20.0, 20.0
    evaluator.warnings = []
    result = evaluator._evaluate_geometry_and_overlaps()
    return result, evaluator.warnings


def test_unrotated_offset_courtyard_not_centered_on_pin_one() -> None:
    body = """
    (footprint "TerminalBlock:Test"
      (at 10 10)
      (fp_rect
        (start -3.04 -5.71)
        (end 13.21 5.1)
        (layer "F.CrtYd"))
    )"""
    assert _absolute_courtyard_bounds_mm(body, (10, 10, 0)) == (6.96, 4.29, 23.21, 15.1)


def test_rotated_courtyard_uses_board_coordinate_transform() -> None:
    body = """
    (footprint "Connector:Test"
      (at 100 200 90)
      (fp_rect
        (start -2 -1)
        (end 3 4)
        (layer "F.CrtYd"))
    )"""
    assert _absolute_courtyard_bounds_mm(body, (100, 200, 90)) == (99.0, 197.0, 104.0, 202.0)


def test_unrelated_silkscreen_does_not_enlarge_courtyard_bbox() -> None:
    body = """
    (footprint "Package:Test"
      (at 5 5)
      (fp_rect (start -1 -1) (end 1 1) (layer "F.CrtYd"))
      (fp_line (start 50 50) (end 55 55) (layer "F.SilkS"))
    )"""
    assert _absolute_courtyard_bounds_mm(body, (5, 5, 0)) == (4.0, 4.0, 6.0, 6.0)


def test_unsupported_courtyard_primitive_falls_back() -> None:
    body = '(footprint "Package:Test" (fp_arc (start 0 0) (mid 1 1) (end 2 0) (layer "F.CrtYd")))'
    assert _absolute_courtyard_bounds_mm(body, (5, 5, 0)) is None


def test_actual_offset_boxes_do_not_report_false_overlap() -> None:
    result, warnings = _evaluate(
        {
            "J1": _footprint((12, 6, 19, 9), name="Connector_USB:Test"),
            "U2": _footprint((3, 6, 10, 9)),
            "R11": _footprint((12, 12, 15, 14)),
        }
    )
    assert result == ([], [], [])
    assert warnings == []


def test_connector_overhang_is_review_warning_not_automatic_fabrication_failure() -> None:
    result, warnings = _evaluate({"J1": _footprint((18, 6, 23, 10), name="Connector_USB:Test")})
    assert result == ([], [], [])
    assert len(warnings) == 1
    assert "J1" in warnings[0]
    assert "overhang" in warnings[0]


def test_non_connector_outside_board_remains_a_hard_failure() -> None:
    result, warnings = _evaluate({"U2": _footprint((18, 6, 23, 10))})
    assert result == ([], [], ["U2"])
    assert warnings == []


def test_true_courtyard_overlap_remains_a_hard_failure() -> None:
    result, _ = _evaluate({"U2": _footprint((3, 3, 8, 8)), "R1": _footprint((7, 7, 9, 9))})
    assert result == ([], ["R1/U2"], [])
