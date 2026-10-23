"""Fail-closed connector mating geometry, independent of KiCad GUI/IPC."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from kicad_mcp.models.intent import ConnectorMatingSpec, MechanicalConstraint
from kicad_mcp.tools.board_file import _parse_board_footprint_blocks
from kicad_mcp.tools.design_intent_state import ProjectDesignIntent
from kicad_mcp.tools.validation import _PlacementEvaluator

J1 = "Connector_USB:USB_C_Receptacle_GCT_USB4085"


def _board(rotation: int, x: float, y: float, *, rectangle: bool = True) -> str:
    outline = (
        "(gr_rect (start 0 0) (end 60 36) (stroke (width 0.05) (type default)) "
        '(fill no) (layer "Edge.Cuts"))'
        if rectangle
        else "(gr_circle (center 30 18) (end 55 18) "
        '(stroke (width 0.05) (type default)) (fill no) (layer "Edge.Cuts"))'
    )
    return (
        '(kicad_pcb (version 20250216) (generator "pytest") '
        + outline
        + f'(footprint "{J1}" (layer "F.Cu")\n\t\t(at {x} {y} {rotation}) '
        '(property "Reference" "J1" (at 0 0 0) (layer "F.SilkS")) '
        '(property "Value" "USB-C" (at 0 0 0) (layer "F.Fab")) '
        "(fp_rect (start -2.3 -1.1) (end 8.3 9.1) "
        '(stroke (width 0.05) (type solid)) (fill no) (layer "F.CrtYd")) '
        '(pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu" "F.Mask")))'
        ")"
    )


def _spec(**updates: object) -> ConnectorMatingSpec:
    data: dict[str, object] = {
        "ref": "J1",
        "footprint_id": J1,
        "edge": "left",
        "datum_x_mm": 2.975,
        "datum_y_mm": 6.1,
        "normal_local": "bottom",
        "max_datum_error_mm": 0.5,
    }
    data.update(updates)
    return ConnectorMatingSpec.model_validate(data)


def _analysis(angle: int, x: float, y: float, **updates: object):
    content = _board(angle, x, y, **updates)
    intent = ProjectDesignIntent(mechanical=MechanicalConstraint(connector_mating=[_spec()]))
    return _PlacementEvaluator(content, _parse_board_footprint_blocks(content), intent).evaluate()


def test_existing_j1_near_left_edge_but_wrong_direction_fails() -> None:
    report = _analysis(0, 2.75, 13.5)
    assert any(
        "J1" in problem and "mating direction" in problem for problem in report.hard_failures
    )
    assert any("J1" in problem and "datum" in problem for problem in report.hard_failures)


def test_aligned_j1_datum_and_mouth_direction_pass() -> None:
    report = _analysis(270, 6.1, 13.5)
    assert not [m for m in report.hard_failures if "mating" in m or "datum" in m]
    assert report.connector_edge_spec_violations == []


@pytest.mark.parametrize("rotation", [0, 90, 180])
def test_near_board_edge_is_not_proof_of_mating_direction(rotation: int) -> None:
    report = _analysis(rotation, 6.1, 13.5)
    assert any("mating direction" in msg for msg in report.hard_failures)


def test_missing_or_mismatched_footprint_identity_fails_closed() -> None:
    source = _board(270, 6.1, 13.5)
    entries = _parse_board_footprint_blocks(source)
    intent = ProjectDesignIntent(
        mechanical=MechanicalConstraint(connector_mating=[_spec(footprint_id="Other:USB")])
    )
    evaluation = _PlacementEvaluator(source, entries, intent).evaluate()
    assert any("footprint mismatch" in msg for msg in evaluation.hard_failures)


def test_non_rectangular_outline_cannot_fake_pass() -> None:
    report = _analysis(270, 6.1, 13.5, rectangle=False)
    assert any("rectangular Edge.Cuts" in msg for msg in report.hard_failures)


def test_missing_connector_fails_closed() -> None:
    content = _board(270, 6.1, 13.5)
    intent = ProjectDesignIntent(
        mechanical=MechanicalConstraint(connector_mating=[_spec(ref="J404")])
    )
    report = _PlacementEvaluator(content, _parse_board_footprint_blocks(content), intent).evaluate()
    assert any("J404" in msg and "missing" in msg for msg in report.hard_failures)


def test_legacy_mechanical_payload_round_trips() -> None:
    original = MechanicalConstraint(connector_placement=[{"ref": "J1", "edge": "left"}])
    restored = MechanicalConstraint.model_validate_json(original.model_dump_json())
    assert restored.connector_mating == []


def test_mating_spec_rejects_unknown_face_and_negative_tolerance() -> None:
    with pytest.raises(ValidationError):
        _spec(normal_local="upstream")
    with pytest.raises(ValidationError):
        _spec(max_datum_error_mm=-1)


def test_connector_mating_explicit_side_must_be_front_copper() -> None:
    content = _board(270, 6.1, 13.5)
    entries = _parse_board_footprint_blocks(content)
    entries["J1"]["layer_name"] = "B.Cu"
    intent = ProjectDesignIntent(mechanical=MechanicalConstraint(connector_mating=[_spec()]))
    report = _PlacementEvaluator(content, entries, intent).evaluate()
    assert any("front-copper footprint layer" in msg for msg in report.hard_failures)


def test_datum_on_edge_line_extension_is_not_valid() -> None:
    report = _analysis(270, 6.1, 38.0)
    assert any("outside the specified edge segment" in msg for msg in report.hard_failures)


def test_mating_contract_round_trips_without_unknown_fields() -> None:
    intent = ProjectDesignIntent(mechanical=MechanicalConstraint(connector_mating=[_spec()]))
    restored = ProjectDesignIntent.model_validate_json(intent.model_dump_json())
    assert restored.mechanical.connector_mating == [_spec()]


def test_mating_datum_uses_finite_edge_segment_distance_at_corners() -> None:
    # After the 270-degree rotation, the local datum offset is (-6.1, +2.975).
    # Thus (5.7, -3.375) locates the datum at (-0.4, -0.4). Separate
    # horizontal/vertical tolerance checks could both pass, but the actual
    # nearest segment distance is sqrt(0.4^2 + 0.4^2) > 0.5 mm.
    report = _analysis(270, 5.7, -3.375)
    assert any("mating datum is 0.566 mm" in msg for msg in report.hard_failures)


def test_mating_datum_within_finite_edge_tolerance_at_corner_passes() -> None:
    # Datum (0.3, -0.4) is 0.5 mm from left-edge endpoint (0, 0).
    report = _analysis(270, 6.4, -3.375)
    assert not any("mating datum is" in msg for msg in report.connector_edge_spec_violations)


@pytest.mark.parametrize(("width", "height"), [(0, 36), (60, 0), (0, 0)])
def test_degenerate_rectangular_edge_cuts_is_rejected(width: int, height: int) -> None:
    content = _board(270, 6.1, 13.5).replace(
        "(end 60 36) (stroke (width 0.05)",
        f"(end {width} {height}) (stroke (width 0.05)",
    )
    report = _PlacementEvaluator(
        content,
        _parse_board_footprint_blocks(content),
        ProjectDesignIntent(mechanical=MechanicalConstraint(connector_mating=[_spec()])),
    ).evaluate()
    assert any("rectangular Edge.Cuts" in msg for msg in report.hard_failures)


def test_missing_root_footprint_layer_never_passes_mating_acceptance() -> None:
    content = _board(270, 6.1, 13.5)
    root = f'(footprint "{J1}" (layer "F.Cu")'
    assert root in content
    content = content.replace(root, f'(footprint "{J1}"', 1)
    entries = _parse_board_footprint_blocks(content)
    assert entries["J1"]["layer_name"] == "F.Cu"  # historical fallback
    assert entries["J1"]["layer_name_explicit"] is False
    intent = ProjectDesignIntent(mechanical=MechanicalConstraint(connector_mating=[_spec()]))
    report = _PlacementEvaluator(content, entries, intent).evaluate()
    assert any("explicit front-copper" in msg for msg in report.hard_failures)


def test_nested_graphics_fcu_layer_does_not_spoof_root_footprint_layer() -> None:
    content = _board(270, 6.1, 13.5)
    root = f'(footprint "{J1}" (layer "F.Cu")'
    assert root in content
    content = content.replace(root, f'(footprint "{J1}"', 1)
    content = content.replace(
        '(pad "1" smd rect',
        '(fp_line (start 0 0) (end 2 0) (layer "F.Cu")) (pad "1" smd rect',
        1,
    )
    entries = _parse_board_footprint_blocks(content)
    assert entries["J1"]["layer_name_explicit"] is False
    intent = ProjectDesignIntent(mechanical=MechanicalConstraint(connector_mating=[_spec()]))
    report = _PlacementEvaluator(content, entries, intent).evaluate()
    assert any("explicit front-copper" in msg for msg in report.hard_failures)


def test_real_front_layer_parsing_remains_explicit() -> None:
    content = _board(270, 6.1, 13.5)
    entry = _parse_board_footprint_blocks(content)["J1"]
    assert entry["layer_name"] == "F.Cu"
    assert entry["layer_name_explicit"] is True


def test_mating_nominal_fit_fails_declared_worst_case_tolerance_budget() -> None:
    # Nominal J3-style datum 0.400 mm inboard would pass a 0.500-mm
    # threshold. A declared 0.100-mm part plus 0.200-mm profile tolerance
    # consumes an additional 0.300 mm of conservative worst-case margin.
    content = _board(270, 6.5, 13.5)
    entries = _parse_board_footprint_blocks(content)
    nominal = ProjectDesignIntent(mechanical=MechanicalConstraint(connector_mating=[_spec()]))
    budgeted = ProjectDesignIntent(
        mechanical=MechanicalConstraint(
            connector_mating=[
                _spec(
                    datum_component_tolerance_mm=0.1,
                    board_edge_tolerance_mm=0.2,
                )
            ]
        )
    )
    nominal_result = _PlacementEvaluator(content, entries, nominal).evaluate()
    budgeted_result = _PlacementEvaluator(content, entries, budgeted).evaluate()
    assert nominal_result.connector_edge_spec_violations == []
    assert any(
        "worst-case mating datum" in msg and "0.700 mm" in msg
        for msg in budgeted_result.hard_failures
    )


def test_declared_tolerance_budget_on_boundary_is_accepted() -> None:
    content = _board(270, 6.5, 13.5)
    intent = ProjectDesignIntent(
        mechanical=MechanicalConstraint(
            connector_mating=[_spec(datum_component_tolerance_mm=0.1, board_edge_tolerance_mm=0.0)]
        )
    )
    report = _PlacementEvaluator(content, _parse_board_footprint_blocks(content), intent).evaluate()
    assert report.connector_edge_spec_violations == []


@pytest.mark.parametrize(
    "missing_field", ["datum_component_tolerance_mm", "board_edge_tolerance_mm"]
)
def test_partially_declared_tolerance_budget_fails_closed(missing_field: str) -> None:
    data: dict[str, object] = {
        "datum_component_tolerance_mm": 0.1,
        "board_edge_tolerance_mm": 0.2,
    }
    del data[missing_field]
    content = _board(270, 6.5, 13.5)
    intent = ProjectDesignIntent(mechanical=MechanicalConstraint(connector_mating=[_spec(**data)]))
    report = _PlacementEvaluator(content, _parse_board_footprint_blocks(content), intent).evaluate()
    assert any("incomplete mating tolerance budget" in m for m in report.hard_failures)


@pytest.mark.parametrize("invalid", [-0.1, float("nan"), float("inf")])
def test_mating_tolerance_budget_rejects_bad_numbers(invalid: float) -> None:
    with pytest.raises(ValidationError):
        _spec(datum_component_tolerance_mm=invalid)
    with pytest.raises(ValidationError):
        _spec(board_edge_tolerance_mm=invalid)
