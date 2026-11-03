"""Unit tests for DFM, DFA, DFT, BOM, and Bring-up Review (#1586)."""

from __future__ import annotations

import pytest

from kicad_mcp.models.review import (
    AssessmentStatus,
    ReviewContext,
)
from kicad_mcp.review.dfm_review import (
    AssemblyProfile,
    BoardAssemblyInput,
    BoardDFMInput,
    BOMItemInput,
    BringupPlanInput,
    DFTTestabilitySpec,
    FabricationProfile,
    StageAuthorizationInput,
    dfm_profile_to_evidence_record,
    evaluate_bom_and_lifecycle,
    evaluate_bringup_measurements,
    evaluate_dfa_assembly,
    evaluate_dfm_fabrication_limits,
    evaluate_dft_testability,
)


@pytest.fixture
def jlcpcb_2layer_profile() -> FabricationProfile:
    return FabricationProfile(
        manufacturer="JLCPCB",
        tier="standard",
        process="rigid_1oz_2layer",
        version="2026.10",
        review_date="2026-10-21",
        source="https://jlcpcb.com/capabilities/pcb-capabilities/",
        rules={
            "min_trace_width_mm": 0.127,
            "min_trace_clearance_mm": 0.127,
            "min_drill_mm": 0.3,
            "min_annular_ring_mm": 0.18,
            "min_pth_annular_ring_2layer_1oz_mm": 0.18,
            "recommended_pth_annular_ring_2layer_1oz_mm": 0.25,
            "copper_to_edge_mm": 0.3,
            "max_aspect_ratio": 8.0,
        },
    )


@pytest.fixture
def smt_assembly_profile() -> AssemblyProfile:
    return AssemblyProfile(
        assembler="JLCPCB",
        process="pcba_smt_standard",
        version="2026.10",
        review_date="2026-10-21",
        source="https://jlcpcb.com/smt-capabilities",
        min_fiducials=2,
        min_component_clearance_mm=0.25,
    )


def test_dfm_missing_profile_fails_closed() -> None:
    context = ReviewContext(project_name="usb-hub")
    board = BoardDFMInput(copper_layers=2)

    assessment = evaluate_dfm_fabrication_limits(None, board, context)
    assert assessment.status == AssessmentStatus.NOT_ASSESSED
    assert "dfm_profile" in assessment.missing_inputs
    assert "No universal fabrication limit" in assessment.summary


def test_dfm_violations_flagged(jlcpcb_2layer_profile: FabricationProfile) -> None:
    context = ReviewContext(project_name="usb-hub")
    board = BoardDFMInput(
        copper_layers=2,
        min_trace_width_mm=0.10,  # < 0.127
        min_trace_clearance_mm=0.10,  # < 0.127
        min_drill_mm=0.25,  # < 0.30
        min_annular_ring_mm=0.15,  # < 0.18
        copper_to_edge_mm=0.20,  # < 0.30
        aspect_ratio=9.5,  # > 8.0
        unmeasured_pth_count=4,
    )

    assessment = evaluate_dfm_fabrication_limits(jlcpcb_2layer_profile, board, context)
    assert assessment.status == AssessmentStatus.FAIL
    errors = [f for f in assessment.findings if f.severity == "error"]
    assert len(errors) == 6
    warnings = [f for f in assessment.findings if f.severity == "warning"]
    assert len(warnings) == 1
    assert "unmeasured" in warnings[0].description


