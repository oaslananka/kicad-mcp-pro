"""Unit tests for connector mechanical acceptance and mating orientation review (#1393, T6)."""

from __future__ import annotations

from typing import Any

from kicad_mcp.models.intent import ConnectorMatingSpec
from kicad_mcp.models.review import (
    AssessmentStatus,
    EvaluationMethod,
    ReviewAssessment,
    ReviewContext,
)
from kicad_mcp.review.mechanical_acceptance import (
    evaluate_connector_mating_orientation,
    evaluate_mechanical_stage_gate,
)

USB4085_FP = "Connector_USB:USB_C_Receptacle_GCT_USB4085"

BOARD_FRAME = (0.0, 0.0, 60.0, 36.0)


def _usb_spec(**updates: object) -> ConnectorMatingSpec:
    data: dict[str, Any] = {
        "ref": "J1",
        "footprint_id": USB4085_FP,
        "edge": "left",
        "datum_x_mm": 2.975,
        "datum_y_mm": 6.1,
        "normal_local": "bottom",
        "max_datum_error_mm": 0.5,
        "max_direction_error_deg": 5.0,
    }
    data.update(updates)
    return ConnectorMatingSpec.model_validate(data)


def test_unannotated_connector_fails_closed() -> None:
    """Proves fail-closed behaviour: connector footprint without mechanical spec yields FAIL."""
    context = ReviewContext(project_name="unannotated_connector")
    footprints = {
        "J1": {
            "name": USB4085_FP,
            "x_mm": 2.75,
            "y_mm": 13.5,
            "rotation": 0.0,
            "layer_name": "F.Cu",
            "layer_name_explicit": True,
        }
    }

    assessment = evaluate_connector_mating_orientation(
        context,
        footprints=footprints,
        frame=BOARD_FRAME,
        specs=[],
    )

    assert assessment.status == AssessmentStatus.FAIL
    assert len(assessment.findings) == 1
    finding = assessment.findings[0]
    assert finding.object_ref == "J1"
    assert "lacks declared mechanical mating intent" in finding.description
    assert finding.severity == "error"


def test_usb4085_wrong_mating_direction_fails() -> None:
    """Proves Issue #1393 reproduction: USB4085 near left edge with wrong angle fails."""
    context = ReviewContext(project_name="wrong_direction", has_3d_models=True)
    footprints = {
        "J1": {
            "name": USB4085_FP,
            "x_mm": 2.75,
            "y_mm": 13.5,
            "rotation": 0.0,  # 0 deg points inward/orthogonal instead of outward to left edge
            "layer_name": "F.Cu",
            "layer_name_explicit": True,
        }
    }

    assessment = evaluate_connector_mating_orientation(
        context,
        footprints=footprints,
        frame=BOARD_FRAME,
        specs=[_usb_spec()],
    )

    assert assessment.status == AssessmentStatus.FAIL
    direction_errors = [
        f for f in assessment.findings if "mating direction points" in f.description
    ]
    assert len(direction_errors) >= 1
    assert direction_errors[0].severity == "error"


def test_usb4085_valid_mating_orientation_passes() -> None:
    """Proves that a correctly rotated USB4085 (270 deg) facing left Edge.Cuts passes."""
    context = ReviewContext(project_name="valid_connector", has_3d_models=True)
    # Rotation 270: local bottom normal (-y) maps to board (-x) matching left edge normal
    footprints = {
        "J1": {
            "name": USB4085_FP,
            "x_mm": 6.1,
            "y_mm": 13.5,
            "rotation": 270.0,
            "layer_name": "F.Cu",
            "layer_name_explicit": True,
        }
    }

    assessment = evaluate_connector_mating_orientation(
        context,
        footprints=footprints,
        frame=BOARD_FRAME,
        specs=[_usb_spec()],
    )

    assert assessment.status == AssessmentStatus.PASS
    assert len(assessment.findings) == 0


def test_missing_3d_model_warns_swept_volume() -> None:
    """Proves missing 3-D model generates swept volume warning with nominal 2-D alignment."""
    context = ReviewContext(project_name="no_3d_model", has_3d_models=False)
    footprints = {
        "J1": {
            "name": USB4085_FP,
            "x_mm": 6.1,
            "y_mm": 13.5,
            "rotation": 270.0,
            "layer_name": "F.Cu",
            "layer_name_explicit": True,
        }
    }

    assessment = evaluate_connector_mating_orientation(
        context,
        footprints=footprints,
        frame=BOARD_FRAME,
        specs=[_usb_spec()],
    )

    assert assessment.status == AssessmentStatus.WARN
    assert any("3D model is unavailable" in f.description for f in assessment.findings)


def test_non_rectangular_board_fails_closed() -> None:
    """Mechanical intent requires verified rectangular outline; circular boards fail closed."""
    context = ReviewContext(project_name="circular_board", has_3d_models=True)
    footprints = {
        "J1": {
            "name": USB4085_FP,
            "x_mm": 6.1,
            "y_mm": 13.5,
            "rotation": 90.0,
            "layer_name": "F.Cu",
            "layer_name_explicit": True,
        }
    }

    assessment = evaluate_connector_mating_orientation(
        context,
        footprints=footprints,
        frame=BOARD_FRAME,
        specs=[_usb_spec()],
        rectangular_outline_verified=False,
    )

    assert assessment.status == AssessmentStatus.FAIL
    assert any(
        "rectangular Edge.Cuts outline is required" in f.description for f in assessment.findings
    )


def test_no_connectors_on_board_not_applicable() -> None:
    """Board with only passive components evaluates to NOT_APPLICABLE."""
    context = ReviewContext(project_name="passive_board")
    footprints = {
        "R1": {"name": "Resistor_SMD:R_0805", "x_mm": 10.0, "y_mm": 10.0},
        "C1": {"name": "Capacitor_SMD:C_0603", "x_mm": 20.0, "y_mm": 10.0},
    }

    assessment = evaluate_connector_mating_orientation(
        context,
        footprints=footprints,
        frame=BOARD_FRAME,
        specs=[],
    )

    assert assessment.status == AssessmentStatus.NOT_APPLICABLE
    assert assessment.metadata.get("connector_count") == 0


def test_electrical_pass_does_not_override_mechanical_fail() -> None:
    """Crucial contract: ERC/DRC electrical PASS cannot override mechanical connector FAIL."""
    context = ReviewContext(project_name="gate_test", has_3d_models=True)
    footprints = {
        "J1": {
            "name": USB4085_FP,
            "x_mm": 2.75,
            "y_mm": 13.5,
            "rotation": 0.0,
            "layer_name": "F.Cu",
            "layer_name_explicit": True,
        }
    }

    # Mechanical assessment FAILS
    mechanical_eval = evaluate_connector_mating_orientation(
        context,
        footprints=footprints,
        frame=BOARD_FRAME,
        specs=[_usb_spec()],
    )
    assert mechanical_eval.status == AssessmentStatus.FAIL

    # Mocked electrical assessment PASSES
    electrical_eval = ReviewAssessment(
        rule_id="drc.clearance",
        status=AssessmentStatus.PASS,
        method=EvaluationMethod.NATIVE,
        summary="All electrical DRC rules passed with 0 violations.",
    )

    gate_decision = evaluate_mechanical_stage_gate(mechanical_eval, electrical_eval)

    assert gate_decision.approved is False
    assert "Electrical PASS cannot override mechanical failure" in gate_decision.summary
