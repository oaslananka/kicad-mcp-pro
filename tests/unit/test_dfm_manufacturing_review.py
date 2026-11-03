"""Unit tests for DFM, DFA, DFT, BOM, and Bring-up Review (#1586)."""

from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

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


def test_dfm_missing_profile_measurements_is_unassessed(
    jlcpcb_2layer_profile: FabricationProfile,
) -> None:
    """A selected vendor profile is not evidence that the PCB measurements pass."""
    result = evaluate_dfm_fabrication_limits(
        jlcpcb_2layer_profile,
        BoardDFMInput(copper_layers=2),
        ReviewContext(project_name="board"),
    )
    assert result.status == AssessmentStatus.NOT_ASSESSED
    assert "min_trace_width_mm" in result.missing_inputs
    assert "min_drill_mm" in result.missing_inputs


def test_empty_dft_cannot_be_certified_as_testable() -> None:
    result = evaluate_dft_testability(DFTTestabilitySpec(), ReviewContext())
    assert result.status == AssessmentStatus.NOT_ASSESSED
    assert "testpoint_coverage" in result.missing_inputs


def test_empty_bringup_plan_cannot_be_certified() -> None:
    result = evaluate_bringup_measurements(
        [],
        StageAuthorizationInput(power_on_authorized=True, power_on_authorizer="owner"),
        ReviewContext(),
    )
    assert result.status == AssessmentStatus.NOT_ASSESSED
    assert "bringup_test_plan" in result.missing_inputs


def test_bom_without_stock_evidence_does_not_claim_verified_stock() -> None:
    item = BOMItemInput(reference="U1", mpn="test-ic", footprint="SOIC8")
    assert item.stock_status == "UNVERIFIED"
    result = evaluate_bom_and_lifecycle([item], ReviewContext())
    assert result.status == AssessmentStatus.WARN
    assert any("unverified" in finding.description.lower() for finding in result.findings)


def test_fabrication_profile_digest_changes_with_rules_even_when_source_digest_same(
    jlcpcb_2layer_profile: FabricationProfile,
) -> None:
    """Supplier source checksums do not replace immutable profile-revision hashes."""
    source_digest = "a" * 64
    first = jlcpcb_2layer_profile.model_copy(update={"source_sha256": source_digest})
    updated = first.model_copy(update={"version": "2026.11"})
    assert first.profile_sha256() != updated.profile_sha256()
    changed_rule = first.model_copy(update={"rules": {"min_trace_width_mm": 0.25}})
    assert first.profile_sha256() != changed_rule.profile_sha256()


def test_assembly_profile_digest_changes_with_parameters_even_if_source_unchanged(
    smt_assembly_profile: AssemblyProfile,
) -> None:
    old = smt_assembly_profile.model_copy(update={"source_sha256": "b" * 64})
    new = old.model_copy(update={"min_fiducials": 3})
    assert old.profile_sha256() != new.profile_sha256()


@pytest.mark.parametrize("bad_value", [math.nan, math.inf, -math.inf])
def test_nonfinite_bringup_measurement_rejected(bad_value: float) -> None:
    with pytest.raises(ValidationError):
        BringupPlanInput(
            item_id="PWR_01",
            description="rail measured",
            measured_value=bad_value,
            acceptance_min=3.1,
            acceptance_max=3.5,
        )


def test_nonfinite_supplier_rule_rejected(jlcpcb_2layer_profile: FabricationProfile) -> None:
    with pytest.raises(ValidationError):
        FabricationProfile(
            **{
                **jlcpcb_2layer_profile.model_dump(),
                "rules": {"min_trace_width_mm": math.nan},
            }
        )


def test_bringup_without_acceptance_bounds_is_not_a_pass() -> None:
    result = evaluate_bringup_measurements(
        [
            BringupPlanInput(
                item_id="PWR_01",
                description="power-on test",
                measured_value=3.3,
                measurement_unit="V",
                instrument_id="DMM001",
                environmental_temp_c=22.0,
            )
        ],
        StageAuthorizationInput(power_on_authorized=True, power_on_authorizer="owner"),
        ReviewContext(),
    )
    assert result.status != AssessmentStatus.PASS


def test_empty_fabricator_exception_cannot_waive_usb4085(
    jlcpcb_2layer_profile: FabricationProfile,
) -> None:
    board = BoardDFMInput(
        copper_layers=2,
        pth_annular_rings=[{"ref": "J1", "pad_number": "A1", "nominal_ring_mm": 0.125}],
    )
    context = ReviewContext(explicit_requirements={"fabricator_exceptions": {"J1": ""}})
    result = evaluate_dfm_fabrication_limits(jlcpcb_2layer_profile, board, context)
    assert result.status == AssessmentStatus.FAIL
    assert any("#1381" in finding.description for finding in result.findings)


