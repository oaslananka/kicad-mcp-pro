"""Unit tests for invariant-preserving visual quality review and cosmetic planning (#1583, T5)."""

from __future__ import annotations

from typing import Any

from kicad_mcp.models.review import (
    AssessmentStatus,
    EvaluationMethod,
    ReviewContext,
)
from kicad_mcp.review.visual_quality import (
    ComponentRotationState,
    apply_cosmetic_transaction,
    calculate_cpl_rotation,
    detect_pin1_marker_visibility,
    evaluate_pcb_visual_quality,
    evaluate_schematic_visual_quality,
    evaluate_visual_quality,
    plan_cosmetic_transaction,
    verify_rotation_independence,
)

SAMPLE_CLEAN_SCH = """(kicad_sch
  (version 20231120)
  (generator "eeschema")
  (paper "A4")
  (title_block
    (title "Clean Test Circuit")
  )
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
  (symbol
    (lib_id "Device:C")
    (at 76.2 50.8 0)
    (unit 1)
    (property "Reference" "C1" (at 76.2 48.26 0) (effects (font (size 1.27 1.27))))
    (property "Value" "100nF" (at 76.2 53.34 0) (effects (font (size 1.27 1.27))))
    (property "Footprint" "" (at 76.2 50.8 0) (effects (font (size 1.27 1.27)) hide))
    (pin "1" (uuid "p3") (at 76.2 45.72 270))
    (pin "2" (uuid "p4") (at 76.2 55.88 90))
  )
  (wire
    (pts (xy 50.8 45.72) (xy 76.2 45.72))
    (stroke (width 0) (type solid))
  )
)"""

SAMPLE_BLANK_SCH = (
    '(kicad_sch (version 20231120) (generator eeschema) (title_block (title "Empty")))'
)


def test_empty_schematic_returns_not_assessed_never_pass() -> None:
    """Proves False-PASS #6 is fixed: zero symbols and zero wires evaluates to NOT_ASSESSED."""
    context = ReviewContext(project_name="blank_project")
    assessment = evaluate_schematic_visual_quality(context, SAMPLE_BLANK_SCH)

    assert assessment.status == AssessmentStatus.NOT_ASSESSED
    assert assessment.missing_inputs == ["schematic_symbols", "schematic_wires"]
    assert assessment.metadata.get("empty_sheet") is True
    assert assessment.metadata.get("defect_category") == "cosmetic_style"
    assert assessment.metadata.get("electrical_defect") is False


def test_empty_pcb_returns_not_assessed_never_pass() -> None:
    """Proves that a PCB with zero footprints evaluates to NOT_ASSESSED, never PASS."""
    context = ReviewContext(project_name="blank_pcb")
    assessment = evaluate_pcb_visual_quality(context, footprints={})

    assert assessment.status == AssessmentStatus.NOT_ASSESSED
    assert assessment.missing_inputs == ["board_footprints"]
    assert assessment.metadata.get("empty_board") is True
    assert assessment.metadata.get("defect_category") == "cosmetic_style"
    assert assessment.metadata.get("electrical_defect") is False


def test_schematic_missing_input_blocked() -> None:
    """When schematic text is None, returns BLOCKED."""
    context = ReviewContext(project_name="test")
    assessment = evaluate_schematic_visual_quality(context, None)

    assert assessment.status == AssessmentStatus.BLOCKED
    assert assessment.missing_inputs == ["sch_text"]


def test_pcb_missing_input_blocked() -> None:
    """When PCB footprints is None, returns BLOCKED."""
    context = ReviewContext(project_name="test")
    assessment = evaluate_pcb_visual_quality(context, footprints=None)

    assert assessment.status == AssessmentStatus.BLOCKED
    assert assessment.missing_inputs == ["board_footprints"]


def test_rotation_independence_and_cpl_calibration() -> None:
    """Verifies that schematic, PCB, and CPL rotations remain decoupled."""
    # R1: 0 deg on schematic, 90 deg on PCB, 90 deg on JLCPCB CPL (0 offset)
    r1_before = ComponentRotationState(
        reference="R1",
        symbol_orientation_deg=0.0,
        pcb_rotation_deg=90.0,
        cpl_rotation_deg=90.0,
        cpl_offset_deg=0.0,
    )
    assert r1_before.verify_cpl_calibration() is True

    # Rotate schematic symbol for aesthetic layout: 0 -> 90 deg
    r1_after_sch = ComponentRotationState(
        reference="R1",
        symbol_orientation_deg=90.0,
        pcb_rotation_deg=90.0,
        cpl_rotation_deg=90.0,
        cpl_offset_deg=0.0,
    )
    ok, err = verify_rotation_independence(r1_before, r1_after_sch, mutated_domain="schematic")
    assert ok is True
    assert err is None

    # Violation: schematic cosmetic change leaked into physical PCB rotation
    r1_corrupt_pcb = ComponentRotationState(
        reference="R1",
        symbol_orientation_deg=90.0,
        pcb_rotation_deg=180.0,  # Corrupted!
        cpl_rotation_deg=90.0,
        cpl_offset_deg=0.0,
    )
    ok, err = verify_rotation_independence(r1_before, r1_corrupt_pcb, mutated_domain="schematic")
    assert ok is False
    assert err is not None
    assert "mutated PCB physical rotation" in err

    # Diode with 180 deg CPL offset
    d1_calc = calculate_cpl_rotation(pcb_rotation_deg=90.0, cpl_offset_deg=180.0)
    assert d1_calc == 270.0