def test_dfm_usb4085_annular_ring_blocker_issue_1381(
    jlcpcb_2layer_profile: FabricationProfile,
) -> None:
    context = ReviewContext(project_name="usb-dp-dongle")
    # GCT USB4085 with 16 signal PTH pads: Ø0.65 mm copper, Ø0.40 mm drill -> ring = 0.125 mm
    board = BoardDFMInput(
        copper_layers=2,
        min_trace_width_mm=0.15,
        min_trace_clearance_mm=0.15,
        min_drill_mm=0.40,
        min_annular_ring_mm=0.125,
        copper_to_edge_mm=0.5,
        pth_annular_rings=[
            {"ref": "J1", "pad_number": "A1", "nominal_ring_mm": 0.125},
            {"ref": "J1", "pad_number": "A4", "nominal_ring_mm": 0.125},
        ],
    )

    assessment = evaluate_dfm_fabrication_limits(jlcpcb_2layer_profile, board, context)
    assert assessment.status == AssessmentStatus.FAIL
    usb_findings = [f for f in assessment.findings if "#1381" in f.description]
    assert len(usb_findings) == 2
    assert "generic dfm score cannot waive" in usb_findings[0].description.lower()

    # With documented fabricator exception in review context, specific pads are permitted
    waived_context = ReviewContext(
        project_name="usb-dp-dongle",
        explicit_requirements={"fabricator_exceptions": {"J1": "CAM_APPROVED_20261021"}},
    )
    waived_assessment = evaluate_dfm_fabrication_limits(
        jlcpcb_2layer_profile, board, waived_context
    )
    # The general min_annular_ring_mm (0.125 < 0.18) still warns/fails general check
    # but the specific J1 #1381 blocker is waived
    waived_usb = [f for f in waived_assessment.findings if "#1381" in f.description]
    assert len(waived_usb) == 0


def test_profile_sha256_invalidation(jlcpcb_2layer_profile: FabricationProfile) -> None:
    hash1 = jlcpcb_2layer_profile.profile_sha256()

    profile2 = FabricationProfile(
        manufacturer=jlcpcb_2layer_profile.manufacturer,
        tier=jlcpcb_2layer_profile.tier,
        process=jlcpcb_2layer_profile.process,
        version="2026.11",  # Changed revision
        review_date="2026-11-01",
        source=jlcpcb_2layer_profile.source,
        rules=jlcpcb_2layer_profile.rules,
    )
    hash2 = profile2.profile_sha256()
    assert hash1 != hash2

    record = dfm_profile_to_evidence_record(
        jlcpcb_2layer_profile,
        project_key="demo-project",
        board_sha256="a" * 64,
    )
    assert len(record.inputs) == 2
    assert any(inp.sha256 == hash1 for inp in record.inputs)


def test_dfa_assembly_fiducials_and_courtyards(
    smt_assembly_profile: AssemblyProfile,
) -> None:
    context = ReviewContext(project_name="board")
    assembly_input = BoardAssemblyInput(
        fiducials_count=1,  # < 2
        courtyard_overlaps=[{"ref_a": "U1", "ref_b": "C12", "overlap_mm2": 0.45}],
        components=[
            {"ref": "D1", "is_polarized": True, "has_pin1_mark": False},
        ],
    )

    assessment = evaluate_dfa_assembly(smt_assembly_profile, assembly_input, context)
    assert assessment.status == AssessmentStatus.FAIL
    desc = " ".join(f.description for f in assessment.findings)
    assert "optical fiducials" in desc
    assert "Courtyard collision" in desc
    assert "missing pin-1" in desc


def test_dfa_cpl_rotation_semantics_separate_from_footprint(
    smt_assembly_profile: AssemblyProfile,
) -> None:
    context = ReviewContext(project_name="board")
    # Footprint 90 deg, assembler requires +180 deg offset -> expected CPL is 270 deg
    assembly_input = BoardAssemblyInput(
        fiducials_count=2,
        components=[
            {
                "ref": "U1",
                "footprint_rotation_deg": 90.0,
                "cpl_offset_deg": 180.0,
                "cpl_rotation_deg": 90.0,  # Error: forgot to apply offset!
                "has_pin1_mark": True,
            }
        ],
    )

    assessment = evaluate_dfa_assembly(smt_assembly_profile, assembly_input, context)
    assert assessment.status == AssessmentStatus.FAIL
    assert any("CPL rotation mismatch" in f.description for f in assessment.findings)

    # Correct CPL rotation
    assembly_input.components[0]["cpl_rotation_deg"] = 270.0
    valid_assessment = evaluate_dfa_assembly(smt_assembly_profile, assembly_input, context)
    assert valid_assessment.status == AssessmentStatus.PASS


