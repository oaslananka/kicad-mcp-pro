"""Unit tests for critical placement pin and net connectivity (#1582, T4).

Verifies:
- Nearby wrong-rail capacitor cannot receive electrical PASS.
- Farther correct-rail capacitor measures actual pin-to-pin distance.
- Unresolved power pin returns NOT_ASSESSED; footprint center is never substituted.
- Distinct ground nets (AGND vs DGND) prevent claiming verified ground return.
- Unsupported backside transform returns NOT_ASSESSED.
- Crystal placement matches companion MCU via declared oscillator topology, not nearest reference.
- Open/unconnected crystal companion returns FAIL.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from kicad_mcp.models.placement_topology import (
    PlacementBoardTopology,
    PlacementComponentTopology,
    PlacementPinTopology,
)
from kicad_mcp.models.review import (
    AssessmentStatus,
    ReviewContext,
)
from kicad_mcp.models.signal_integrity import DecouplingPlacementInput
from kicad_mcp.review.placement_connectivity import (
    evaluate_crystal_placement,
    evaluate_decoupling_connectivity,
)
from kicad_mcp.signal_integrity.decoupling_placement import (
    SignalIntegrityDecouplingPlacementService,
)
from kicad_mcp.tools import emc_compliance as emc


def test_nearby_wrong_rail_capacitor_fails_critical_placement() -> None:
    # U1 at (10, 10) with +3.3V power pin 1 at (10, 12)
    # C1 is 0.5mm away at (10, 12.5), BUT on +12V rail (wrong rail)
    u1 = PlacementComponentTopology(
        reference="U1",
        component_type="ic",
        location_mm=(10.0, 10.0),
        pins=[
            PlacementPinTopology(
                pin_number="1",
                net_name="+3.3V",
                pin_type="power_input",
                location_mm=(10.0, 12.0),
            ),
            PlacementPinTopology(
                pin_number="2",
                net_name="GND",
                pin_type="ground",
                location_mm=(10.0, 8.0),
            ),
        ],
    )
    c1_wrong = PlacementComponentTopology(
        reference="C1",
        component_type="capacitor",
        location_mm=(10.0, 12.5),
        pins=[
            PlacementPinTopology(
                pin_number="1",
                net_name="+12V",
                pin_type="passive",
                location_mm=(10.0, 12.5),
            ),
            PlacementPinTopology(
                pin_number="2",
                net_name="GND",
                pin_type="ground",
                location_mm=(10.0, 13.5),
            ),
        ],
    )

    topology = PlacementBoardTopology(
        components={"U1": u1, "C1": c1_wrong},
        has_ground_plane=True,
    )
    context = ReviewContext(project_name="PowerDomainBoard")

    assessment = evaluate_decoupling_connectivity(
        context,
        topology,
        target_ic="U1",
        max_distance_mm=3.0,
    )

    # Nearby wrong-rail cap must NOT pass!
    assert assessment.status == AssessmentStatus.FAIL
    assert len(assessment.findings) == 1
    finding = assessment.findings[0]
    assert "+3.3V" in finding.description
    assert "wrong rail '+12V'" in finding.description or "No same-rail" in finding.description


def test_farther_correct_rail_capacitor_satisfies_decoupling() -> None:
    # U1 at (10, 10) with +3.3V power pin 1 at (10, 12)
    # C1 (wrong rail +12V) is 0.5 mm away
    # C2 (correct rail +3.3V) is 2.0 mm away at (10, 14)
    u1 = PlacementComponentTopology(
        reference="U1",
        component_type="ic",
        location_mm=(10.0, 10.0),
        pins=[
            PlacementPinTopology(
                pin_number="1",
                net_name="+3.3V",
                pin_type="power_input",
                location_mm=(10.0, 12.0),
            ),
            PlacementPinTopology(
                pin_number="2",
                net_name="GND",
                pin_type="ground",
                location_mm=(10.0, 8.0),
            ),
        ],
    )
    c1_wrong = PlacementComponentTopology(
        reference="C1",
        component_type="capacitor",
        location_mm=(10.0, 12.5),
        pins=[
            PlacementPinTopology(pin_number="1", net_name="+12V", location_mm=(10.0, 12.5)),
            PlacementPinTopology(pin_number="2", net_name="GND", location_mm=(10.0, 13.5)),
        ],
    )
    c2_correct = PlacementComponentTopology(
        reference="C2",
        component_type="capacitor",
        location_mm=(10.0, 14.0),
        pins=[
            PlacementPinTopology(pin_number="1", net_name="+3.3V", location_mm=(10.0, 14.0)),
            PlacementPinTopology(pin_number="2", net_name="GND", location_mm=(10.0, 15.0)),
        ],
    )

    topology = PlacementBoardTopology(
        components={"U1": u1, "C1": c1_wrong, "C2": c2_correct},
        has_ground_plane=True,
    )
    context = ReviewContext(project_name="TwoCapBoard")

    assessment = evaluate_decoupling_connectivity(
        context,
        topology,
        target_ic="U1",
        max_distance_mm=3.0,
    )

    # C2 on +3.3V is within 3.0 mm (2.0 mm) -> passes!
    assert assessment.status == AssessmentStatus.PASS
    assert assessment.findings == []
    assert assessment.metadata["passed_pins"] == 1


@pytest.mark.parametrize(
    ("ic_ground", "cap_ground", "has_ground_plane", "expected_status"),
    [
        ("AGND", "DGND", True, AssessmentStatus.NOT_ASSESSED),
        ("GND", "GND", False, AssessmentStatus.NOT_ASSESSED),
        ("GND", "GND", True, AssessmentStatus.PASS),
    ],
)
def test_same_rail_nearby_cap_needs_verified_ground_return(
    ic_ground: str,
    cap_ground: str,
    has_ground_plane: bool,
    expected_status: AssessmentStatus,
) -> None:
    """A nearby same-rail capacitor alone is not sufficient electrical evidence."""
    ic = PlacementComponentTopology(
        reference="U1",
        component_type="ic",
        pins=[
            PlacementPinTopology(
                pin_number="1",
                net_name="+3V3",
                pin_type="power_input",
                location_mm=(10.0, 12.0),
            ),
            PlacementPinTopology(
                pin_number="2",
                net_name=ic_ground,
                pin_type="ground",
                location_mm=(10.0, 10.0),
            ),
        ],
    )
    cap = PlacementComponentTopology(
        reference="C1",
        component_type="capacitor",
        location_mm=(10.0, 12.5),
        pins=[
            PlacementPinTopology(
                pin_number="1",
                net_name="+3V3",
                pin_type="passive",
                location_mm=(10.0, 12.5),
            ),
            PlacementPinTopology(
                pin_number="2",
                net_name=cap_ground,
                pin_type="ground",
                location_mm=(10.0, 13.0),
            ),
        ],
    )
    topology = PlacementBoardTopology(
        components={"U1": ic, "C1": cap},
        has_ground_plane=has_ground_plane,
    )
    assessment = evaluate_decoupling_connectivity(ReviewContext(), topology)
    assert assessment.status == expected_status
    if expected_status == AssessmentStatus.NOT_ASSESSED:
        assert assessment.missing_inputs == ["ground_return_connectivity"]
        assert assessment.metadata["cap_ref"] == "C1"
    else:
        assert assessment.findings == []
        assert assessment.metadata["passed_pins"] == 1


def test_same_rail_selects_nearest_cap_with_verified_ground_return() -> None:
    """A nearer wrong-ground capacitor must not hide a valid decoupler."""
    ic = PlacementComponentTopology(
        reference="U1",
        component_type="ic",
        pins=[
            PlacementPinTopology(
                pin_number="1",
                net_name="+3V3",
                pin_type="power_input",
                location_mm=(10.0, 12.0),
            ),
            PlacementPinTopology(
                pin_number="2",
                net_name="AGND",
                pin_type="ground",
                location_mm=(10.0, 10.0),
            ),
        ],
    )

    def cap(ref: str, distance: float, ground: str) -> PlacementComponentTopology:
        return PlacementComponentTopology(
            reference=ref,
            component_type="capacitor",
            location_mm=(10.0, 12.0 + distance),
            pins=[
                PlacementPinTopology(
                    pin_number="1",
                    net_name="+3V3",
                    pin_type="passive",
                    location_mm=(10.0, 12.0 + distance),
                ),
                PlacementPinTopology(
                    pin_number="2",
                    net_name=ground,
                    pin_type="ground",
                    location_mm=(10.0, 12.5 + distance),
                ),
            ],
        )

    topology = PlacementBoardTopology(
        components={
            "U1": ic,
            "C1": cap("C1", 0.3, "DGND"),
            "C2": cap("C2", 1.0, "AGND"),
        },
        has_ground_plane=True,
    )
    result = evaluate_decoupling_connectivity(ReviewContext(), topology)
    assert result.status == AssessmentStatus.PASS
    assert result.metadata["passed_pins"] == 1
    assert result.findings == []


def test_missing_unresolved_power_pin_returns_not_assessed() -> None:
    u1 = PlacementComponentTopology(
        reference="U1",
        component_type="ic",
        location_mm=(15.0, 25.0),
        pins=[
            PlacementPinTopology(pin_number="1", net_name="VDD", location_mm=(15.0, 26.0)),
        ],
    )
    topology = PlacementBoardTopology(components={"U1": u1})
    context = ReviewContext(project_name="MissingPinBoard")

    # Query for non-existent power pin 99
    assessment = evaluate_decoupling_connectivity(
        context,
        topology,
        target_ic="U1",
        target_power_pin="99",
    )

    assert assessment.status == AssessmentStatus.NOT_ASSESSED
    assert "power_pin_resolution" in assessment.missing_inputs
    assert "99" in assessment.summary
    assert "cannot substitute" in assessment.summary


def test_unsupported_backside_transform_returns_not_assessed() -> None:
    u1 = PlacementComponentTopology(
        reference="U1",
        component_type="ic",
        location_mm=(10.0, 10.0),
        layer="B.Cu",
        pins=[
            PlacementPinTopology(
                pin_number="1",
                net_name="+3.3V",
                pin_type="power_input",
                location_mm=(10.0, 10.0),
                layer="B.Cu",
            ),
        ],
    )
    topology = PlacementBoardTopology(components={"U1": u1})
    context = ReviewContext(project_name="BacksideBoard")

    assessment = evaluate_decoupling_connectivity(
        context,
        topology,
        target_ic="U1",
        target_power_pin="1",
    )

    assert assessment.status == AssessmentStatus.NOT_ASSESSED
    assert "backside_transform" in assessment.missing_inputs


def test_crystal_matches_declared_companion_oscillator_net() -> None:
    # Sensor U1 is geographically closer (1.0 mm away), but has no oscillator nets
    # MCU U2 is 3.5 mm away, but shares OSC_IN / OSC_OUT nets with crystal Y1
    y1 = PlacementComponentTopology(
        reference="Y1",
        component_type="crystal",
        location_mm=(20.0, 20.0),
        pins=[
            PlacementPinTopology(pin_number="1", net_name="OSC_IN", location_mm=(20.0, 20.0)),
            PlacementPinTopology(pin_number="2", net_name="OSC_OUT", location_mm=(20.0, 21.0)),
        ],
    )
    u1_sensor = PlacementComponentTopology(
        reference="U1",
        component_type="ic",
        location_mm=(20.0, 21.0),  # 1.0 mm away from Y1
        pins=[
            PlacementPinTopology(pin_number="1", net_name="I2C_SDA"),
            PlacementPinTopology(pin_number="2", net_name="I2C_SCL"),
        ],
    )
    u2_mcu = PlacementComponentTopology(
        reference="U2",
        component_type="ic",
        location_mm=(20.0, 23.5),  # 3.5 mm away from Y1
        pins=[
            PlacementPinTopology(pin_number="5", net_name="OSC_IN"),
            PlacementPinTopology(pin_number="6", net_name="OSC_OUT"),
        ],
    )

    topology = PlacementBoardTopology(
        components={"Y1": y1, "U1": u1_sensor, "U2": u2_mcu},
    )
    context = ReviewContext(project_name="CrystalBoard")

    assessment = evaluate_crystal_placement(context, topology, max_distance_mm=8.0)

    # Must match companion U2 (not nearest IC U1) and pass
    assert assessment.status == AssessmentStatus.PASS
    assert assessment.findings == []


def test_crystal_without_companion_fails() -> None:
    y1 = PlacementComponentTopology(
        reference="Y1",
        component_type="crystal",
        location_mm=(10.0, 10.0),
        pins=[
            PlacementPinTopology(pin_number="1", net_name="XTAL_UNROUTED_1"),
            PlacementPinTopology(pin_number="2", net_name="XTAL_UNROUTED_2"),
        ],
    )
    u1 = PlacementComponentTopology(
        reference="U1",
        component_type="ic",
        location_mm=(15.0, 10.0),
        pins=[PlacementPinTopology(pin_number="1", net_name="GND")],
    )

    topology = PlacementBoardTopology(components={"Y1": y1, "U1": u1})
    context = ReviewContext(project_name="OpenCrystalBoard")

    assessment = evaluate_crystal_placement(context, topology)

    assert assessment.status == AssessmentStatus.FAIL
    assert len(assessment.findings) == 1
    assert "no declared companion" in assessment.findings[0].description


def test_si_decoupling_service_unresolved_pin_not_assessed() -> None:
    service = SignalIntegrityDecouplingPlacementService()
    payload = DecouplingPlacementInput(
        ic_ref="U1",
        power_pin="99",
        target_freq_mhz=250.0,
    )
    output = service.analyze(
        payload=payload,
        source_x_mm=10.0,
        source_y_mm=20.0,
        recommended_mm=3.0,
        capacitors=[("C1", 1.0, "100nF")],
        is_pad_verified=False,
    )

    assert "NOT_ASSESSED" in output
    assert "Power pin '99' could not be resolved" in output
    assert "cannot confirm electrical PASS" in output


def test_emc_check_decoupling_wrong_rail_returns_warn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fp_u1 = MagicMock()
    fp_u1.reference_field.text.value = "U1"
    fp_u1.position = MagicMock(x=10_000_000, y=10_000_000)

    fp_c1 = MagicMock()
    fp_c1.reference_field.text.value = "C1"
    fp_c1.position = MagicMock(x=11_000_000, y=10_000_000)

    # U1 pad is on +3.3V, C1 pad is on +12V
    pad_u1 = MagicMock()
    pad_u1.parent = fp_u1
    pad_u1.net.name = "+3.3V"

    pad_c1 = MagicMock()
    pad_c1.parent = fp_c1
    pad_c1.net.name = "+12V"

    monkeypatch.setattr(emc, "board_footprints", MagicMock(return_value=[fp_u1, fp_c1]))
    monkeypatch.setattr(emc, "board_pads", MagicMock(return_value=[pad_u1, pad_c1]))
    monkeypatch.setattr(emc, "get_board", MagicMock())
    monkeypatch.setattr(emc, "point_xy_mm", lambda pos: (pos.x / 1_000_000, pos.y / 1_000_000))

    verdict, detail = emc._emc_check_decoupling_text(max_distance_mm=3.0)

    # Must NOT return PASS when capacitor is on wrong rail
    assert verdict == "WARN"
    assert "Missing local capacitors" in detail or "different" in detail


def test_placement_decoupling_edge_cases() -> None:
    context = ReviewContext()

    # Unsupported geometry
    top_unsupp = PlacementBoardTopology(unsupported_geometry=True)
    assert (
        evaluate_decoupling_connectivity(context, top_unsupp).status
        == AssessmentStatus.NOT_ASSESSED
    )

    # Target IC not found
    top_empty = PlacementBoardTopology()
    assert (
        evaluate_decoupling_connectivity(context, top_empty, target_ic="U99").status
        == AssessmentStatus.BLOCKED
    )

    # No ICs
    assert (
        evaluate_decoupling_connectivity(context, top_empty).status
        == AssessmentStatus.NOT_APPLICABLE
    )

    # IC with no power pins
    u_no_pwr = PlacementComponentTopology(reference="U1", component_type="ic", pins=[])
    top_no_pwr = PlacementBoardTopology(components={"U1": u_no_pwr})
    assert (
        evaluate_decoupling_connectivity(context, top_no_pwr).status
        == AssessmentStatus.NOT_ASSESSED
    )

    # Pin location is None
    u_none_loc = PlacementComponentTopology(
        reference="U1",
        component_type="ic",
        pins=[
            PlacementPinTopology(
                pin_number="1", net_name="+3V3", pin_type="power_input", location_mm=None
            )
        ],
    )
    top_none_loc = PlacementBoardTopology(components={"U1": u_none_loc})
    assert (
        evaluate_decoupling_connectivity(context, top_none_loc).status
        == AssessmentStatus.NOT_ASSESSED
    )

    # Same rail capacitor farther than threshold
    u1 = PlacementComponentTopology(
        reference="U1",
        component_type="ic",
        pins=[
            PlacementPinTopology(
                pin_number="1", net_name="+3.3V", pin_type="power_input", location_mm=(0.0, 0.0)
            ),
            PlacementPinTopology(
                pin_number="2", net_name="GND", pin_type="ground", location_mm=(0.0, 1.0)
            ),
        ],
    )
    c_far = PlacementComponentTopology(
        reference="C1",
        component_type="capacitor",
        location_mm=(10.0, 10.0),
        pins=[
            PlacementPinTopology(
                pin_number="1", net_name="+3.3V", pin_type="passive", location_mm=(10.0, 10.0)
            ),
            PlacementPinTopology(
                pin_number="2", net_name="GND", pin_type="ground", location_mm=(10.0, 11.0)
            ),
        ],
    )
    top_far = PlacementBoardTopology(components={"U1": u1, "C1": c_far}, has_ground_plane=True)
    res_far = evaluate_decoupling_connectivity(context, top_far, max_distance_mm=3.0)
    assert res_far.status == AssessmentStatus.FAIL
    assert len(res_far.findings) == 1
    assert "is 14.14 mm from pin" in res_far.findings[0].description


def test_placement_crystal_edge_cases() -> None:
    context = ReviewContext()

    # No crystals
    top_empty = PlacementBoardTopology()
    assert evaluate_crystal_placement(context, top_empty).status == AssessmentStatus.NOT_APPLICABLE

    # Crystal with declared companion_refs and excessive distance
    mcu = PlacementComponentTopology(reference="U1", component_type="ic", location_mm=(0.0, 0.0))
    y1_far = PlacementComponentTopology(
        reference="Y1",
        component_type="crystal",
        location_mm=(20.0, 0.0),
        companion_refs=["U1"],
    )
    top_xtal_far = PlacementBoardTopology(components={"U1": mcu, "Y1": y1_far})
    res_xtal_far = evaluate_crystal_placement(context, top_xtal_far, max_distance_mm=5.0)
    assert res_xtal_far.status == AssessmentStatus.FAIL
    assert len(res_xtal_far.findings) == 1
    assert "is 20.00 mm from companion" in res_xtal_far.findings[0].description

    # Crystal with missing coordinates
    y1_no_coords = PlacementComponentTopology(
        reference="Y1",
        component_type="crystal",
        location_mm=None,
        companion_refs=["U1"],
    )
    top_xtal_no_coords = PlacementBoardTopology(components={"U1": mcu, "Y1": y1_no_coords})
    assert (
        evaluate_crystal_placement(context, top_xtal_no_coords).status
        == AssessmentStatus.NOT_ASSESSED
    )
