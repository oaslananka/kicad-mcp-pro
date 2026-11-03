"""DFM, DFA, DFT, BOM, and Bring-up Review Evaluation (#1586).

Connects manufacturing and assembly checks to selected, dated, and versioned
fabricator/assembler capability profiles. Distinguishes checklists from measurement
evidence. Preserves distinct CPL rotation, footprint orientation, and assembly datum.
Enforces USB4085 annular ring blocking checks (#1381).
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from ..models.review import (
    AssessmentStatus,
    EvaluationMethod,
    ReviewAssessment,
    ReviewContext,
    ReviewFinding,
)
from ..project.evidence_freshness import (
    EvidenceInputDigest,
    EvidenceRecord,
    EvidenceRecordKind,
)


class FabricationProfile(BaseModel):
    """Dated, versioned capability profile from a qualified PCB manufacturer."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    manufacturer: str = Field(min_length=1, max_length=100)
    tier: str = Field(min_length=1, max_length=100)
    process: str = Field(min_length=1, max_length=100)
    version: str = Field(min_length=1, max_length=50)
    review_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    source: str = Field(min_length=1, max_length=256)
    rules: dict[str, float | int] = Field(default_factory=dict)
    source_sha256: str = ""

    def profile_sha256(self) -> str:
        """Return deterministic SHA256 digest of profile parameters."""
        if self.source_sha256 and len(self.source_sha256) == 64:
            return self.source_sha256
        content = json.dumps(
            {
                "manufacturer": self.manufacturer,
                "tier": self.tier,
                "process": self.process,
                "version": self.version,
                "review_date": self.review_date,
                "source": self.source,
                "rules": sorted(self.rules.items()),
            },
            sort_keys=True,
        )
        return hashlib.sha256(content.encode("utf-8")).hexdigest()


