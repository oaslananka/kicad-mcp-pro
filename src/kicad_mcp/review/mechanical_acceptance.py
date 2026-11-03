"""Connector mechanical acceptance and mating orientation review (#1393, T6).

Principles:
1. Validates connector mating direction and board-edge registration against Edge.Cuts.
2. Fails closed on missing required mechanical intent: any unannotated connector footprint
   on the board without a ConnectorMatingSpec yields FAIL, blocking manufacturing release.
3. Checks outward mating normal, datum offset, and finite Edge.Cuts segment bounds.
4. Distinguishes 2-D mating datum alignment from 3-D plug/screwdriver swept volume.
   Warns when 3-D models are unavailable.
5. Invariant: Electrical PASS (ERC/DRC) does NOT override mechanical FAIL.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from ..models.intent import ConnectorMatingSpec
from ..models.review import (
    AssessmentStatus,
    EvaluationMethod,
    ReviewAssessment,
    ReviewContext,
    ReviewFinding,
)
from ..project.connector_mating_review import evaluate_connector_mating
from ..tools.board_file import _board_frame_mm, _parse_board_footprint_blocks
from ..utils.sexpr import _extract_block
from .stage_gate import ReviewStage, StageGateDecision


def check_rectangular_outline(
    pcb_text: str,
    frame: tuple[float, float, float, float],
) -> bool:
    """Check if Edge.Cuts consists solely of a single valid gr_rect."""
    min_x, min_y, max_x, max_y = frame
    if max_x <= min_x or max_y <= min_y:
        return False
    primitives: list[str] = []
    for found in re.finditer(r"\(gr_(?:rect|line|arc|circle|poly|curve)\b", pcb_text):
        block, _ = _extract_block(pcb_text, found.start())
        if block and '(layer "Edge.Cuts")' in block:
            primitives.append(found.group().removeprefix("("))
    return primitives == ["gr_rect"]


def is_connector_footprint(ref: str, entry: Mapping[str, Any]) -> bool:
    """Identify whether a footprint is a connector requiring mechanical mating intent."""
    if ref.startswith("J"):
        return True
    name = str(entry.get("name", "")).lower()
    connector_keywords = (
        "connector",
        "terminalblock",
        "usb",
        "header",
        "jack",
        "socket",
        "receptacle",
        "plug",
    )
    return any(kw in name for kw in connector_keywords)


def evaluate_connector_mating_orientation(
    context: ReviewContext,
    *,
    pcb_text: str | None = None,
    specs: list[ConnectorMatingSpec] | None = None,
    footprints: Mapping[str, Mapping[str, Any]] | None = None,
    frame: tuple[float, float, float, float] | None = None,
    rectangular_outline_verified: bool | None = None,
) -> ReviewAssessment:
    """Evaluate connector mechanical mating direction, datum alignment, and 3-D intent."""
    # Resolve footprints from pcb_text if not explicitly passed
    resolved_footprints: dict[str, dict[str, Any]] = {}
    if footprints is not None:
        resolved_footprints = {k: dict(v) for k, v in footprints.items()}
    elif pcb_text is not None:
        resolved_footprints = _parse_board_footprint_blocks(pcb_text)

    # Resolve frame
    resolved_frame = frame
    if resolved_frame is None and pcb_text is not None:
        resolved_frame = _board_frame_mm(pcb_text, resolved_footprints)

    if not resolved_footprints or resolved_frame is None:
        return ReviewAssessment(
            rule_id="mechanical.connector_mating_orientation",
            rule_revision=1,
            status=AssessmentStatus.BLOCKED,
            method=EvaluationMethod.ANALYTICAL,
            summary="Board outline or footprint data missing; cannot evaluate connector mating.",
            missing_inputs=["connector_mating_specs", "board_outline"],
            metadata={"defect_category": "mechanical"},
        )

    # Frame bounds alone do not prove a rectangular Edge.Cuts outline.
    missing_outline_evidence = rectangular_outline_verified is None and pcb_text is None
    if rectangular_outline_verified is None:
        rectangular_outline_verified = (
            check_rectangular_outline(pcb_text, resolved_frame) if pcb_text is not None else False
        )

    # Resolve specs
    resolved_specs = specs
    if resolved_specs is None:
        raw_specs = context.explicit_requirements.get("connector_mating_specs")
        if isinstance(raw_specs, list):
            resolved_specs = []
            for item in raw_specs:
                if isinstance(item, ConnectorMatingSpec):
                    resolved_specs.append(item)
                elif isinstance(item, dict):
                    resolved_specs.append(ConnectorMatingSpec.model_validate(item))
        else:
            resolved_specs = []

    # Find all connector footprints
    connector_map = {
        ref: fp for ref, fp in resolved_footprints.items() if is_connector_footprint(ref, fp)
    }

    if not connector_map:
        return ReviewAssessment(
            rule_id="mechanical.connector_mating_orientation",
            rule_revision=1,
            status=AssessmentStatus.NOT_APPLICABLE,
            method=EvaluationMethod.ANALYTICAL,
            summary="No connector footprints found on board; mating evaluation not applicable.",
            metadata={"defect_category": "mechanical", "connector_count": 0},
        )

    findings: list[ReviewFinding] = []
    finding_idx = 1

    # Rule: Fail closed on unannotated connectors
    spec_map = {s.ref: s for s in resolved_specs}
    unannotated_refs = sorted(set(connector_map.keys()) - set(spec_map.keys()))

    for un_ref in unannotated_refs:
        fp_name = str(connector_map[un_ref].get("name", "Unknown"))
        px = connector_map[un_ref].get("x_mm")
        py = connector_map[un_ref].get("y_mm")
        pos = (float(px), float(py)) if px is not None and py is not None else None
        findings.append(
            ReviewFinding(
                id=f"MEC_MATING_{finding_idx:03d}",
                rule_id="mechanical.connector_mating_orientation",
                rule_revision=1,
                severity="error",
                object_ref=un_ref,
                location_mm=pos,
                description=(
                    f"Connector '{un_ref}' ({fp_name}) lacks declared mechanical mating intent. "
                    "Mating direction, datum alignment, and cable clearance are unverified."
                ),
                remediation=(
                    f"Declare ConnectorMatingSpec for '{un_ref}' with intended board edge, "
                    "mating datum coordinates, and outward normal."
                ),
                metadata={"defect_category": "mechanical", "unannotated_connector": True},
            )
        )
        finding_idx += 1

    if missing_outline_evidence and not unannotated_refs:
        return ReviewAssessment(
            rule_id="mechanical.connector_mating_orientation",
            rule_revision=1,
            status=AssessmentStatus.NOT_ASSESSED,
            method=EvaluationMethod.ANALYTICAL,
            summary="A board frame cannot establish a verified rectangular Edge.Cuts outline.",
            missing_inputs=["verified_rectangular_edge_cuts"],
            metadata={"defect_category": "mechanical", "connector_count": len(connector_map)},
        )

    # Evaluate each declared spec
    for spec in resolved_specs:
        fp_entry = resolved_footprints.get(spec.ref)
        problems = evaluate_connector_mating(
            spec,
            fp_entry,
            resolved_frame,
            rectangular_outline_verified=rectangular_outline_verified,
        )
        for prob in problems:
            px = fp_entry.get("x_mm") if fp_entry else None
            py = fp_entry.get("y_mm") if fp_entry else None
            pos = (float(px), float(py)) if px is not None and py is not None else None
            findings.append(
                ReviewFinding(
                    id=f"MEC_MATING_{finding_idx:03d}",
                    rule_id="mechanical.connector_mating_orientation",
                    rule_revision=1,
                    severity="error",
                    object_ref=spec.ref,
                    location_mm=pos,
                    description=prob,
                    remediation=(
                        f"Realign connector '{spec.ref}' mating datum with {spec.edge} Edge.Cuts "
                        "or rotate footprint to align outward mating normal."
                    ),
                    metadata={"defect_category": "mechanical", "alignment_failure": True},
                )
            )
            finding_idx += 1

        # Check 3D swept volume / model availability
        if not context.has_3d_models:
            findings.append(
                ReviewFinding(
                    id=f"MEC_MATING_{finding_idx:03d}",
                    rule_id="mechanical.connector_mating_orientation",
                    rule_revision=1,
                    severity="warning",
                    object_ref=spec.ref,
                    description=(
                        f"Connector '{spec.ref}' 3D model is unavailable; physical swept volume "
                        "and enclosure plug clearance cannot be verified."
                    ),
                    remediation=(
                        "Attach valid 3D STEP/WRL model to footprint for swept-volume verification."
                    ),
                    metadata={"defect_category": "mechanical", "missing_3d_model": True},
                )
            )
            finding_idx += 1

    has_error = any(f.severity == "error" for f in findings)
    has_warning = any(f.severity == "warning" for f in findings)

    if has_error:
        status = AssessmentStatus.FAIL
        summary = (
            f"Connector mechanical mating evaluation failed with {len(findings)} issues "
            f"(blocking manufacturing release)."
        )
    elif has_warning:
        status = AssessmentStatus.WARN
        summary = (
            f"Connector 2-D mating alignment passed nominally, with {len(findings)} warnings "
            "(3-D swept volume unverified)."
        )
    else:
        status = AssessmentStatus.PASS
        summary = (
            f"Connector mechanical mating verified for {len(resolved_specs)} connectors "
            f"along Edge.Cuts."
        )

    return ReviewAssessment(
        rule_id="mechanical.connector_mating_orientation",
        rule_revision=1,
        status=status,
        method=EvaluationMethod.ANALYTICAL,
        summary=summary,
        findings=findings,
        metadata={
            "defect_category": "mechanical",
            "connector_count": len(connector_map),
            "annotated_spec_count": len(resolved_specs),
            "unannotated_count": len(unannotated_refs),
        },
    )


def evaluate_mechanical_stage_gate(
    mechanical_assessment: ReviewAssessment,
    electrical_assessment: ReviewAssessment | None = None,
    stage: ReviewStage = ReviewStage.PRODUCTION_ACCEPTANCE,
) -> StageGateDecision:
    """Evaluate gate readiness; electrical PASS cannot override mechanical FAIL."""
    if mechanical_assessment.status == AssessmentStatus.FAIL:
        blocking = [
            f"Mechanical failure on {f.object_ref}: {f.description}"
            for f in mechanical_assessment.findings
            if f.severity == "error"
        ]
        return StageGateDecision(
            stage=stage,
            approved=False,
            summary=(
                "Manufacturing gate blocked: mechanical connector acceptance failed. "
                "Electrical PASS cannot override mechanical failure."
            ),
            blocking_reasons=blocking or ["Connector mechanical mating direction or datum failed."],
        )

    if mechanical_assessment.status in {AssessmentStatus.BLOCKED, AssessmentStatus.NOT_ASSESSED}:
        return StageGateDecision(
            stage=stage,
            approved=False,
            summary="Manufacturing gate blocked: mechanical connector acceptance is unassessed.",
            blocking_reasons=["Mechanical connector intent has not been assessed."],
        )

    if electrical_assessment is not None and electrical_assessment.status == AssessmentStatus.FAIL:
        return StageGateDecision(
            stage=stage,
            approved=False,
            summary="Manufacturing gate blocked: electrical checks failed.",
            blocking_reasons=[f.description for f in electrical_assessment.findings],
        )

    return StageGateDecision(
        stage=stage,
        approved=True,
        summary="Manufacturing stage gate approved for mechanical and electrical alignment.",
    )