def _passing_dfm_board(**updates: object) -> BoardDFMInput:
    values = {
        "copper_layers": 2,
        "min_trace_width_mm": 0.20,
        "min_trace_clearance_mm": 0.20,
        "min_drill_mm": 0.40,
        "min_annular_ring_mm": 0.20,
        "copper_to_edge_mm": 0.50,
        "aspect_ratio": 6.0,
    }
    values.update(updates)
    return BoardDFMInput(**values)


def test_dfm_complete_profile_verification_and_pending_slots(
    jlcpcb_2layer_profile: FabricationProfile,
) -> None:
    context = ReviewContext(project_name="board")
    passing = evaluate_dfm_fabrication_limits(jlcpcb_2layer_profile, _passing_dfm_board(), context)
    assert passing.status == AssessmentStatus.PASS
    assert not passing.missing_inputs

    incomplete_pth = evaluate_dfm_fabrication_limits(
        jlcpcb_2layer_profile, _passing_dfm_board(unmeasured_pth_count=2), context
    )
    assert incomplete_pth.status == AssessmentStatus.WARN
    assert any("unmeasured" in x.description for x in incomplete_pth.findings)


def test_dfm_profile_without_capability_rules_is_unassessed(
    jlcpcb_2layer_profile: FabricationProfile,
) -> None:
    source = jlcpcb_2layer_profile.model_copy(update={"rules": {}})
    result = evaluate_dfm_fabrication_limits(
        source, _passing_dfm_board(), ReviewContext(project_name="board")
    )
    assert result.status == AssessmentStatus.NOT_ASSESSED
    assert "manufacturer_capability_rules" in result.missing_inputs


def test_dft_missing_spec_does_not_pass() -> None:
    result = evaluate_dft_testability(None, ReviewContext())
    assert result.status == AssessmentStatus.NOT_ASSESSED
    assert "testpoint_coverage" in result.missing_inputs


def test_bom_nrnd_out_of_stock_and_alternate_incompatibilities() -> None:
    item = BOMItemInput(
        reference="U1",
        mpn="candidate",
        footprint="SOIC8",
        lifecycle_status="NRND",
        stock_status="OUT_OF_STOCK",
        alternates=[
            {
                "alt_mpn": "alternative",
                "footprint_compatible": False,
                "pin_compatible": True,
                "electrical_compatible": False,
                "firmware_compatible": False,
                "lifecycle_status": "OBSOLETE",
            }
        ],
    )
    result = evaluate_bom_and_lifecycle([item], ReviewContext())
    assert result.status == AssessmentStatus.FAIL
    all_findings = " ".join(x.description for x in result.findings)
    for reason in (
        "NRND",
        "OUT_OF_STOCK",
        "footprint incompatible",
        "electrical rating incompatible",
        "firmware/register incompatible",
        "lifecycle OBSOLETE",
    ):
        assert reason in all_findings


def test_bom_missing_entries_not_assessed() -> None:
    result = evaluate_bom_and_lifecycle(None, ReviewContext())
    assert result.status == AssessmentStatus.NOT_ASSESSED
    assert "bom_items" in result.missing_inputs


def _measured_bringup(**updates: object) -> BringupPlanInput:
    values = {
        "item_id": "PWR_01",
        "description": "power supply rail",
        "measured_value": 3.3,
        "acceptance_min": 3.1,
        "acceptance_max": 3.5,
        "measurement_unit": "V",
        "instrument_id": "DMM-001",
        "environmental_temp_c": 22.0,
        "evidence_link": "local-measurement-001",
    }
    values.update(updates)
    return BringupPlanInput(**values)


def test_bringup_limits_and_missing_environment_are_recorded() -> None:
    result = evaluate_bringup_measurements(
        [
            _measured_bringup(measured_value=2.5, instrument_id=None),
            _measured_bringup(item_id="PWR_02", measured_value=3.9, environmental_temp_c=None),
        ],
        None,
        ReviewContext(project_name="board"),
    )
    assert result.status == AssessmentStatus.FAIL
    desc = " ".join(x.description for x in result.findings)
    for reason in (
        "below minimum",
        "exceeds maximum",
        "lacks instrument",
        "lacks environmental",
        "authorization record not provided",
    ):
        assert reason in desc