def test_dfa_tombstoning_thermal_imbalance(
    smt_assembly_profile: AssemblyProfile,
) -> None:
    context = ReviewContext(project_name="board")
    assembly_input = BoardAssemblyInput(
        fiducials_count=2,
        components=[
            {
                "ref": "R1",
                "package": "R_0402",
                "pin1_connected_to_plane": True,
                "pin2_connected_to_plane": False,
                "has_thermal_relief": False,
                "has_pin1_mark": True,
            }
        ],
    )

    assessment = evaluate_dfa_assembly(smt_assembly_profile, assembly_input, context)
    assert assessment.status == AssessmentStatus.WARN
    assert any("tombstoning" in f.description for f in assessment.findings)


def test_dft_testability_coverage() -> None:
    context = ReviewContext(project_name="board")
    spec = DFTTestabilitySpec(
        power_rail_testpoints={"+3V3": True, "+1V8": False},
        reset_testpoints={"NRST": False},
        testpoint_probe_pitches=[
            {"tp1": "TP1", "tp2": "TP2", "pitch_mm": 0.8, "min_required_mm": 1.27}
        ],
    )

    assessment = evaluate_dft_testability(spec, context)
    assert assessment.status == AssessmentStatus.FAIL
    errors = [f for f in assessment.findings if f.severity == "error"]
    assert len(errors) == 3


def test_bom_lifecycle_and_unverified_stock() -> None:
    context = ReviewContext(project_name="board")
    bom_items = [
        BOMItemInput(
            reference="U1",
            mpn="STM32F405RGT6",
            footprint="LQFP-64",
            lifecycle_status="ACTIVE",
            stock_status="OFFLINE_SNAPSHOT",
            stock_as_of="2026-09-01",
        ),
        BOMItemInput(
            reference="U2",
            mpn="OLD_OPAMP",
            footprint="SOIC-8",
            lifecycle_status="EOL",
            alternates=[
                {
                    "alt_mpn": "NEW_OPAMP",
                    "footprint_compatible": True,
                    "pin_compatible": False,  # Pinout mismatch
                    "electrical_compatible": True,
                    "firmware_compatible": True,
                    "lifecycle_status": "ACTIVE",
                }
            ],
        ),
    ]

    assessment = evaluate_bom_and_lifecycle(bom_items, context)
    assert assessment.status == AssessmentStatus.FAIL
    assert any("offline_snapshot" in f.description.lower() for f in assessment.findings)
    assert any("EOL" in f.description for f in assessment.findings)
    assert any("pinout incompatible" in f.description for f in assessment.findings)


def test_bringup_checklist_is_not_measurement_evidence() -> None:
    context = ReviewContext(project_name="board")
    plan = [
        BringupPlanInput(
            item_id="PWR_01",
            description="3.3V Rail check",
            is_checklist_only=True,  # Merely checked off without actual measurement
            measured_value=None,
        ),
        BringupPlanInput(
            item_id="PWR_02",
            description="1.8V Rail check",
            is_checklist_only=False,
            target_rail_or_net="+1V8",
            acceptance_min=1.71,
            acceptance_max=1.89,
            measured_value=1.802,
            measurement_unit="V",
            instrument_id="DMM_KEITHLEY_2000_SN123",
            environmental_temp_c=23.5,
        ),
    ]

    auth = StageAuthorizationInput(power_on_authorized=True)
    assessment = evaluate_bringup_measurements(plan, auth, context)
    assert assessment.status == AssessmentStatus.FAIL
    checklist_findings = [f for f in assessment.findings if "checklist completion" in f.description]
    assert len(checklist_findings) == 1


def test_stage_authorization_separation() -> None:
    context = ReviewContext(project_name="board")
    plan = [
        BringupPlanInput(
            item_id="PWR_01",
            description="3.3V Rail check",
            measured_value=3.305,
            acceptance_min=3.135,
            acceptance_max=3.465,
            measurement_unit="V",
            instrument_id="DMM_01",
            environmental_temp_c=22.0,
        )
    ]

    # Production release requested before power-on authorization
    invalid_auth = StageAuthorizationInput(
        power_on_authorized=False,
        production_release_authorized=True,
    )
    assessment = evaluate_bringup_measurements(plan, invalid_auth, context)
    assert assessment.status == AssessmentStatus.FAIL
    assert any(
        "Production release cannot be authorized without completed" in f.description
        for f in assessment.findings
    )