def test_cosmetic_transaction_dry_run_preserves_invariants() -> None:
    """Dry run plan verifies 100% preservation of connectivity, symbols, and hierarchy."""

    def safe_mutator(text: str) -> tuple[str, list[dict[str, Any]]]:
        # Trivial safe cosmetic change: update title
        mutated = text.replace("Clean Test Circuit", "Clean Test Circuit Rev B")
        return mutated, [{"change": "title_update", "title": "Clean Test Circuit Rev B"}]

    plan = plan_cosmetic_transaction(SAMPLE_CLEAN_SCH, "title_fix", safe_mutator)
    assert plan.is_safe_to_apply is True
    assert plan.connectivity_preserved is True
    assert plan.symbol_inventory_preserved is True
    assert plan.hierarchy_preserved is True
    assert plan.refusal_reason is None
    assert len(plan.changes) == 1

    applied_text, success, msg = apply_cosmetic_transaction(SAMPLE_CLEAN_SCH, plan)
    assert success is True
    assert "Clean Test Circuit Rev B" in applied_text
    assert "Successfully applied" in msg


def test_cosmetic_transaction_refuses_and_rolls_back_on_invariant_violation() -> None:
    """Cosmetic plan rejects changes that alter symbol designators or connectivity."""

    def destructive_mutator(text: str) -> tuple[str, list[dict[str, Any]]]:
        # Destructive mutation: changes reference R1 to R99
        mutated = text.replace('"R1"', '"R99"')
        return mutated, [{"change": "rename_ref", "from": "R1", "to": "R99"}]

    plan = plan_cosmetic_transaction(SAMPLE_CLEAN_SCH, "rename_bug", destructive_mutator)
    assert plan.is_safe_to_apply is False
    assert plan.symbol_inventory_preserved is False
    assert plan.refusal_reason is not None
    assert "Symbol inventory altered" in plan.refusal_reason

    applied_text, success, msg = apply_cosmetic_transaction(SAMPLE_CLEAN_SCH, plan)
    assert success is False
    assert applied_text == SAMPLE_CLEAN_SCH
    assert "Refused to apply" in msg


def test_pcb_pin1_marker_detection_and_occlusion() -> None:
    """Detects missing silkscreen pin-1 marker and silkscreen reference text occlusion."""
    footprints: dict[str, dict[str, Any]] = {
        "U1": {
            "x_mm": 50.0,
            "y_mm": 50.0,
            "width_mm": 5.0,
            "height_mm": 4.0,
            "rotation": 0.0,
            "block": """(footprint "Package_SO:SOIC-8"
              (layer "F.Cu")
              (pad "1" smd roundrect (at -2.0 -1.5) (size 1.5 0.6))
              (pad "2" smd roundrect (at -2.0 -0.5) (size 1.5 0.6))
              (pad "3" smd roundrect (at -2.0 0.5) (size 1.5 0.6))
              (fp_circle
                (center -2.0 -2.2) (end -1.8 -2.2)
                (stroke (width 0.12) (type solid)) (layer "F.SilkS")
              )
              (property "Reference" "U1" (at 0.0 3.0) (layer "F.SilkS"))
            )""",
        },
        "U2": {
            # Missing pin 1 silkscreen marker
            "x_mm": 80.0,
            "y_mm": 50.0,
            "width_mm": 5.0,
            "height_mm": 4.0,
            "rotation": 0.0,
            "block": """(footprint "Package_SO:SOIC-8"
              (layer "F.Cu")
              (pad "1" smd roundrect (at -2.0 -1.5) (size 1.5 0.6))
              (pad "2" smd roundrect (at -2.0 -0.5) (size 1.5 0.6))
              (pad "3" smd roundrect (at -2.0 0.5) (size 1.5 0.6))
              (property "Reference" "U2" (at 0.0 3.0) (layer "F.SilkS"))
            )""",
        },
    }

    findings = detect_pin1_marker_visibility(footprints)
    u2_missing = [f for f in findings if f.ref == "U2" and f.code == "pin1_marker_missing"]
    assert len(u2_missing) == 1

    u1_findings = [f for f in findings if f.ref == "U1"]
    assert len(u1_findings) == 0


def test_unified_evaluate_visual_quality() -> None:
    """Verifies that unified evaluator executes both schematic and PCB visual checks."""
    context = ReviewContext(
        project_name="unified_test",
        explicit_requirements={
            "schematic_symbols": True,
            "board_footprints": True,
        },
    )
    assessments = evaluate_visual_quality(
        context,
        sch_text=SAMPLE_CLEAN_SCH,
        footprints={
            "R1": {
                "x_mm": 20.0,
                "y_mm": 20.0,
                "width_mm": 2.0,
                "height_mm": 1.0,
                "rotation": 0.0,
                "block": (
                    '(footprint "R_0805" (layer "F.Cu") '
                    '(property "Reference" "R1" (at 0 2) (layer "F.SilkS")))'
                ),
            }
        },
        bounds=(0.0, 0.0, 100.0, 100.0),
    )

    assert len(assessments) == 2
    sch_eval = next(a for a in assessments if a.rule_id == "cosmetics.schematic_visual_readability")
    pcb_eval = next(a for a in assessments if a.rule_id == "cosmetics.pcb_visual_presentation")

    assert sch_eval.method == EvaluationMethod.HEURISTIC
    assert pcb_eval.method == EvaluationMethod.HEURISTIC
    assert sch_eval.status in (AssessmentStatus.PASS, AssessmentStatus.WARN)
    assert pcb_eval.status in (AssessmentStatus.PASS, AssessmentStatus.WARN)