def test_bringup_valid_measurement_and_power_on_authorization_pass() -> None:
    result = evaluate_bringup_measurements(
        [_measured_bringup()],
        StageAuthorizationInput(power_on_authorized=True, power_on_authorizer="owner"),
        ReviewContext(project_name="board"),
    )
    assert result.status == AssessmentStatus.PASS


def test_bringup_missing_authorization_record_is_warning() -> None:
    result = evaluate_bringup_measurements(
        [_measured_bringup()],
        None,
        ReviewContext(project_name="board"),
    )
    assert result.status == AssessmentStatus.WARN
    assert any("authorization record not provided" in x.description for x in result.findings)


def test_unknown_alternate_compatibility_does_not_pass() -> None:
    """Unverified alternate pin/footprint/electrical equivalence is not approval."""
    item = BOMItemInput(
        reference="U1",
        mpn="original",
        footprint="SOIC8",
        stock_status="VERIFIED_IN_STOCK",
        stock_as_of="2026-11-03",
        alternates=[{"alt_mpn": "suggested"}],
    )
    result = evaluate_bom_and_lifecycle([item], ReviewContext())
    assert result.status == AssessmentStatus.FAIL
    assert any("footprint incompatible" in x.description for x in result.findings)
    assert any("pinout incompatible" in x.description for x in result.findings)


def test_undated_verified_stock_claim_requires_evidence() -> None:
    item = BOMItemInput(
        reference="U1",
        mpn="normal",
        footprint="SOIC8",
        stock_status="VERIFIED_IN_STOCK",
    )
    unproven = evaluate_bom_and_lifecycle([item], ReviewContext())
    assert unproven.status == AssessmentStatus.WARN
    dated = evaluate_bom_and_lifecycle(
        [item.model_copy(update={"stock_as_of": "2026-11-03"})], ReviewContext()
    )
    assert dated.status == AssessmentStatus.PASS


@pytest.mark.parametrize("unverified_ring", [math.nan, "invalid"])
def test_nonfinite_or_invalid_pth_ring_never_passes(
    jlcpcb_2layer_profile: FabricationProfile,
    unverified_ring: object,
) -> None:
    board = _passing_dfm_board(
        pth_annular_rings=[{"ref": "J1", "pad_number": "A1", "nominal_ring_mm": unverified_ring}]
    )
    result = evaluate_dfm_fabrication_limits(jlcpcb_2layer_profile, board, ReviewContext())
    assert result.status == AssessmentStatus.FAIL
    assert any("#1381" in x.description for x in result.findings)


def test_missing_supplier_specific_ring_floor_stays_unassessed(
    jlcpcb_2layer_profile: FabricationProfile,
) -> None:
    missing_rule = {
        name: value
        for name, value in jlcpcb_2layer_profile.rules.items()
        if name != "min_pth_annular_ring_2layer_1oz_mm"
    }
    profile = jlcpcb_2layer_profile.model_copy(update={"rules": missing_rule})
    board = _passing_dfm_board(
        pth_annular_rings=[{"ref": "J1", "pad_number": "A1", "nominal_ring_mm": 0.2}]
    )
    result = evaluate_dfm_fabrication_limits(profile, board, ReviewContext())
    assert result.status == AssessmentStatus.NOT_ASSESSED
    assert "min_pth_annular_ring_2layer_1oz_mm" in result.missing_inputs


def test_power_on_without_named_authorizer_cannot_pass() -> None:
    result = evaluate_bringup_measurements(
        [_measured_bringup()],
        StageAuthorizationInput(power_on_authorized=True),
        ReviewContext(),
    )
    assert result.status != AssessmentStatus.PASS
    assert any("authorizer" in x.description.lower() for x in result.findings)


def test_bringup_measurement_without_evidence_reference_cannot_pass() -> None:
    result = evaluate_bringup_measurements(
        [_measured_bringup(evidence_link=None)],
        StageAuthorizationInput(power_on_authorized=True, power_on_authorizer="owner"),
        ReviewContext(),
    )
    assert result.status != AssessmentStatus.PASS
    assert any("evidence" in x.description.lower() for x in result.findings)


def test_measured_bringup_without_power_on_permission_cannot_pass() -> None:
    result = evaluate_bringup_measurements(
        [_measured_bringup()],
        StageAuthorizationInput(power_on_authorized=False),
        ReviewContext(),
    )
    assert result.status != AssessmentStatus.PASS