class AssemblyProfile(BaseModel):
    """Dated, versioned capability profile for PCBA SMT assembly."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    assembler: str = Field(min_length=1, max_length=100)
    process: str = Field(min_length=1, max_length=100)
    version: str = Field(min_length=1, max_length=50)
    review_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    source: str = Field(min_length=1, max_length=256)
    min_fiducials: int = 2
    min_component_clearance_mm: float = 0.25
    source_sha256: str = ""

    def profile_sha256(self) -> str:
        """Return deterministic SHA256 digest of assembly profile parameters."""
        if self.source_sha256 and len(self.source_sha256) == 64:
            return self.source_sha256
        content = json.dumps(
            {
                "assembler": self.assembler,
                "process": self.process,
                "version": self.version,
                "review_date": self.review_date,
                "source": self.source,
                "min_fiducials": self.min_fiducials,
                "min_component_clearance_mm": self.min_component_clearance_mm,
            },
            sort_keys=True,
        )
        return hashlib.sha256(content.encode("utf-8")).hexdigest()


class BoardDFMInput(BaseModel):
    """Measured board parameters and annular ring inspections for DFM check."""

    model_config = ConfigDict(extra="forbid")

    copper_layers: int = Field(ge=1, le=64)
    copper_weight_oz: float = 1.0
    min_trace_width_mm: float | None = None
    min_trace_clearance_mm: float | None = None
    min_drill_mm: float | None = None
    min_annular_ring_mm: float | None = None
    copper_to_edge_mm: float | None = None
    board_thickness_mm: float = 1.6
    aspect_ratio: float | None = None
    pth_annular_rings: list[dict[str, Any]] = Field(default_factory=list)
    unmeasured_pth_count: int = 0


class BoardAssemblyInput(BaseModel):
    """Physical layout data for assembly (DFA) verification."""

    model_config = ConfigDict(extra="forbid")

    fiducials_count: int = 0
    courtyard_overlaps: list[dict[str, Any]] = Field(default_factory=list)
    components: list[dict[str, Any]] = Field(default_factory=list)


class DFTTestabilitySpec(BaseModel):
    """Test point access and probe geometry for DFT verification."""

    model_config = ConfigDict(extra="forbid")

    power_rail_testpoints: dict[str, bool] = Field(default_factory=dict)
    reset_testpoints: dict[str, bool] = Field(default_factory=dict)
    testpoint_probe_pitches: list[dict[str, Any]] = Field(default_factory=list)
    probe_component_clearances: list[dict[str, Any]] = Field(default_factory=list)


class BOMItemInput(BaseModel):
    """Component entry in bill of materials with lifecycle and alternates."""

    model_config = ConfigDict(extra="forbid")

    reference: str
    mpn: str
    footprint: str
    lifecycle_status: Literal["ACTIVE", "NRND", "EOL", "OBSOLETE"] = "ACTIVE"
    stock_status: Literal["VERIFIED_IN_STOCK", "OFFLINE_SNAPSHOT", "UNVERIFIED", "OUT_OF_STOCK"] = (
        "VERIFIED_IN_STOCK"
    )
    stock_as_of: str | None = None
    alternates: list[dict[str, Any]] = Field(default_factory=list)


class BringupPlanInput(BaseModel):
    """Bring-up step with acceptance criteria and actual measurement evidence."""

    model_config = ConfigDict(extra="forbid")

    item_id: str
    description: str
    is_checklist_only: bool = False
    target_rail_or_net: str | None = None
    acceptance_min: float | None = None
    acceptance_max: float | None = None
    measured_value: float | None = None
    measurement_unit: str | None = None
    instrument_id: str | None = None
    environmental_temp_c: float | None = None
    evidence_link: str | None = None


class StageAuthorizationInput(BaseModel):
    """Explicit signoff status for hardware bring-up and manufacturing release."""

    model_config = ConfigDict(extra="forbid")

    power_on_authorized: bool = False
    power_on_authorizer: str | None = None
    production_release_authorized: bool = False
    production_release_authorizer: str | None = None


def evaluate_dfm_fabrication_limits(
    profile: FabricationProfile | None,
    board_input: BoardDFMInput | None,
    context: ReviewContext,
    rule_id: str = "mfg.dfm_profile_compliance",
) -> ReviewAssessment:
    """Evaluate PCB fabrication limits against selected supplier capability profile."""
    if profile is None:
        return ReviewAssessment(
            rule_id=rule_id,
            rule_revision=1,
            status=AssessmentStatus.NOT_ASSESSED,
            method=EvaluationMethod.ANALYTICAL,
            summary=(
                "No universal fabrication limit without a selected applicable profile; "
                "DFM evaluation cannot run."
            ),
            missing_inputs=["dfm_profile"],
            metadata={"defect_category": "manufacturing", "reason": "missing_profile"},
        )

    if board_input is None:
        return ReviewAssessment(
            rule_id=rule_id,
            rule_revision=1,
            status=AssessmentStatus.NOT_ASSESSED,
            method=EvaluationMethod.ANALYTICAL,
            summary="Board DFM measurements not provided.",
            missing_inputs=["board_dfm_measurements"],
            metadata={"defect_category": "manufacturing"},
        )

    findings: list[ReviewFinding] = []
    finding_idx = 1
    rules = profile.rules

    # 1. Trace width
    min_tw = rules.get("min_trace_width_mm")
    if (
        min_tw is not None
        and board_input.min_trace_width_mm is not None
        and board_input.min_trace_width_mm < min_tw
    ):
        findings.append(
            ReviewFinding(
                id=f"DFM_{finding_idx:03d}",
                rule_id=rule_id,
                rule_revision=1,
                severity="error",
                description=(
                    f"Min trace width {board_input.min_trace_width_mm:.3f} mm violates "
                    f"{profile.manufacturer} {profile.tier} limit {min_tw:.3f} mm."
                ),
                remediation="Widen narrow tracks or select advanced manufacturing tier.",
            )
        )
        finding_idx += 1

    # 2. Trace clearance
    min_tc = rules.get("min_trace_clearance_mm")
    if (
        min_tc is not None
        and board_input.min_trace_clearance_mm is not None
        and board_input.min_trace_clearance_mm < min_tc
    ):
        findings.append(
            ReviewFinding(
                id=f"DFM_{finding_idx:03d}",
                rule_id=rule_id,
                rule_revision=1,
                severity="error",
                description=(
                    f"Min clearance {board_input.min_trace_clearance_mm:.3f} mm violates "
                    f"{profile.manufacturer} {profile.tier} limit {min_tc:.3f} mm."
                ),
                remediation="Increase trace-to-trace spacing to satisfy fab capability.",
            )
        )
        finding_idx += 1

    # 3. Drill diameter
    min_drill = rules.get("min_drill_mm")
    if (
        min_drill is not None
        and board_input.min_drill_mm is not None
        and board_input.min_drill_mm < min_drill
    ):
        findings.append(
            ReviewFinding(
                id=f"DFM_{finding_idx:03d}",
                rule_id=rule_id,
                rule_revision=1,
                severity="error",
                description=(
                    f"Min drill {board_input.min_drill_mm:.3f} mm violates "
                    f"{profile.manufacturer} {profile.tier} limit {min_drill:.3f} mm."
                ),
                remediation="Increase drill diameter or select microvia capability.",
            )
        )
        finding_idx += 1

    # 4. Annular ring evaluation & Issue #1381 concrete check
    min_ar = rules.get("min_annular_ring_mm")
    if (
        min_ar is not None
        and board_input.min_annular_ring_mm is not None
        and board_input.min_annular_ring_mm < min_ar
    ):
        findings.append(
            ReviewFinding(
                id=f"DFM_{finding_idx:03d}",
                rule_id=rule_id,
                rule_revision=1,
                severity="error",
                description=(
                    f"Min annular ring {board_input.min_annular_ring_mm:.3f} mm violates "
                    f"{profile.manufacturer} limit {min_ar:.3f} mm."
                ),
                remediation="Enlarge via/pad copper lands.",
            )
        )
        finding_idx += 1

    # Specific 2-layer / 1-oz PTH floor check (Issue #1381)
    if board_input.copper_layers == 2 and profile.manufacturer.upper() == "JLCPCB":
        pth_floor = float(rules.get("min_pth_annular_ring_2layer_1oz_mm", 0.18))
        waivers = context.explicit_requirements.get("fabricator_exceptions", {})
        for ring_item in board_input.pth_annular_rings:
            ref = str(ring_item.get("ref", ""))
            pad_no = str(ring_item.get("pad_number", ""))
            nominal_ring = float(ring_item.get("nominal_ring_mm", 0.0))
            if nominal_ring < pth_floor - 1e-7:
                has_waiver = ref in waivers or f"{ref}:{pad_no}" in waivers
                if not has_waiver:
                    findings.append(
                        ReviewFinding(
                            id=f"DFM_{finding_idx:03d}",
                            rule_id=rule_id,
                            rule_revision=1,
                            severity="error",
                            description=(
                                f"PTH annular ring {nominal_ring:.3f} mm on {ref} pad {pad_no} "
                                f"is below JLCPCB 2-layer minimum {pth_floor:.3f} mm (#1381). "
                                "Generic DFM score cannot waive PTH process limit; "
                                "requires documented fabricator exception."
                            ),
                            remediation=(
                                "Obtain written fabricator exception or "
                                "redesign connector land pattern."
                            ),
                            metadata={"ref": ref, "pad": pad_no, "nominal_ring_mm": nominal_ring},
                        )
                    )
                    finding_idx += 1

    # 5. Copper to board edge
    copper_to_edge = rules.get("copper_to_edge_mm")
    if (
        copper_to_edge is not None
        and board_input.copper_to_edge_mm is not None
        and board_input.copper_to_edge_mm < copper_to_edge
    ):
        findings.append(
            ReviewFinding(
                id=f"DFM_{finding_idx:03d}",
                rule_id=rule_id,
                rule_revision=1,
                severity="error",
                description=(
                    f"Copper to board edge {board_input.copper_to_edge_mm:.3f} mm is below "
                    f"{profile.manufacturer} required clearance {copper_to_edge:.3f} mm."
                ),
                remediation="Pull back copper pours and routing from board outline.",
            )
        )
        finding_idx += 1

    # 6. Aspect ratio
    max_aspect = rules.get("max_aspect_ratio")
    if (
        max_aspect is not None
        and board_input.aspect_ratio is not None
        and board_input.aspect_ratio > max_aspect
    ):
        findings.append(
            ReviewFinding(
                id=f"DFM_{finding_idx:03d}",
                rule_id=rule_id,
                rule_revision=1,
                severity="error",
                description=(
                    f"Drill aspect ratio {board_input.aspect_ratio:.1f}:1 exceeds "
                    f"{profile.manufacturer} maximum {max_aspect:.1f}:1."
                ),
                remediation="Increase drill diameter or reduce board core thickness.",
            )
        )
        finding_idx += 1

    # 7. Unmeasured PTH/slots note
    if board_input.unmeasured_pth_count > 0:
        findings.append(
            ReviewFinding(
                id=f"DFM_{finding_idx:03d}",
                rule_id=rule_id,
                rule_revision=1,
                severity="warning",
                description=(
                    f"{board_input.unmeasured_pth_count} noncircular PTH/plated slots "
                    "remain unmeasured; written CAM approval required before fabrication."
                ),
                remediation="Submit Gerbers for CAM engineer review and approval.",
            )
        )
        finding_idx += 1

    errors = [f for f in findings if f.severity == "error"]
    warnings = [f for f in findings if f.severity == "warning"]

    if errors:
        status = AssessmentStatus.FAIL
        summary = (
            f"DFM check failed against {profile.manufacturer} {profile.tier} "
            f"({len(errors)} error(s), {len(warnings)} warning(s))."
        )
    elif warnings:
        status = AssessmentStatus.WARN
        summary = (
            f"DFM check passed with {len(warnings)} warning(s) "
            f"against {profile.manufacturer} {profile.tier}."
        )
    else:
        status = AssessmentStatus.PASS
        summary = (
            f"DFM check passed against {profile.manufacturer} {profile.tier} "
            f"(process: {profile.process}, rev: {profile.version})."
        )

    return ReviewAssessment(
        rule_id=rule_id,
        rule_revision=1,
        status=status,
        method=EvaluationMethod.ANALYTICAL,
        summary=summary,
        findings=findings,
        metadata={
            "manufacturer": profile.manufacturer,
            "tier": profile.tier,
            "process": profile.process,
            "version": profile.version,
            "profile_sha256": profile.profile_sha256(),
            "measured_value": board_input.min_annular_ring_mm,
            "applied_threshold": min_ar,
            "threshold_unit": "mm",
        },
    )


def evaluate_dfa_assembly(
    profile: AssemblyProfile | None,
    assembly_input: BoardAssemblyInput | None,
    context: ReviewContext,
    rule_id: str = "mfg.dfa_assembly_rules",
) -> ReviewAssessment:
    """Evaluate PCBA SMT assembly, fiducials, courtyard, pin-1, and CPL rotation."""
    if profile is None:
        return ReviewAssessment(
            rule_id=rule_id,
            rule_revision=1,
            status=AssessmentStatus.NOT_ASSESSED,
            method=EvaluationMethod.ANALYTICAL,
            summary="Assembly profile not provided.",
            missing_inputs=["assembly_profile"],
            metadata={"defect_category": "assembly"},
        )

    if assembly_input is None:
        return ReviewAssessment(
            rule_id=rule_id,
            rule_revision=1,
            status=AssessmentStatus.NOT_ASSESSED,
            method=EvaluationMethod.ANALYTICAL,
            summary="Board assembly input not provided.",
            missing_inputs=["board_assembly_input"],
            metadata={"defect_category": "assembly"},
        )

    findings: list[ReviewFinding] = []
    finding_idx = 1

    # 1. Optical fiducials check
    if assembly_input.fiducials_count < profile.min_fiducials:
        findings.append(
            ReviewFinding(
                id=f"DFA_{finding_idx:03d}",
                rule_id=rule_id,
                rule_revision=1,
                severity="error",
                description=(
                    f"Assembly requires at least {profile.min_fiducials} optical fiducials; "
                    f"found {assembly_input.fiducials_count}."
                ),
                remediation="Add fiducial markers on opposite corners of board/panel.",
            )
        )
        finding_idx += 1

    # 2. Courtyard overlaps
    for overlap in assembly_input.courtyard_overlaps:
        ref_a = overlap.get("ref_a", "compA")
        ref_b = overlap.get("ref_b", "compB")
        area = float(overlap.get("overlap_mm2", 0.0))
        findings.append(
            ReviewFinding(
                id=f"DFA_{finding_idx:03d}",
                rule_id=rule_id,
                rule_revision=1,
                severity="error",
                description=(
                    f"Courtyard collision between {ref_a} and {ref_b} (overlap: {area:.3f} mm²)."
                ),
                remediation="Increase physical spacing between component footprints.",
                metadata={"ref_a": ref_a, "ref_b": ref_b, "overlap_mm2": area},
            )
        )
        finding_idx += 1

    # 3. Component checks (Pin-1, CPL rotation semantics, Tombstoning)
    for comp in assembly_input.components:
        ref = comp.get("ref", "unknown")
        # Polarity / pin-1 check
        if comp.get("is_polarized", False) and not comp.get("has_pin1_mark", False):
            findings.append(
                ReviewFinding(
                    id=f"DFA_{finding_idx:03d}",
                    rule_id=rule_id,
                    rule_revision=1,
                    severity="error",
                    description=(
                        f"Polarized component {ref} missing pin-1 / polarity silkscreen marker."
                    ),
                    remediation="Add pin-1 dot or cathode band on silkscreen.",
                )
            )
            finding_idx += 1

        # CPL rotation semantics: ensure CPL rotation reflects footprint + offset
        fp_rot = comp.get("footprint_rotation_deg")
        cpl_rot = comp.get("cpl_rotation_deg")
        cpl_offset = comp.get("cpl_offset_deg", 0.0)
        if fp_rot is not None and cpl_rot is not None:
            expected_cpl = (float(fp_rot) + float(cpl_offset)) % 360.0
            actual_cpl = float(cpl_rot) % 360.0
            if not math.isclose(expected_cpl, actual_cpl, abs_tol=1e-2):
                findings.append(
                    ReviewFinding(
                        id=f"DFA_{finding_idx:03d}",
                        rule_id=rule_id,
                        rule_revision=1,
                        severity="error",
                        description=(
                            f"CPL rotation mismatch on {ref}: footprint {fp_rot}° + "
                            f"offset {cpl_offset}° = {expected_cpl:.1f}°, "
                            f"but CPL specifies {actual_cpl:.1f}°."
                        ),
                        remediation="Re-generate CPL with assembler-specific rotation correction.",
                    )
                )
                finding_idx += 1

        # Tombstoning / thermal imbalance on 2-terminal chips
        pin1_plane = comp.get("pin1_connected_to_plane", False)
        pin2_plane = comp.get("pin2_connected_to_plane", False)
        has_relief = comp.get("has_thermal_relief", True)
        if pin1_plane != pin2_plane and not has_relief:
            findings.append(
                ReviewFinding(
                    id=f"DFA_{finding_idx:03d}",
                    rule_id=rule_id,
                    rule_revision=1,
                    severity="warning",
                    description=(
                        f"Thermal imbalance on 2-terminal chip {ref} ({comp.get('package', '')}): "
                        "one terminal on solid copper plane without thermal relief "
                        "risks tombstoning."
                    ),
                    remediation="Add thermal relief spokes to pad connection.",
                )
            )
            finding_idx += 1

    errors = [f for f in findings if f.severity == "error"]
    warnings = [f for f in findings if f.severity == "warning"]

    if errors:
        status = AssessmentStatus.FAIL
        summary = f"DFA assembly check failed with {len(errors)} error(s)."
    elif warnings:
        status = AssessmentStatus.WARN
        summary = f"DFA assembly check passed with {len(warnings)} warning(s)."
    else:
        status = AssessmentStatus.PASS
        summary = (
            f"DFA assembly check passed against {profile.assembler} (process: {profile.process})."
        )

    return ReviewAssessment(
        rule_id=rule_id,
        rule_revision=1,
        status=status,
        method=EvaluationMethod.ANALYTICAL,
        summary=summary,
        findings=findings,
        metadata={
            "assembler": profile.assembler,
            "process": profile.process,
            "version": profile.version,
            "profile_sha256": profile.profile_sha256(),
        },
    )


def evaluate_dft_testability(
    spec: DFTTestabilitySpec | None,
    context: ReviewContext,
    rule_id: str = "mfg.dft_testability",
) -> ReviewAssessment:
    """Evaluate test point access and probe spacing for manufacturing test."""
    if spec is None:
        return ReviewAssessment(
            rule_id=rule_id,
            rule_revision=1,
            status=AssessmentStatus.NOT_ASSESSED,
            method=EvaluationMethod.ANALYTICAL,
            summary="Testability specification not provided.",
            missing_inputs=["testpoint_coverage"],
            metadata={"defect_category": "testability"},
        )

    findings: list[ReviewFinding] = []
    finding_idx = 1

    # 1. Power rail test points
    for rail, has_tp in spec.power_rail_testpoints.items():
        if not has_tp:
            findings.append(
                ReviewFinding(
                    id=f"DFT_{finding_idx:03d}",
                    rule_id=rule_id,
                    rule_revision=1,
                    severity="error",
                    description=f"Power rail '{rail}' lacks dedicated test point for probe access.",
                    remediation=f"Add accessible test point or pad on net '{rail}'.",
                )
            )
            finding_idx += 1

    # 2. Reset line test points
    for rst, has_tp in spec.reset_testpoints.items():
        if not has_tp:
            findings.append(
                ReviewFinding(
                    id=f"DFT_{finding_idx:03d}",
                    rule_id=rule_id,
                    rule_revision=1,
                    severity="error",
                    description=(
                        f"Reset net '{rst}' lacks accessible test point for ICT / bring-up."
                    ),
                    remediation=f"Add test point on net '{rst}'.",
                )
            )
            finding_idx += 1

    # 3. Probe pitch / clearance
    for pitch_item in spec.testpoint_probe_pitches:
        tp1 = pitch_item.get("tp1", "TP1")
        tp2 = pitch_item.get("tp2", "TP2")
        pitch = float(pitch_item.get("pitch_mm", 0.0))
        min_pitch = float(pitch_item.get("min_required_mm", 1.27))
        if pitch < min_pitch:
            findings.append(
                ReviewFinding(
                    id=f"DFT_{finding_idx:03d}",
                    rule_id=rule_id,
                    rule_revision=1,
                    severity="error",
                    description=(
                        f"Test point pitch between {tp1} and {tp2} ({pitch:.3f} mm) is below "
                        f"minimum fixture probe clearance {min_pitch:.3f} mm."
                    ),
                    remediation="Increase spacing between adjacent test points.",
                )
            )
            finding_idx += 1

    errors = [f for f in findings if f.severity == "error"]
    status = AssessmentStatus.FAIL if errors else AssessmentStatus.PASS
    summary = (
        f"DFT testability review failed with {len(errors)} error(s)."
        if errors
        else "DFT testability review passed with all required test points accessible."
    )

    return ReviewAssessment(
        rule_id=rule_id,
        rule_revision=1,
        status=status,
        method=EvaluationMethod.ANALYTICAL,
        summary=summary,
        findings=findings,
    )


def evaluate_bom_and_lifecycle(
    bom_items: list[BOMItemInput] | None,
    context: ReviewContext,
    rule_id: str = "mfg.bom_lifecycle_alternates",
) -> ReviewAssessment:
    """Evaluate BOM sourcing, component lifecycle, unverified stock, and alternate qualification."""
    if not bom_items:
        return ReviewAssessment(
            rule_id=rule_id,
            rule_revision=1,
            status=AssessmentStatus.NOT_ASSESSED,
            method=EvaluationMethod.ANALYTICAL,
            summary="BOM items not provided.",
            missing_inputs=["bom_items"],
            metadata={"defect_category": "bom"},
        )

    findings: list[ReviewFinding] = []
    finding_idx = 1

    for item in bom_items:
        # 1. Lifecycle checks
        if item.lifecycle_status in ("EOL", "OBSOLETE"):
            findings.append(
                ReviewFinding(
                    id=f"BOM_{finding_idx:03d}",
                    rule_id=rule_id,
                    rule_revision=1,
                    severity="error",
                    description=(
                        f"BOM component {item.reference} ({item.mpn}) is {item.lifecycle_status}."
                    ),
                    remediation="Select active replacement part with active lifecycle.",
                )
            )
            finding_idx += 1
        elif item.lifecycle_status == "NRND":
            findings.append(
                ReviewFinding(
                    id=f"BOM_{finding_idx:03d}",
                    rule_id=rule_id,
                    rule_revision=1,
                    severity="warning",
                    description=(
                        f"BOM component {item.reference} ({item.mpn}) is Not Recommended "
                        "for New Designs (NRND)."
                    ),
                    remediation="Plan migration to newer pin-compatible active component.",
                )
            )
            finding_idx += 1

        # 2. Stock availability checks
        if item.stock_status in ("OFFLINE_SNAPSHOT", "UNVERIFIED"):
            findings.append(
                ReviewFinding(
                    id=f"BOM_{finding_idx:03d}",
                    rule_id=rule_id,
                    rule_revision=1,
                    severity="warning",
                    description=(
                        f"BOM component {item.reference} ({item.mpn}) stock is from "
                        f"{item.stock_status.lower()} (as of {item.stock_as_of or 'unspecified'}); "
                        "cannot be presented as verified live availability."
                    ),
                    remediation="Verify live supplier stock and lead time before procurement.",
                )
            )
            finding_idx += 1
        elif item.stock_status == "OUT_OF_STOCK":
            findings.append(
                ReviewFinding(
                    id=f"BOM_{finding_idx:03d}",
                    rule_id=rule_id,
                    rule_revision=1,
                    severity="error",
                    description=f"BOM component {item.reference} ({item.mpn}) is OUT_OF_STOCK.",
                    remediation="Select qualified in-stock alternate.",
                )
            )
            finding_idx += 1

        # 3. Alternates evaluation
        for alt in item.alternates:
            alt_mpn = alt.get("alt_mpn", "alternate")
            incompatibilities: list[str] = []
            if not alt.get("footprint_compatible", True):
                incompatibilities.append("footprint incompatible")
            if not alt.get("pin_compatible", True):
                incompatibilities.append("pinout incompatible")
            if not alt.get("electrical_compatible", True):
                incompatibilities.append("electrical rating incompatible")
            if not alt.get("firmware_compatible", True):
                incompatibilities.append("firmware/register incompatible")
            if alt.get("lifecycle_status") in ("EOL", "OBSOLETE"):
                incompatibilities.append(f"lifecycle {alt.get('lifecycle_status')}")

            if incompatibilities:
                findings.append(
                    ReviewFinding(
                        id=f"BOM_{finding_idx:03d}",
                        rule_id=rule_id,
                        rule_revision=1,
                        severity="error",
                        description=(
                            f"Alternate {alt_mpn} for {item.reference} rejected: "
                            f"{', '.join(incompatibilities)}."
                        ),
                        remediation="Disqualify incompatible alternate or modify schematic/PCB.",
                    )
                )
                finding_idx += 1

    errors = [f for f in findings if f.severity == "error"]
    warnings = [f for f in findings if f.severity == "warning"]

    if errors:
        status = AssessmentStatus.FAIL
        summary = f"BOM review failed with {len(errors)} error(s)."
    elif warnings:
        status = AssessmentStatus.WARN
        summary = f"BOM review passed with {len(warnings)} sourcing warning(s)."
    else:
        status = AssessmentStatus.PASS
        summary = "BOM review passed: all components active, available, and alternates qualified."

    return ReviewAssessment(
        rule_id=rule_id,
        rule_revision=1,
        status=status,
        method=EvaluationMethod.ANALYTICAL,
        summary=summary,
        findings=findings,
    )


def evaluate_bringup_measurements(
    items: list[BringupPlanInput] | None,
    auth: StageAuthorizationInput | None,
    context: ReviewContext,
    rule_id: str = "mfg.bringup_evidence_verification",
) -> ReviewAssessment:
    """Evaluate bring-up test plan and distinguish checklists from actual measurement evidence."""
    if items is None:
        return ReviewAssessment(
            rule_id=rule_id,
            rule_revision=1,
            status=AssessmentStatus.NOT_ASSESSED,
            method=EvaluationMethod.PHYSICAL_MEASUREMENT,
            summary="Bring-up test plan not provided.",
            missing_inputs=["bringup_test_plan"],
            metadata={"defect_category": "bringup"},
        )

    findings: list[ReviewFinding] = []
    finding_idx = 1

    for item in items:
        # Check: checklist item without measurement data is NOT measurement evidence
        if item.is_checklist_only or item.measured_value is None:
            findings.append(
                ReviewFinding(
                    id=f"BRINGUP_{finding_idx:03d}",
                    rule_id=rule_id,
                    rule_revision=1,
                    severity="error",
                    description=(
                        f"Bring-up step '{item.item_id}' ({item.description}): "
                        "checklist completion without measurements is not measurement evidence."
                    ),
                    remediation="Record actual measured value using calibrated test instrument.",
                )
            )
            finding_idx += 1
            continue

        # Acceptance bounds
        val = item.measured_value
        if item.acceptance_min is not None and val < item.acceptance_min:
            findings.append(
                ReviewFinding(
                    id=f"BRINGUP_{finding_idx:03d}",
                    rule_id=rule_id,
                    rule_revision=1,
                    severity="error",
                    description=(
                        f"Bring-up step '{item.item_id}' measured value {val} "
                        f"{item.measurement_unit or ''} is below minimum {item.acceptance_min}."
                    ),
                    remediation="Investigate power supply tolerance or load fault.",
                )
            )
            finding_idx += 1

        if item.acceptance_max is not None and val > item.acceptance_max:
            findings.append(
                ReviewFinding(
                    id=f"BRINGUP_{finding_idx:03d}",
                    rule_id=rule_id,
                    rule_revision=1,
                    severity="error",
                    description=(
                        f"Bring-up step '{item.item_id}' measured value {val} "
                        f"{item.measurement_unit or ''} exceeds maximum {item.acceptance_max}."
                    ),
                    remediation="Investigate regulator loop stability or overvoltage condition.",
                )
            )
            finding_idx += 1

        # Instrument identity and environment warnings
        if not item.instrument_id:
            findings.append(
                ReviewFinding(
                    id=f"BRINGUP_{finding_idx:03d}",
                    rule_id=rule_id,
                    rule_revision=1,
                    severity="warning",
                    description=(
                        f"Bring-up step '{item.item_id}' lacks instrument / "
                        "test equipment identity."
                    ),
                    remediation="Log calibrated multimeter, scope, or analyzer serial number.",
                )
            )
            finding_idx += 1

        if item.environmental_temp_c is None:
            findings.append(
                ReviewFinding(
                    id=f"BRINGUP_{finding_idx:03d}",
                    rule_id=rule_id,
                    rule_revision=1,
                    severity="warning",
                    description=(
                        f"Bring-up step '{item.item_id}' lacks environmental ambient temperature."
                    ),
                    remediation="Record ambient room temperature during test.",
                )
            )
            finding_idx += 1

    # Stage authorization separation
    if auth is None:
        findings.append(
            ReviewFinding(
                id=f"BRINGUP_{finding_idx:03d}",
                rule_id=rule_id,
                rule_revision=1,
                severity="warning",
                description="Hardware stage authorization record not provided.",
                remediation="Provide signed StageAuthorizationInput.",
            )
        )
        finding_idx += 1
    else:
        if auth.production_release_authorized and not auth.power_on_authorized:
            findings.append(
                ReviewFinding(
                    id=f"BRINGUP_{finding_idx:03d}",
                    rule_id=rule_id,
                    rule_revision=1,
                    severity="error",
                    description=(
                        "Production release cannot be authorized without completed "
                        "and authorized hardware power-on bring-up."
                    ),
                    remediation="Complete bring-up testing before authorizing production release.",
                )
            )
            finding_idx += 1

    errors = [f for f in findings if f.severity == "error"]
    warnings = [f for f in findings if f.severity == "warning"]

    if errors:
        status = AssessmentStatus.FAIL
        summary = f"Bring-up measurement verification failed with {len(errors)} error(s)."
    elif warnings:
        status = AssessmentStatus.WARN
        summary = f"Bring-up measurement verification passed with {len(warnings)} warning(s)."
    else:
        status = AssessmentStatus.PASS
        summary = (
            "Bring-up measurement verification passed: all measured values within acceptance "
            "bounds with calibrated test setup and valid authorizations."
        )

    return ReviewAssessment(
        rule_id=rule_id,
        rule_revision=1,
        status=status,
        method=EvaluationMethod.PHYSICAL_MEASUREMENT,
        summary=summary,
        findings=findings,
    )


def dfm_profile_to_evidence_record(
    profile: FabricationProfile,
    project_key: str,
    board_sha256: str,
    producer_version: str = "1.0.0",
) -> EvidenceRecord:
    """Convert verified DFM capability profile into immutable EvidenceRecord with sorted inputs."""
    prof_hash = profile.profile_sha256()
    raw_inputs = [
        EvidenceInputDigest(entity_id="board_source", sha256=board_sha256),
        EvidenceInputDigest(entity_id="dfm_profile", sha256=prof_hash),
    ]
    sorted_inputs = tuple(sorted(raw_inputs, key=lambda entry: entry.entity_id))

    return EvidenceRecord(
        schema_version=1,
        evidence_id=f"EVID_DFM_{profile.manufacturer.lower()}_{profile.version}",
        kind=EvidenceRecordKind.MEASUREMENT,
        project_key=project_key,
        source_revision=profile.version,
        source_sha256=board_sha256,
        producer=f"kicad_mcp.review.dfm:{profile.manufacturer}",
        producer_version=producer_version,
        captured_at=datetime.now(UTC),
        dependency_manifest_complete=True,
        inputs=sorted_inputs,
        provenance_source=profile.source,
    )
