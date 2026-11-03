"""Safe invariant-preserving visual quality review and cosmetic planning (#1583, T5).

Principles:
1. Distinguish cosmetic style from electrical and manufacturing defects.
   Aesthetic issues (font size inconsistency, grid misalignment, non-standard symbol orientation)
   are tagged as cosmetic_style (electrical_defect=False), never mapping into electrical failures.
2. Fix False-PASS #6: An empty schematic sheet (0 symbols, 0 wires) or empty PCB (0 footprints)
   must evaluate to NOT_ASSESSED, never to PASS.
3. Strict separation of rotation semantics:
   - Schematic symbol orientation (aesthetic orientation on schematic sheet).
   - PCB footprint rotation (physical placement coordinates on PCB).
   - CPL pick-and-place rotation (manufacturing angle with zero-orientation offsets).
   Schematic cosmetic fixes must never mutate PCB footprint rotation or CPL rotation.
4. Safe dry-run cosmetic changes and invariant enforcement:
   - Cosmetic fixes produce a plan before committing.
   - Plan verifies that coordinate-independent net connectivity (pin groups and net names),
     component designators, and sheet hierarchy instances are 100% preserved.
   - Any violation triggers immediate refusal and automatic rollback.
5. PCB presentation review:
   - Uses pcb_readability checks (silkscreen overlap, offboard parts, body overlap).
   - Checks pin-1 silkscreen visibility and occlusion for polarized/multi-pin parts.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ..models.review import (
    AssessmentStatus,
    EvaluationMethod,
    ReviewAssessment,
    ReviewContext,
    ReviewFinding,
)
from ..models.visual_qa import (
    parse_symbols,
    parse_wires,
    run_cosmetic_qa,
)
from ..tools.schematic_cosmetics import ConnectivitySignature, _connectivity_signature
from ..utils.pcb_readability import (
    FootprintMap,
    PcbFinding,
    _reference_silk_box,
    _rotate,
    run_pcb_readability,
)

SCHEMATIC_VISUAL_RULE = "cosmetics.schematic_visual_readability"
PCB_VISUAL_RULE = "cosmetics.pcb_visual_presentation"


@dataclass(frozen=True, slots=True)
class ComponentRotationState:
    """Explicitly isolated rotation angles across the three engineering domains."""

    reference: str
    symbol_orientation_deg: float  # Schematic sheet aesthetic orientation (0, 90, 180, 270)
    pcb_rotation_deg: float  # PCB board layout physical placement angle
    cpl_rotation_deg: float  # Pick-and-place manufacturing tape/feeder angle
    cpl_offset_deg: float = 0.0  # Manufacturer/footprint zero-orientation calibration offset

    def verify_cpl_calibration(self) -> bool:
        """Verify that CPL angle equals PCB angle plus calibration offset (mod 360)."""
        expected = (self.pcb_rotation_deg + self.cpl_offset_deg) % 360.0
        actual = self.cpl_rotation_deg % 360.0
        return math.isclose(actual, expected, abs_tol=0.1)


def calculate_cpl_rotation(pcb_rotation_deg: float, cpl_offset_deg: float) -> float:
    """Calculate the expected manufacturing pick-and-place rotation from PCB rotation and offset."""
    return (pcb_rotation_deg + cpl_offset_deg) % 360.0


def verify_rotation_independence(
    before: ComponentRotationState,
    after: ComponentRotationState,
    *,
    mutated_domain: str,
) -> tuple[bool, str | None]:
    """Verify that edits in one domain do not corrupt isolated rotations in other domains."""
    if mutated_domain == "schematic":
        # Schematic changes MUST NOT alter PCB footprint rotation or CPL manufacturing rotation
        if not math.isclose(before.pcb_rotation_deg, after.pcb_rotation_deg, abs_tol=0.01):
            return (
                False,
                f"Cosmetic schematic change mutated PCB physical rotation for {before.reference} "
                f"({before.pcb_rotation_deg}° -> {after.pcb_rotation_deg}°).",
            )
        if not math.isclose(before.cpl_rotation_deg, after.cpl_rotation_deg, abs_tol=0.01):
            return (
                False,
                f"Cosmetic schematic change mutated CPL rotation for {before.reference} "
                f"({before.cpl_rotation_deg}° -> {after.cpl_rotation_deg}°).",
            )
    elif mutated_domain == "pcb":
        # PCB rotation changes MUST NOT alter schematic symbol orientation
        if not math.isclose(
            before.symbol_orientation_deg, after.symbol_orientation_deg, abs_tol=0.01
        ):
            return (
                False,
                f"PCB physical rotation mutated schematic orientation for {before.reference} "
                f"({before.symbol_orientation_deg}° -> {after.symbol_orientation_deg}°).",
            )
    return (True, None)


def extract_symbol_references(sch_text: str) -> frozenset[str]:
    """Extract all symbol references from schematic text."""
    refs = set(re.findall(r'\(property\s+"Reference"\s+"([^"]+)"', sch_text))
    return frozenset(refs)


def extract_sheet_hierarchy(sch_text: str) -> frozenset[str]:
    """Extract sheet names and sheet file paths from schematic text."""
    sheet_names = set(re.findall(r'\(property\s+"Sheetname"\s+"([^"]+)"', sch_text))
    sheet_files = set(re.findall(r'\(property\s+"Sheetfile"\s+"([^"]+)"', sch_text))
    return frozenset(sheet_names | sheet_files)


@dataclass(frozen=True, slots=True)
class CosmeticTransactionPlan:
    """Safe pre-commit plan for cosmetic schematic mutations."""

    fix_name: str
    original_text: str
    mutated_text: str
    changes: list[dict[str, Any]]
    connectivity_preserved: bool
    symbol_inventory_preserved: bool
    hierarchy_preserved: bool
    is_safe_to_apply: bool
    refusal_reason: str | None = None
    before_signature: ConnectivitySignature = field(default_factory=frozenset)
    after_signature: ConnectivitySignature = field(default_factory=frozenset)


def plan_cosmetic_transaction(
    sch_text: str,
    fix_name: str,
    mutator: Callable[[str], tuple[str, list[dict[str, Any]]]],
) -> CosmeticTransactionPlan:
    """Plan a cosmetic mutation in a pure, non-destructive dry-run.

    Verifies that connectivity, symbol references, and sheet hierarchy remain 100% identical.
    """
    try:
        mutated_text, changes = mutator(sch_text)
    except Exception as exc:
        return CosmeticTransactionPlan(
            fix_name=fix_name,
            original_text=sch_text,
            mutated_text=sch_text,
            changes=[],
            connectivity_preserved=False,
            symbol_inventory_preserved=False,
            hierarchy_preserved=False,
            is_safe_to_apply=False,
            refusal_reason=f"Mutator raised exception: {exc}",
        )

    if not changes or sch_text == mutated_text:
        return CosmeticTransactionPlan(
            fix_name=fix_name,
            original_text=sch_text,
            mutated_text=mutated_text,
            changes=changes,
            connectivity_preserved=True,
            symbol_inventory_preserved=True,
            hierarchy_preserved=True,
            is_safe_to_apply=True,
            refusal_reason=None,
        )

    before_sig = _connectivity_signature(sch_text)
    after_sig = _connectivity_signature(mutated_text)
    conn_preserved = before_sig == after_sig

    before_symbols = extract_symbol_references(sch_text)
    after_symbols = extract_symbol_references(mutated_text)
    symbols_preserved = before_symbols == after_symbols

    before_hierarchy = extract_sheet_hierarchy(sch_text)
    after_hierarchy = extract_sheet_hierarchy(mutated_text)
    hierarchy_preserved = before_hierarchy == after_hierarchy

    refusals: list[str] = []
    if not conn_preserved:
        refusals.append(
            "Net connectivity signature changed (pins disconnected, shorted, or net names altered)"
        )
    if not symbols_preserved:
        diff_syms = (before_symbols - after_symbols) | (after_symbols - before_symbols)
        refusals.append(f"Symbol inventory altered: {sorted(diff_syms)}")
    if not hierarchy_preserved:
        refusals.append("Hierarchical sheet structure altered")

    is_safe = conn_preserved and symbols_preserved and hierarchy_preserved
    refusal_reason = "; ".join(refusals) if refusals else None

    return CosmeticTransactionPlan(
        fix_name=fix_name,
        original_text=sch_text,
        mutated_text=mutated_text,
        changes=changes,
        connectivity_preserved=conn_preserved,
        symbol_inventory_preserved=symbols_preserved,
        hierarchy_preserved=hierarchy_preserved,
        is_safe_to_apply=is_safe,
        refusal_reason=refusal_reason,
        before_signature=before_sig,
        after_signature=after_sig,
    )


def apply_cosmetic_transaction(
    sch_text: str,
    plan: CosmeticTransactionPlan,
) -> tuple[str, bool, str]:
    """Safely apply a planned cosmetic mutation, with rollback on invariant failure."""
    if not plan.is_safe_to_apply:
        return (
            sch_text,
            False,
            f"Refused to apply {plan.fix_name}: {plan.refusal_reason or 'invariant violation'}",
        )

    applied_text = plan.mutated_text
    after_sig = _connectivity_signature(applied_text)
    if after_sig != plan.after_signature or after_sig != plan.before_signature:
        return (
            sch_text,
            False,
            f"Rollback: connectivity signature diverged during application of {plan.fix_name}.",
        )

    return (
        applied_text,
        True,
        f"Successfully applied {plan.fix_name} ({len(plan.changes)} changes).",
    )


def _pin1_finding_for_footprint(ref: str, entry: dict[str, Any]) -> PcbFinding | None:
    """Inspect one footprint without mistaking generic silk graphics for electrical evidence."""
    block = str(entry.get("block", ""))
    if not block:
        return None
    pad1_match = re.search(
        r'\(pad\s+"?1"?\s+\S+\s+\S+\s*\(at\s+([-\d.]+)\s+([-\d.]+)(?:\s+([-\d.]+))?\)',
        block,
    )
    if not pad1_match:
        return None
    is_polarized_target = (
        ref.startswith(("U", "D", "Q", "J")) or len(re.findall(r"\(pad\s+", block)) >= 3
    )
    if not is_polarized_target:
        return None
    has_silk_graphics = bool(
        re.search(
            r'\(fp_(?:circle|line|arc|poly)\b[\s\S]*?\(layer\s+"[FB]\.SilkS"\)',
            block,
        )
    )
    if not has_silk_graphics:
        return PcbFinding(
            level="WARN",
            code="pin1_marker_missing",
            message=f"Footprint {ref} has pin 1 but lacks visible pin-1 silkscreen marker.",
            ref=ref,
            x=float(entry.get("x_mm", 0.0) or 0.0),
            y=float(entry.get("y_mm", 0.0) or 0.0),
        )
    ref_box = _reference_silk_box(ref, entry)
    if ref_box is None:
        return None
    p1_dx = float(pad1_match.group(1))
    p1_dy = float(pad1_match.group(2))
    foot_rot = float(entry.get("rotation", 0) or 0)
    rp1_dx, rp1_dy = _rotate(p1_dx, p1_dy, foot_rot)
    p1_abs_x = float(entry.get("x_mm", 0.0) or 0.0) + rp1_dx
    p1_abs_y = float(entry.get("y_mm", 0.0) or 0.0) + rp1_dy
    if not ref_box.contains_point(p1_abs_x, p1_abs_y):
        return None
    return PcbFinding(
        level="WARN",
        code="pin1_marker_occluded",
        message=f"Footprint {ref} silkscreen reference text occludes pin-1 marker.",
        ref=ref,
        x=p1_abs_x,
        y=p1_abs_y,
    )


def detect_pin1_marker_visibility(footprints: FootprintMap) -> list[PcbFinding]:
    """Detect missing or occluded pin-1 markers on polarized and multi-pin parts."""
    findings: list[PcbFinding] = []
    for ref, entry in sorted(footprints.items()):
        finding = _pin1_finding_for_footprint(ref, entry)
        if finding is not None:
            findings.append(finding)
    return findings


def _visual_location(position: object) -> tuple[float, float] | None:
    if not isinstance(position, (list, tuple)) or len(position) < 2:
        return None
    try:
        return float(position[0]), float(position[1])
    except (ValueError, TypeError):
        return None


def _schematic_visual_finding(
    idx: int, raw: object, *, strict_policy: bool
) -> ReviewFinding | None:
    if not isinstance(raw, dict):
        return None
    level = str(raw.get("level", "INFO")).upper()
    code = str(raw.get("code", "unknown"))
    is_readability_defect = code in {
        "label_collision",
        "symbol_overlap",
        "text_overlap",
        "offsheet_box",
        "offsheet_symbol",
    }
    if is_readability_defect:
        severity = "error" if strict_policy else "warning"
    else:
        severity = "warning" if strict_policy and level == "WARN" else "info"
    if severity == "info":
        return None
    return ReviewFinding(
        id=f"SCH_VIS_{idx + 1:03d}",
        rule_id=SCHEMATIC_VISUAL_RULE,
        rule_revision=1,
        severity=severity,
        object_ref=str(raw.get("ref", "")),
        location_mm=_visual_location(raw.get("position")),
        description=str(raw.get("message", "")),
        metadata={
            "defect_category": "readability" if is_readability_defect else "cosmetic_style",
            "electrical_defect": False,
            "code": code,
        },
    )


def evaluate_schematic_visual_quality(
    context: ReviewContext,
    sch_text: str | None = None,
) -> ReviewAssessment:
    """Evaluate schematic readability and cosmetic quality without electrical conflation."""
    if sch_text is None:
        return ReviewAssessment(
            rule_id=SCHEMATIC_VISUAL_RULE,
            rule_revision=1,
            status=AssessmentStatus.BLOCKED,
            method=EvaluationMethod.HEURISTIC,
            summary="Schematic text missing; cannot evaluate schematic visual quality.",
            missing_inputs=["sch_text"],
            metadata={
                "defect_category": "cosmetic_style",
                "electrical_defect": False,
            },
        )

    stripped = sch_text.strip()
    if not stripped:
        return ReviewAssessment(
            rule_id=SCHEMATIC_VISUAL_RULE,
            rule_revision=1,
            status=AssessmentStatus.NOT_ASSESSED,
            method=EvaluationMethod.HEURISTIC,
            summary="Schematic text is empty; visual quality cannot be assessed.",
            missing_inputs=["schematic_symbols", "schematic_wires"],
            metadata={
                "defect_category": "cosmetic_style",
                "electrical_defect": False,
                "empty_sheet": True,
                "symbol_count": 0,
                "wire_count": 0,
            },
        )

    symbols = parse_symbols(sch_text)
    wires = parse_wires(sch_text)

    # Empty sheet check: zero symbols and zero wires must NOT pass
    if len(symbols) == 0 and len(wires) == 0:
        return ReviewAssessment(
            rule_id=SCHEMATIC_VISUAL_RULE,
            rule_revision=1,
            status=AssessmentStatus.NOT_ASSESSED,
            method=EvaluationMethod.HEURISTIC,
            summary=(
                "Schematic contains zero symbols and zero wires (empty sheet); "
                "visual quality cannot be assessed."
            ),
            missing_inputs=["schematic_symbols", "schematic_wires"],
            metadata={
                "defect_category": "cosmetic_style",
                "electrical_defect": False,
                "empty_sheet": True,
                "symbol_count": 0,
                "wire_count": 0,
            },
        )

    qa_report = run_cosmetic_qa(sch_text)
    raw_findings = qa_report.get("findings", [])
    if not isinstance(raw_findings, list):
        raw_findings = []

    review_findings: list[ReviewFinding] = []
    strict_policy = bool(context.explicit_requirements.get("strict_schematic_cosmetics", False))

    for idx, raw in enumerate(raw_findings):
        finding = _schematic_visual_finding(idx, raw, strict_policy=strict_policy)
        if finding is not None:
            review_findings.append(finding)

    has_error = any(rf.severity == "error" for rf in review_findings)
    has_warning = any(rf.severity == "warning" for rf in review_findings)

    if has_error:
        status = AssessmentStatus.FAIL
        summary = (
            f"Schematic visual QA detected {len(review_findings)} defects violating visual policy."
        )
    elif has_warning:
        status = AssessmentStatus.WARN
        summary = (
            f"Schematic visual QA identified {len(review_findings)} readability/style warnings."
        )
    else:
        status = AssessmentStatus.PASS
        summary = (
            f"Schematic visual QA passed with cosmetic score "
            f"{qa_report.get('cosmetic_score', 100.0)}/100."
        )

    return ReviewAssessment(
        rule_id=SCHEMATIC_VISUAL_RULE,
        rule_revision=1,
        status=status,
        method=EvaluationMethod.HEURISTIC,
        summary=summary,
        findings=review_findings,
        metadata={
            "defect_category": "cosmetic_style",
            "electrical_defect": False,
            "cosmetic_score": qa_report.get("cosmetic_score", 100.0),
            "symbol_count": len(symbols),
            "wire_count": len(wires),
            "penalties_by_category": qa_report.get("penalties_by_category", {}),
        },
    )


def _coerce_readability_findings(raw: object) -> list[PcbFinding]:
    if not isinstance(raw, list):
        return []
    findings: list[PcbFinding] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        position = item.get("position")
        location = (
            (float(position[0]), float(position[1]))
            if isinstance(position, (list, tuple)) and len(position) >= 2
            else (None, None)
        )
        findings.append(
            PcbFinding(
                level=str(item.get("level", "WARN")),
                code=str(item.get("code", "unknown")),
                message=str(item.get("message", "")),
                ref=str(item.get("ref", "")),
                x=location[0],
                y=location[1],
            )
        )
    return findings


def _pcb_visual_finding(
    idx: int, finding: PcbFinding, *, strict_policy: bool
) -> ReviewFinding | None:
    if finding.level == "INFO" and not strict_policy:
        return None
    if finding.level in {"FAIL", "WARN"}:
        severity = "error" if strict_policy else "warning"
    else:
        severity = "warning" if strict_policy else "info"
    if severity == "info":
        return None
    location = (finding.x, finding.y) if finding.x is not None and finding.y is not None else None
    return ReviewFinding(
        id=f"PCB_VIS_{idx + 1:03d}",
        rule_id=PCB_VISUAL_RULE,
        rule_revision=1,
        severity=severity,
        object_ref=finding.ref,
        location_mm=location,
        description=finding.message,
        metadata={
            "defect_category": "cosmetic_style",
            "electrical_defect": False,
            "code": finding.code,
        },
    )


def evaluate_pcb_visual_quality(
    context: ReviewContext,
    *,
    footprints: FootprintMap | None = None,
    bounds: tuple[float, float, float, float] | None = None,
) -> ReviewAssessment:
    """Evaluate PCB silkscreen presentation, component bounds, and pin-1 marker visibility."""
    if footprints is None:
        return ReviewAssessment(
            rule_id=PCB_VISUAL_RULE,
            rule_revision=1,
            status=AssessmentStatus.BLOCKED,
            method=EvaluationMethod.HEURISTIC,
            summary="PCB footprint data missing; cannot evaluate PCB visual presentation.",
            missing_inputs=["board_footprints"],
            metadata={
                "defect_category": "cosmetic_style",
                "electrical_defect": False,
            },
        )

    if len(footprints) == 0:
        return ReviewAssessment(
            rule_id=PCB_VISUAL_RULE,
            rule_revision=1,
            status=AssessmentStatus.NOT_ASSESSED,
            method=EvaluationMethod.HEURISTIC,
            summary=(
                "PCB contains zero footprints (empty board); visual presentation "
                "cannot be assessed."
            ),
            missing_inputs=["board_footprints"],
            metadata={
                "defect_category": "cosmetic_style",
                "electrical_defect": False,
                "empty_board": True,
                "footprint_count": 0,
            },
        )

    readability_rep = run_pcb_readability(footprints, bounds)
    pin1_findings = detect_pin1_marker_visibility(footprints)

    all_findings = _coerce_readability_findings(readability_rep.get("findings", []))
    all_findings.extend(pin1_findings)
    review_findings: list[ReviewFinding] = []
    strict_policy = bool(context.explicit_requirements.get("strict_pcb_presentation", False))
    for idx, item in enumerate(all_findings):
        finding = _pcb_visual_finding(idx, item, strict_policy=strict_policy)
        if finding is not None:
            review_findings.append(finding)

    has_error = any(rf.severity == "error" for rf in review_findings)
    has_warning = any(rf.severity == "warning" for rf in review_findings)

    if has_error:
        status = AssessmentStatus.FAIL
        summary = (
            f"PCB visual presentation detected {len(review_findings)} defects violating policy."
        )
    elif has_warning:
        status = AssessmentStatus.WARN
        summary = (
            f"PCB visual presentation identified {len(review_findings)} presentation warnings."
        )
    else:
        status = AssessmentStatus.PASS
        summary = (
            "PCB visual presentation passed "
            "(silkscreen, pin-1 markers, and component bounds clean)."
        )

    return ReviewAssessment(
        rule_id=PCB_VISUAL_RULE,
        rule_revision=1,
        status=status,
        method=EvaluationMethod.HEURISTIC,
        summary=summary,
        findings=review_findings,
        metadata={
            "defect_category": "cosmetic_style",
            "electrical_defect": False,
            "footprint_count": len(footprints),
        },
    )


def evaluate_visual_quality(
    context: ReviewContext,
    sch_text: str | None = None,
    *,
    footprints: FootprintMap | None = None,
    bounds: tuple[float, float, float, float] | None = None,
) -> list[ReviewAssessment]:
    """Unified entrypoint for assessing schematic and PCB visual quality."""
    assessments: list[ReviewAssessment] = []
    if sch_text is not None or "schematic_symbols" in context.explicit_requirements:
        assessments.append(evaluate_schematic_visual_quality(context, sch_text))
    if (
        footprints is not None
        or bounds is not None
        or "board_footprints" in context.explicit_requirements
    ):
        assessments.append(
            evaluate_pcb_visual_quality(context, footprints=footprints, bounds=bounds)
        )
    return assessments
