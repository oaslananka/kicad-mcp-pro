"""Conservative source-board PTH ring preflight, not manufacturer clearance."""

from __future__ import annotations

import pytest

from kicad_mcp.tools.pth_annular_audit import audit_pth_annular_ring_lines


def _board(*pads: str) -> str:
    return (
        "(kicad_pcb (version 20250216) "
        '(footprint "Connector:Test" (layer "F.Cu") '
        '(property "Reference" "J1") ' + " ".join(pads) + "))"
    )


def _round(number: str, copper: float, drill: float) -> str:
    return (
        f'(pad "{number}" thru_hole circle (at 0 0) '
        f'(size {copper} {copper}) (drill {drill}) (layers "*.Cu" "*.Mask"))'
    )


def test_known_round_pth_below_jlcpcb_threshold_is_explicit_fail() -> None:
    lines = audit_pth_annular_ring_lines(_board(_round("A1", 0.65, 0.4)), 0.18)
    assert any(
        line.startswith("- FAIL:") and "J1 pad A1" in line and "0.125 mm" in line for line in lines
    )
    assert any("1 circular" in line and "0 unmeasured" in line for line in lines)
    assert not any(line.startswith("- PASS:") for line in lines)


def test_larger_round_pth_has_only_unqualified_warning() -> None:
    lines = audit_pth_annular_ring_lines(_board(_round("1", 0.9, 0.4)), 0.18)
    assert not any(line.startswith("- FAIL:") or line.startswith("- PASS:") for line in lines)
    assert any("1 circular" in line and "written CAM" in line for line in lines)


def test_unsupported_plated_oval_slot_and_smd_are_not_measured_as_round() -> None:
    slot = '(pad "2" thru_hole oval (size 1 2) (drill oval 0.6 1.2))'
    smd = '(pad "3" smd circle (size 0.4 0.4) (layers "F.Cu"))'
    lines = audit_pth_annular_ring_lines(_board(_round("1", 0.9, 0.4), slot, smd), 0.18)
    assert any("1 circular" in line and "1 unmeasured" in line for line in lines)
    assert any("plated slots" in line for line in lines)
    assert not any(line.startswith("- PASS:") for line in lines)


def test_missing_pad_drill_and_malformed_geometry_fail_closed_as_unmeasured() -> None:
    pads = [
        '(pad "1" thru_hole circle (size 0.65 0.65))',
        '(pad "2" thru_hole circle (size 0.65 0.65) (drill oval 0.4 0.4))',
        '(pad "3" thru_hole circle (size 0.65 0.7) (drill 0.4))',
        '(pad "4" thru_hole circle (size 0.65 0.65) (drill 0.0))',
    ]
    lines = audit_pth_annular_ring_lines(_board(*pads), 0.18)
    assert any("0 circular" in line and "4 unmeasured" in line for line in lines)
    assert not any(line.startswith("- PASS:") for line in lines)


def test_unsupported_without_any_round_pad_still_warns() -> None:
    assert any("0 circular" in line for line in audit_pth_annular_ring_lines(_board(), 0.18))


@pytest.mark.parametrize("invalid", [0.0, -0.2, float("nan"), float("inf")])
def test_invalid_minimum_is_not_accepted(invalid: float) -> None:
    board = _board(_round("1", 0.65, 0.4))
    with pytest.raises(ValueError):
        audit_pth_annular_ring_lines(board, invalid)


def test_more_than_twenty_violating_pads_are_bounded_with_total_count() -> None:
    lines = audit_pth_annular_ring_lines(
        _board(*(_round(str(n), 0.65, 0.4) for n in range(23))), 0.18
    )
    assert sum(line.startswith("- FAIL:") for line in lines) == 21
    assert any("3 more below-minimum" in line for line in lines)
    assert any("23 below" in line for line in lines)
    assert any("J1: 23" in line for line in lines)


def test_unidentified_footprint_reference_is_explicitly_unknown() -> None:
    board = '(kicad_pcb (footprint "Test" ' + _round("1", 0.65, 0.4) + "))"
    lines = audit_pth_annular_ring_lines(board, 0.18)
    assert any("unknown-reference pad 1" in line for line in lines)


def test_hole_at_or_above_pad_diameter_is_definite_nominal_fail() -> None:
    lines = audit_pth_annular_ring_lines(
        _board(_round("equal", 0.65, 0.65), _round("larger", 0.65, 0.7)), 0.18
    )
    assert any("J1 pad equal: nominal ring 0.000 mm" in line for line in lines)
    assert any("J1 pad larger: nominal ring -0.025 mm" in line for line in lines)
    assert any("2 circular pads measured" in line and "2 below" in line for line in lines)


def test_threshold_precision_does_not_print_apparent_equal_comparison() -> None:
    # Nominal ring 0.1799 is strictly less than 0.180, despite identical
    # three-decimal representations.
    lines = audit_pth_annular_ring_lines(_board(_round("1", 0.7598, 0.4)), 0.18)
    assert any("0.1799000 mm < 0.1800000 mm" in line for line in lines)
    assert not any("0.180 mm < 0.180 mm" in line for line in lines)


def test_offset_round_drill_reduces_nominal_minimum_ring_to_fail() -> None:
    # 0.9/0.4 centered ring=0.250, but a 0.080-mm hole offset
    # leaves 0.170 mm at the thinnest copper edge.
    pad = (
        '(pad "off" thru_hole circle (size 0.9 0.9) '
        '(drill 0.4 (offset 0.08 0)) (layers "*.Cu" "*.Mask"))'
    )
    lines = audit_pth_annular_ring_lines(_board(pad), 0.18)
    assert any(
        line.startswith("- FAIL:") and "J1 pad off" in line and "0.170 mm" in line for line in lines
    )
    assert any("1 circular pads measured" in line and "0 unmeasured" in line for line in lines)


@pytest.mark.parametrize("offset", ["0.07 0.07", "-0.07 0.07", "0.07 -0.07"])
def test_diagonal_and_negative_round_drill_offset_use_vector_length(offset: str) -> None:
    pad = (
        '(pad "diag" thru_hole circle (size 0.9 0.9) '
        f'(drill 0.4 (offset {offset})) (layers "*.Cu" "*.Mask"))'
    )
    lines = audit_pth_annular_ring_lines(_board(pad), 0.18)
    assert any("J1 pad diag" in line and "nominal ring 0.151 mm" in line for line in lines)


def test_centered_and_zero_offset_ring_are_equivalent() -> None:
    shifted = (
        '(pad "zero" thru_hole circle (size 0.9 0.9) '
        '(drill 0.4 (offset 0 0)) (layers "*.Cu" "*.Mask"))'
    )
    lines = audit_pth_annular_ring_lines(_board(shifted), 0.18)
    assert not any(line.startswith("- FAIL:") for line in lines)
    assert any("1 circular pads measured" in line for line in lines)


@pytest.mark.parametrize(
    "drill",
    [
        "(drill 0.4 (offset 0.1))",
        "(drill 0.4 (offset who 0))",
        "(drill 0.4 (offset 0.1 0) (unknown feature))",
        "(drill oval 0.4 0.6 (offset 0.1 0))",
    ],
)
def test_unrecognized_round_hole_offsets_remain_unmeasured(drill: str) -> None:
    pad = f'(pad "unknown" thru_hole circle (size 0.9 0.9) {drill})'
    lines = audit_pth_annular_ring_lines(_board(pad), 0.18)
    assert any("0 circular pads measured, 1 unmeasured" in line for line in lines)
    assert not any(line.startswith("- PASS:") for line in lines)
