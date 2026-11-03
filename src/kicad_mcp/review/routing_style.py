"""Context-aware routing style assessment (#1581, T3).

Evaluates routing corner style against explicit project policy without treating
a generic 90-degree corner as an electrical failure.

Principles:
- Ordinary board without declared style constraint: preference is advisory (WARN).
- Explicit style policy (strict_45, chamfer_required): reports policy violation (FAIL),
  distinctly marked as cosmetic_style rather than electrical / SI defect.
- Orthogonal routing permitted (e.g. orthogonal_allowed): reports NOT_APPLICABLE.
- Distinguishes true corners from T-junctions, arcs, pad transitions, and multi-segment geometry.
- Ambiguous or unsupported geometry yields NOT_ASSESSED.
- Never maps style FAIL into electrical defect.
"""

from __future__ import annotations

import re
from typing import Any

from ..models.review import (
    AssessmentStatus,
    EvaluationMethod,
    ReviewAssessment,
    ReviewContext,
    ReviewFinding,
)
from ..tools.validation import (
    _pcb_track_arcs_from_text,
    _pcb_track_segments_from_text,
    _PcbTrackArc,
    _PcbTrackSegment,
    _route_90_degree_corners,
)


def _detect_ambiguous_geometry(pcb_text: str, segments: list[_PcbTrackSegment]) -> bool:
    """Detect corrupted coordinates, unparseable segment blocks, or unsupported curves."""
    raw_segment_count = len(re.findall(r"\(\s*segment\b", pcb_text))
    if raw_segment_count > len(segments):
        return True
    if re.search(r"\(\s*(curve|bezier)\b[^)]*\.Cu", pcb_text):
        return True
    return False


def _parse_corner_line(line: str) -> tuple[str, str, float, float] | None:
    """Parse corner description 'NET on LAYER has a 90° corner at (X, Y)'."""
    pattern = r"^(.*) on (.*) has a 90° corner at \(([-0-9.]+), ([-0-9.]+)\)$"
    match = re.match(pattern, line)
    if not match:
        return None
    net, layer, x_str, y_str = match.groups()
    return (net, layer, float(x_str), float(y_str))


