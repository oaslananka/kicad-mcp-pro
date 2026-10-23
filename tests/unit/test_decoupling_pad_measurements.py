"""Issue #1380: decoupling proximity must not confuse footprint centers with copper pins."""

from __future__ import annotations

import pytest

from kicad_mcp.tools.board_file import _parse_board_footprint_blocks
from kicad_mcp.tools.design_intent_state import ProjectDesignIntent
from kicad_mcp.tools.validation import _PlacementEvaluator


def _footprint(
    ref: str,
    x: float,
    y: float,
    rotation: int,
    pads: list[tuple[str, float, float, str]],
    *,
    layer: str = "F.Cu",
) -> str:
    pad_text = "".join(
        f'(pad "{number}" smd rect (at {px} {py}) (size 1 1) (layers "{layer}") (net 1 "{net}"))'
        for number, px, py, net in pads
    )
    return chr(10).join(
        [
            f'(footprint "Test:{ref}"',
            f' (layer "{layer}")',
            f" (at {x} {y} {rotation})",
            f' (property "Reference" "{ref}" (at 0 0 0))',
            ' (property "Value" "test" (at 0 0 0))',
            pad_text,
            ")",
        ]
    )


def _evaluate(footprints: str, *, caps: list[str] | None = None, limit: float = 3.0):
    board = (
        "(kicad_pcb (version 20250216)"
        '(gr_rect (start 0 0) (end 80 40) (layer "Edge.Cuts"))' + footprints + ")"
    )
    entries = _parse_board_footprint_blocks(board)
    intent = ProjectDesignIntent(
        decoupling_pairs=[{"ic_ref": "U1", "cap_refs": caps or ["C1"], "max_distance_mm": limit}]
    )
    return _PlacementEvaluator(board, entries, intent).evaluate(), entries


def test_measured_rotated_power_pads_pass_even_with_far_footprint_centers() -> None:
    # U1 origin (10,20) has power pin at local +5; rotated 90deg -> (10,15).
    # C1 origin (10,10), power pad local +5 -> (10,15). Their copper pad centers
    # coincide despite a 10mm center-to-center spacing.
    footprints = _footprint("U1", 10, 20, 90, [("1", 5, 0, "/3V3")])
    footprints += _footprint("C1", 10, 10, 0, [("1", 0, 5, "3V3")])
    report, entries = _evaluate(footprints)
    assert entries["U1"]["pad_positions_mm"][0]["x_mm"] == pytest.approx(10)
    assert entries["U1"]["pad_positions_mm"][0]["y_mm"] == pytest.approx(15)
    assert report.hard_failures == []
    assert not any("decoupling" in warning for warning in report.warnings)


def test_power_pad_separation_warns_without_claiming_measured_trace_length() -> None:
    footprints = _footprint("U1", 10, 10, 0, [("1", 0, 0, "/3V3")])
    footprints += _footprint("C1", 15, 10, 0, [("1", 0, 0, "3V3")])
    report, _ = _evaluate(footprints)
    assert report.hard_failures == []
    assert any(
        "same-supply-net power-pad" in warning and "5.00 mm" in warning
        for warning in report.warnings
    )
    assert any("copper path" in warning for warning in report.warnings)


def test_nearby_ground_only_pads_do_not_fake_good_decoupling() -> None:
    footprints = _footprint("U1", 10, 10, 0, [("1", 0, 0, "GND"), ("2", 0, 3, "/3V3")])
    footprints += _footprint("C1", 10, 11, 0, [("1", 0, 0, "GND"), ("2", 0, 10, "3V3")])
    report, _ = _evaluate(footprints)
    # Physical overlap is a separate legitimate placement hard failure.
    assert any("same-supply-net power-pad" in warning for warning in report.warnings)


def test_missing_capacitor_remains_hard_failure() -> None:
    footprints = _footprint("U1", 10, 10, 0, [("1", 0, 0, "3V3")])
    report, _ = _evaluate(footprints, caps=["C404"])
    assert any(
        "missing or unresolved decoupling caps" in failure for failure in report.hard_failures
    )


def test_back_layer_unsupported_pad_transform_is_not_misreported_as_physical_proof() -> None:
    footprints = _footprint("U1", 10, 10, 0, [("1", 0, 0, "3V3")], layer="B.Cu")
    footprints += _footprint("C1", 30, 10, 0, [("1", 0, 0, "3V3")])
    report, entries = _evaluate(footprints)
    assert entries["U1"]["pad_positions_mm"] == []
    assert report.hard_failures == []
    assert any("footprint-center proxy" in warning for warning in report.warnings)


def test_data_net_matching_does_not_qualify_as_supply_decoupling() -> None:
    footprints = _footprint("U1", 10, 10, 0, [("1", 0, 0, "USB_DP")])
    footprints += _footprint("C1", 30, 10, 0, [("1", 0, 0, "USB_DP")])
    report, _ = _evaluate(footprints)
    assert report.hard_failures == []
    assert any("footprint-center proxy" in warning for warning in report.warnings)
    assert not any("same-supply-net" in warning for warning in report.warnings)


@pytest.mark.parametrize("rail", ["5V", "12V", "5V0", "+3V3"])
def test_named_voltage_rail_is_measured_as_supply_pad(rail: str) -> None:
    footprints = _footprint("U1", 10, 10, 0, [("1", 0, 0, rail)])
    footprints += _footprint("C1", 30, 10, 0, [("1", 0, 0, rail)])
    report, _ = _evaluate(footprints)
    assert report.hard_failures == []
    assert any("same-supply-net power-pad" in warning for warning in report.warnings)
    assert not any("footprint-center proxy" in warning for warning in report.warnings)


def test_vref_enable_is_not_treated_as_decoupling_supply() -> None:
    footprints = _footprint("U1", 10, 10, 0, [("1", 0, 0, "VREF_EN")])
    footprints += _footprint("C1", 30, 10, 0, [("1", 0, 0, "VREF_EN")])
    report, _ = _evaluate(footprints)
    assert report.hard_failures == []
    assert any("footprint-center proxy" in warning for warning in report.warnings)


def test_missing_qualified_pad_measurement_warns_even_when_centers_are_near() -> None:
    footprints = _footprint("U1", 10, 10, 0, [("1", 0, 0, "USB_DP")])
    footprints += _footprint("C1", 11, 10, 0, [("1", 0, 0, "USB_DP")])
    report, _ = _evaluate(footprints)
    assert any("footprint-center proxy" in warning for warning in report.warnings)
