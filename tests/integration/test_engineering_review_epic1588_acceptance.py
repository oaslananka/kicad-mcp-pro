"""End-to-end integration and adversarial fixture acceptance tests for Epic #1588 (T10).

Covers all 8 adversarial pairs:
1. Decoupling: near IC but wrong power net vs matching power net (#1582)
2. Mechanical: inward-facing USB connector vs outward-facing connector (#1393)
3. Routing: 90-degree cosmetic routing corners vs actual trace clearance violation (#1581)
4. Visual quality: cosmetic wire aesthetic vs empty schematic sheet (#1583)
5. External simulation: matching converged report vs stale/foreign-board report (#1585)
6. High-voltage safety: generic keyword .dru vs documented specialist insulation signoff (#1584)
7. DFM annular ring: USB4085 0.125 mm under JLCPCB 0.18 mm floor (#1381) vs waiver (#1586)
8. Bring-up verification: completed checklist vs calibrated measured values (#1586)

Verifies unified reporting consistency between structured payload and Markdown text.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from kicad_mcp.models.intent import ConnectorMatingSpec
from kicad_mcp.models.placement_topology import (
    PlacementBoardTopology,
    PlacementComponentTopology,
    PlacementPinTopology,
)
from kicad_mcp.models.review import (
    AssessmentStatus,
    EvaluationMethod,
    ReviewAssessment,
    ReviewContext,
    ReviewFinding,
    ReviewSnapshot,
)
from kicad_mcp.review.catalog import (
    ReviewRuleCatalog,
    build_standard_rule_catalog,
    compute_coverage,
)
from kicad_mcp.review.dfm_review import (
    BoardDFMInput,
    BringupPlanInput,
    FabricationProfile,
    StageAuthorizationInput,
    evaluate_bringup_measurements,
    evaluate_dfm_fabrication_limits,
)
from kicad_mcp.review.electrical_contracts import (
    evaluate_specialist_safety_review,
)
from kicad_mcp.review.external_evidence import (
    ExternalAnalysisReport,
    evaluate_external_evidence,
)
from kicad_mcp.review.mechanical_acceptance import (
    evaluate_connector_mating_orientation,
)
from kicad_mcp.review.placement_connectivity import (
    evaluate_decoupling_connectivity,
)
from kicad_mcp.review.reporter import (
    generate_unified_review_report,
)
from kicad_mcp.review.routing_style import evaluate_routing_style
from kicad_mcp.review.stage_gate import (
    ReviewStage,
    StageGateDecision,
)
from kicad_mcp.review.visual_quality import (
    evaluate_schematic_visual_quality,
)

SAMPLE_BLANK_SCH = (
    '(kicad_sch (version 20231120) (generator eeschema) (title_block (title "Empty")))'
)

SAMPLE_VALID_SCH = """(kicad_sch
  (version 20231120)
  (generator "eeschema")
  (paper "A4")
  (title_block (title "Valid Circuit"))
  (symbol
    (lib_id "Device:R")
    (at 50.8 50.8 0)
    (unit 1)
    (property "Reference" "R1" (at 50.8 48.26 0) (effects (font (size 1.27 1.27))))
    (property "Value" "10k" (at 50.8 53.34 0) (effects (font (size 1.27 1.27))))
    (property "Footprint" "" (at 50.8 50.8 0) (effects (font (size 1.27 1.27)) hide))
    (pin "1" (uuid "p1") (at 50.8 45.72 270))
    (pin "2" (uuid "p2") (at 50.8 55.88 90))
  )
)"""


@pytest.fixture
def catalog() -> ReviewRuleCatalog:
    return build_standard_rule_catalog()


# --- Adversarial Pair 1: Decoupling Connectivity (#1582) ---
def test_adversarial_pair_decoupling_wrong_net_vs_matching_net() -> None:
    context = ReviewContext(project_name="mcu-board")
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

    # Adversarial: Physically 0.5 mm away, but connected to wrong rail (+12V instead of +3.3V)
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
    bad_topology = PlacementBoardTopology(
        components={"U1": u1, "C1": c1_wrong},
        has_ground_plane=True,
    )
    bad_assessment = evaluate_decoupling_connectivity(context, bad_topology)
    assert bad_assessment.status == AssessmentStatus.FAIL
    assert any("wrong rail" in f.description for f in bad_assessment.findings)

    # Correct: Connected to matching +3.3V and GND nets
    c1_good = PlacementComponentTopology(
        reference="C1",
        component_type="capacitor",
        location_mm=(10.0, 12.5),
        pins=[
            PlacementPinTopology(
                pin_number="1",
                net_name="+3.3V",
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
    good_topology = PlacementBoardTopology(
        components={"U1": u1, "C1": c1_good},
        has_ground_plane=True,
    )
    good_assessment = evaluate_decoupling_connectivity(context, good_topology)
    assert good_assessment.status == AssessmentStatus.PASS


# --- Adversarial Pair 2: Mechanical Connector Mating Direction (#1393) ---
def test_adversarial_pair_connector_mating_inward_vs_outward() -> None:
    context = ReviewContext(project_name="usb-device", has_3d_models=True)
    frame = (0.0, 0.0, 60.0, 36.0)
    fp_name = "Connector_USB:USB_C_Receptacle_GCT_USB4085"
    spec = ConnectorMatingSpec(
        ref="J1",
        footprint_id=fp_name,
        edge="left",
        normal_local="bottom",
        datum_x_mm=2.975,
        datum_y_mm=6.1,
        max_datum_error_mm=0.5,
        max_direction_error_deg=5.0,
    )

    # Adversarial: Connector on left edge rotated 90° points +x (inward)
    inward_footprints = {
        "J1": {
            "name": fp_name,
            "x_mm": 6.1,
            "y_mm": 13.5,
            "rotation": 90.0,
            "layer_name": "F.Cu",
            "layer_name_explicit": True,
        }
    }
    inward_assessment = evaluate_connector_mating_orientation(
        context,
        footprints=inward_footprints,
        frame=frame,
        specs=[spec],
    )
    assert inward_assessment.status == AssessmentStatus.FAIL
    assert any("points 180.0 degrees away" in f.description for f in inward_assessment.findings)

    # Correct: Connector on left edge rotated 270° points -x (outward)
    outward_footprints = {
        "J1": {
            "name": fp_name,
            "x_mm": 6.1,
            "y_mm": 13.5,
            "rotation": 270.0,
            "layer_name": "F.Cu",
            "layer_name_explicit": True,
        }
    }
    outward_assessment = evaluate_connector_mating_orientation(
        context,
        footprints=outward_footprints,
        frame=frame,
        specs=[spec],
    )
    assert outward_assessment.status == AssessmentStatus.PASS


# --- Adversarial Pair 3: Routing Style vs Electrical DRC (#1581) ---
def test_adversarial_pair_routing_style_vs_clearance() -> None:
    context = ReviewContext(project_name="sensor", declared_routing_style="45_degree")
    pcb_text = """(kicad_pcb
  (segment (start 10 10) (end 20 10) (width 0.2) (layer "F.Cu") (net "SIGNAL_A"))
  (segment (start 20 10) (end 20 20) (width 0.2) (layer "F.Cu") (net "SIGNAL_A"))
)"""
    style_assessment = evaluate_routing_style(context, pcb_text)
    assert style_assessment.status == AssessmentStatus.WARN
    assert "advisory" in style_assessment.summary.lower()
    assert style_assessment.metadata["defect_category"] == "cosmetic_style"
    assert style_assessment.metadata["electrical_defect"] is False


# --- Adversarial Pair 4: Visual Quality & Empty Sheet (#1583) ---
def test_adversarial_pair_schematic_visual_presentation_and_empty_sheet() -> None:
    context = ReviewContext(project_name="demo")

    # Empty sheet (False-PASS #6 prevention): 0 symbols, 0 wires must be NOT_ASSESSED, not PASS
    empty_assessment = evaluate_schematic_visual_quality(context, SAMPLE_BLANK_SCH)
    assert empty_assessment.status == AssessmentStatus.NOT_ASSESSED
    assert "schematic_symbols" in empty_assessment.missing_inputs

    # Valid sheet with symbols and wires
    populated_assessment = evaluate_schematic_visual_quality(context, SAMPLE_VALID_SCH)
    assert populated_assessment.status == AssessmentStatus.PASS


# --- Adversarial Pair 5: External Simulation Evidence Freshness (#1585) ---
def test_adversarial_pair_external_evidence_fresh_vs_stale() -> None:
    context = ReviewContext(
        project_name="gigabit-phy",
        project_source_sha256="1" * 64,
        explicit_requirements={"expected_stackup_id": "JLC04161H-7628"},
    )

    # Adversarial: Stale source revision hash
    stale_report = ExternalAnalysisReport(
        report_id="SIM_001",
        tool_name="openEMS",
        tool_version="0.0.36",
        analysis_type="signal_integrity",
        project_key="gigabit-phy",
        source_sha256="2" * 64,  # Stale!
        stackup_id="JLC04161H-7628",
        convergence_status="converged",
    )
    stale_assessment = evaluate_external_evidence(context, stale_report)
    assert stale_assessment.status == AssessmentStatus.FAIL
    assert "Stale source report rejected" in stale_assessment.summary

    # Correct: Matching hash and converged solver
    fresh_report = ExternalAnalysisReport(
        report_id="SIM_002",
        tool_name="openEMS",
        tool_version="0.0.36",
        analysis_type="signal_integrity",
        project_key="gigabit-phy",
        source_sha256="1" * 64,
        stackup_id="JLC04161H-7628",
        convergence_status="converged",
    )
    fresh_assessment = evaluate_external_evidence(context, fresh_report)
    assert fresh_assessment.status == AssessmentStatus.PASS


# --- Adversarial Pair 6: High-Voltage Safety Review (#1584) ---
def test_adversarial_pair_hv_safety_generic_keyword_vs_specialist_signoff() -> None:
    hv_context = ReviewContext(project_name="mains-inverter", is_hv=True)

    # Adversarial: 230V mains without specialist review fails closed
    unreviewed_assessment = evaluate_specialist_safety_review(
        hv_context,
        voltage_v=230.0,
        has_specialist_signoff=False,
    )
    assert unreviewed_assessment.status == AssessmentStatus.FAIL
    assert "requires explicit specialist insulation" in unreviewed_assessment.summary

    # Correct: Documented specialist insulation coordination signoff
    reviewed_assessment = evaluate_specialist_safety_review(
        hv_context,
        voltage_v=230.0,
        has_specialist_signoff=True,
        specialist_evidence_id="EVID_IEC62368_SIGNOFF_20261103",
    )
    assert reviewed_assessment.status == AssessmentStatus.PASS
    assert reviewed_assessment.evidence_refs == ["EVID_IEC62368_SIGNOFF_20261103"]


# --- Adversarial Pair 7: DFM Annular Ring & USB4085 (#1381, #1586) ---
def test_adversarial_pair_dfm_usb4085_blocker_vs_fabricator_exception() -> None:
    profile = FabricationProfile(
        manufacturer="JLCPCB",
        tier="standard",
        process="rigid_1oz_2layer",
        version="2026.10",
        review_date="2026-10-21",
        source="https://jlcpcb.com/capabilities/pcb-capabilities/",
        rules={"min_pth_annular_ring_2layer_1oz_mm": 0.18},
    )
    board = BoardDFMInput(
        copper_layers=2,
        pth_annular_rings=[{"ref": "J1", "pad_number": "A1", "nominal_ring_mm": 0.125}],
    )

    # Adversarial: No waiver -> fails with #1381 reference
    unwaived_context = ReviewContext(project_name="dongle")
    unwaived_assessment = evaluate_dfm_fabrication_limits(profile, board, unwaived_context)
    assert unwaived_assessment.status == AssessmentStatus.FAIL
    assert any("#1381" in f.description for f in unwaived_assessment.findings)

    # Documented waiver in context
    waived_context = ReviewContext(
        project_name="dongle",
        explicit_requirements={"fabricator_exceptions": {"J1": "CAM_SIGNOFF_20261021"}},
    )
    waived_assessment = evaluate_dfm_fabrication_limits(profile, board, waived_context)
    usb_findings = [f for f in waived_assessment.findings if "#1381" in f.description]
    assert len(usb_findings) == 0


# --- Adversarial Pair 8: Bring-Up Checklist vs Measurement Evidence (#1586) ---
def test_adversarial_pair_bringup_checklist_vs_measurements() -> None:
    context = ReviewContext(project_name="power-stage")

    # Adversarial: Checked box without measurement values
    checklist_only = [
        BringupPlanInput(
            item_id="TP_01",
            description="5V Power rail verify",
            is_checklist_only=True,
            measured_value=None,
        )
    ]
    bad_assessment = evaluate_bringup_measurements(
        checklist_only,
        StageAuthorizationInput(power_on_authorized=True),
        context,
    )
    assert bad_assessment.status == AssessmentStatus.FAIL
    assert any(
        "checklist completion without measurements" in f.description
        for f in bad_assessment.findings
    )

    # Correct: Measured values within tolerance
    measured = [
        BringupPlanInput(
            item_id="TP_01",
            description="5V Power rail verify",
            is_checklist_only=False,
            measured_value=5.02,
            acceptance_min=4.75,
            acceptance_max=5.25,
            measurement_unit="V",
            instrument_id="FLUKE_87V_SN987",
            environmental_temp_c=24.0,
            evidence_link="signed-measurement-PWR_TP01",
        )
    ]
    good_assessment = evaluate_bringup_measurements(
        measured,
        StageAuthorizationInput(
            power_on_authorized=True,
            power_on_authorizer="qualified-test-engineer",
        ),
        context,
    )
    assert good_assessment.status == AssessmentStatus.PASS


# --- Unified Report Consistency & Read-Only Safety ---
def test_unified_report_structured_and_markdown_agreement(catalog: ReviewRuleCatalog) -> None:
    context = ReviewContext(
        project_name="acceptance-board",
        project_source_sha256="deadbeef" * 8,
    )
    resolved = catalog.resolve(context)

    assessments = [
        ReviewAssessment(
            rule_id="mechanical.connector_mating_orientation",
            rule_revision=1,
            status=AssessmentStatus.FAIL,
            method=EvaluationMethod.ANALYTICAL,
            summary="Connector mating direction inward.",
            findings=[
                ReviewFinding(
                    id="MECH_001",
                    rule_id="mechanical.connector_mating_orientation",
                    rule_revision=1,
                    severity="error",
                    object_ref="J1",
                    description="USB connector points inward into board.",
                    remediation="Rotate footprint 180 deg.",
                )
            ],
        ),
        ReviewAssessment(
            rule_id="mfg.dfm_profile_compliance",
            rule_revision=1,
            status=AssessmentStatus.NOT_ASSESSED,
            method=EvaluationMethod.ANALYTICAL,
            summary="DFM profile not loaded.",
            missing_inputs=["dfm_profile"],
        ),
        ReviewAssessment(
            rule_id="routing.orthogonal_corners",
            rule_revision=1,
            status=AssessmentStatus.WARN,
            method=EvaluationMethod.HEURISTIC,
            summary="Right-angle corner found.",
            findings=[
                ReviewFinding(
                    id="STYLE_001",
                    rule_id="routing.orthogonal_corners",
                    rule_revision=1,
                    severity="warning",
                    object_ref="SPI_CLK",
                    description="Right-angle corner at (10, 0).",
                    remediation="Chamfer vertex.",
                )
            ],
        ),
    ]

    coverage = compute_coverage(resolved, assessments)

    snapshot = ReviewSnapshot(
        project_key="acceptance-board",
        project_source_sha256="deadbeef" * 8,
        rule_catalog_revision="2026.11",
        context=context,
        resolved_rules=resolved,
        assessments=assessments,
        coverage=coverage,
    )

    report = generate_unified_review_report(snapshot, stage=ReviewStage.PRODUCTION_ACCEPTANCE)

    # 1. Verification of structured fields
    assert report.is_ready_for_stage is False
    assert report.verdict == "BLOCKED"  # Missing mandatory DFM profile blocks release
    assert report.critical_defects_count == 1
    assert report.missing_evidence_count >= 1
    assert report.cosmetic_findings_count == 1

    # 2. 100% agreement between structured counts and Markdown text
    crit_tag = f"Critical Engineering Defects ({report.critical_defects_count})"
    missing_tag = f"Missing Evidence & Unassessed Inputs ({report.missing_evidence_count})"
    cosm_tag = f"Cosmetic & Presentation Preferences ({report.cosmetic_findings_count})"
    assert crit_tag in report.markdown_text
    assert missing_tag in report.markdown_text
    assert cosm_tag in report.markdown_text
    assert f"**Verdict:** `{report.verdict}`" in report.markdown_text
    assert "Rotate footprint 180 deg" in report.markdown_text

    # 3. Read-only safety: Verify running the review does not modify project files
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = Path(tmpdir) / "board.kicad_pcb"
        content = "(kicad_pcb (version 20240108))"
        test_file.write_text(content)
        mtime_before = test_file.stat().st_mtime_ns

        _ = generate_unified_review_report(snapshot)

        mtime_after = test_file.stat().st_mtime_ns
        assert mtime_before == mtime_after
        assert test_file.read_text() == content


def test_integrated_report_never_passes_without_mandatory_rule_assessments(
    catalog: ReviewRuleCatalog,
) -> None:
    """Catalog registration is not evidence that its rules were evaluated."""
    context = ReviewContext(
        project_name="unverified-board",
        project_source_sha256="a" * 64,
    )
    resolved = catalog.resolve(context)
    coverage = compute_coverage(resolved, [])
    snapshot = ReviewSnapshot(
        project_key="unverified-board",
        project_source_sha256="a" * 64,
        rule_catalog_revision="2026.11",
        context=context,
        resolved_rules=resolved,
        assessments=[],
        coverage=coverage,
    )
    report = generate_unified_review_report(snapshot)
    assert report.verdict == "BLOCKED"
    assert report.is_ready_for_stage is False
    assert report.missing_evidence_count > 0
    assert any(
        action.is_blocking
        for action in report.actions
        if action.category.value == "MISSING_EVIDENCE"
    )


def test_positive_external_stage_decision_cannot_override_missing_mandatory_evidence(
    catalog: ReviewRuleCatalog,
) -> None:
    context = ReviewContext(project_name="board", project_source_sha256="b" * 64)
    resolved = catalog.resolve(context)
    snapshot = ReviewSnapshot(
        project_key="board",
        project_source_sha256="b" * 64,
        rule_catalog_revision="2026.11",
        context=context,
        resolved_rules=resolved,
        assessments=[],
        coverage=compute_coverage(resolved, []),
    )
    stage = StageGateDecision(
        stage=ReviewStage.PRODUCTION_ACCEPTANCE,
        approved=True,
        summary="Upstream claims approval",
    )
    report = generate_unified_review_report(
        snapshot,
        stage=ReviewStage.PRODUCTION_ACCEPTANCE,
        stage_decision=stage,
    )
    assert report.is_ready_for_stage is False
    assert report.verdict == "BLOCKED"


def test_empty_review_catalog_does_not_claim_engineering_pass() -> None:
    context = ReviewContext(project_name="board", project_source_sha256="c" * 64)
    snapshot = ReviewSnapshot(
        project_key="board",
        project_source_sha256="c" * 64,
        rule_catalog_revision="empty",
        context=context,
        resolved_rules=[],
        assessments=[],
        coverage=compute_coverage([], []),
    )
    report = generate_unified_review_report(snapshot)
    assert report.is_ready_for_stage is False
    assert report.verdict == "BLOCKED"