def evaluate_routing_style(
    context: ReviewContext,
    pcb_text: str | None = None,
    *,
    segments: list[_PcbTrackSegment] | None = None,
    arcs: list[_PcbTrackArc] | None = None,
    min_segment_length_mm: float = 0.25,
) -> ReviewAssessment:
    """Evaluate PCB routing corners against project style policy in a context-aware manner."""
    if pcb_text is None and segments is None:
        return ReviewAssessment(
            rule_id="routing.orthogonal_corners",
            rule_revision=1,
            status=AssessmentStatus.BLOCKED,
            method=EvaluationMethod.HEURISTIC,
            summary="PCB track data missing; cannot evaluate route corner style.",
            missing_inputs=["pcb_text"],
            metadata={
                "defect_category": "cosmetic_style",
                "electrical_defect": False,
            },
        )

    if context.declared_routing_style == "orthogonal_allowed":
        return ReviewAssessment(
            rule_id="routing.orthogonal_corners",
            rule_revision=1,
            status=AssessmentStatus.NOT_APPLICABLE,
            method=EvaluationMethod.HEURISTIC,
            summary="Project explicitly permits orthogonal routing; 90-degree corners are allowed.",
            metadata={
                "defect_category": "cosmetic_style",
                "electrical_defect": False,
                "policy": "orthogonal_allowed",
            },
        )

    if segments is None and pcb_text is not None:
        segments = _pcb_track_segments_from_text(pcb_text)
    if arcs is None and pcb_text is not None:
        arcs = _pcb_track_arcs_from_text(pcb_text)

    if pcb_text is not None and segments is not None:
        if _detect_ambiguous_geometry(pcb_text, segments):
            return ReviewAssessment(
                rule_id="routing.orthogonal_corners",
                rule_revision=1,
                status=AssessmentStatus.NOT_ASSESSED,
                method=EvaluationMethod.HEURISTIC,
                summary=(
                    "Unsupported or ambiguous track geometry detected in PCB; "
                    "corner style cannot be deterministically evaluated."
                ),
                missing_inputs=["geometry_resolution"],
                metadata={
                    "defect_category": "cosmetic_style",
                    "electrical_defect": False,
                    "unsupported_geometry": True,
                },
            )

    scanned_segments = segments or []
    scanned_arcs = arcs or []
    corners = _route_90_degree_corners(
        scanned_segments,
        min_segment_length_mm=min_segment_length_mm,
        arcs=scanned_arcs,
    )

    if not corners:
        return ReviewAssessment(
            rule_id="routing.orthogonal_corners",
            rule_revision=1,
            status=AssessmentStatus.PASS,
            method=EvaluationMethod.HEURISTIC,
            summary=(
                f"All evaluated route corners comply with 45°/rounded geometry style "
                f"({len(scanned_segments)} segments scanned)."
            ),
            metadata={
                "defect_category": "cosmetic_style",
                "electrical_defect": False,
                "corner_count": 0,
            },
        )

    is_strict = context.declared_routing_style in (
        "strict_45",
        "require_chamfer",
        "chamfer_required",
    )
    status = AssessmentStatus.FAIL if is_strict else AssessmentStatus.WARN
    severity = "error" if is_strict else "warning"

    findings: list[ReviewFinding] = []
    for corner in corners:
        parsed = _parse_corner_line(corner)
        if parsed:
            net, layer, x_mm, y_mm = parsed
            loc = (x_mm, y_mm)
            loc_str = f"{x_mm:.3f}_{y_mm:.3f}"
            obj_ref = f"{net}:{layer}"
        else:
            net, layer = None, None
            loc = None
            x_mm, y_mm = 0.0, 0.0
            loc_str = str(len(findings))
            obj_ref = "route"

        fid = f"corner-{net or 'net'}-{layer or 'layer'}-{loc_str}"[:64]
        desc = (
            f"90° corner on net '{net}' ({layer}) at ({x_mm:.3f}, {y_mm:.3f}) violates "
            f"explicit policy '{context.declared_routing_style}'."
            if is_strict
            else f"Advisory: 90° corner on net '{net}' ({layer}) at ({x_mm:.3f}, {y_mm:.3f}). "
            "Style preference only; not an electrical failure."
        )
        finding_meta: dict[str, Any] = {
            "defect_category": "cosmetic_style",
            "electrical_defect": False,
            "is_advisory": not is_strict,
        }
        if context.declared_routing_style:
            finding_meta["policy"] = context.declared_routing_style

        findings.append(
            ReviewFinding(
                id=fid,
                rule_id="routing.orthogonal_corners",
                rule_revision=1,
                severity=severity,
                object_ref=obj_ref,
                net=net,
                layer=layer,
                location_mm=loc,
                description=desc,
                measured_value=1,
                expected_value=0,
                units="count",
                remediation=(
                    "Chamfer 90-degree corner to 45-degree angle to satisfy explicit policy."
                    if is_strict
                    else (
                        "Consider chamfering to 45° for professional appearance if routing "
                        "density permits."
                    )
                ),
                metadata=finding_meta,
            )
        )

    summary = (
        f"PCB routing contains {len(corners)} right-angle corner(s) violating explicit "
        f"project policy '{context.declared_routing_style}'."
        if is_strict
        else (
            f"PCB routing contains {len(corners)} right-angle corner(s); advisory "
            "preference for 45° chamfers on ordinary boards."
        )
    )

    assessment_meta: dict[str, Any] = {
        "defect_category": "cosmetic_style",
        "electrical_defect": False,
        "is_advisory": not is_strict,
        "corner_count": len(corners),
        "segments_scanned": len(scanned_segments),
        "arcs_scanned": len(scanned_arcs),
    }
    if context.declared_routing_style:
        assessment_meta["declared_routing_style"] = context.declared_routing_style

    return ReviewAssessment(
        rule_id="routing.orthogonal_corners",
        rule_revision=1,
        status=status,
        method=EvaluationMethod.HEURISTIC,
        summary=summary,
        findings=findings,
        metadata=assessment_meta,
    )
