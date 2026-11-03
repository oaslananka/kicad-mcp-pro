"""Engineering review rule catalog and honest result model (#1579, #1580)."""

from .adapter import (
    adapt_assessment_to_verdict,
    adapt_finding,
    adapt_snapshot_to_verdict,
)
from .catalog import (
    ReviewRuleCatalog,
    build_standard_rule_catalog,
    compute_coverage,
)
from .electrical_contracts import (
    ComponentStressContract,
    evaluate_component_derating,
    evaluate_component_stress,
    evaluate_specialist_safety_review,
    evaluate_thermal_spreading,
    evaluate_trace_dc_loss,
)
from .external_evidence import (
    ExternalAnalysisReport,
    evaluate_external_evidence,
    load_external_analysis_report,
    report_to_evidence_record,
)
from .mechanical_acceptance import (
    check_rectangular_outline,
    evaluate_connector_mating_orientation,
    evaluate_mechanical_stage_gate,
    is_connector_footprint,
)
from .placement_connectivity import (
    evaluate_crystal_placement,
    evaluate_decoupling_connectivity,
)
from .routing_style import evaluate_routing_style
from .stage_gate import (
    ReviewStage,
    StageGateDecision,
    bind_snapshot_to_evidence,
    build_verified_design_workflow,
    evaluate_stage_readiness,
)
from .visual_quality import (
    ComponentRotationState,
    CosmeticTransactionPlan,
    apply_cosmetic_transaction,
    calculate_cpl_rotation,
    detect_pin1_marker_visibility,
    evaluate_pcb_visual_quality,
    evaluate_schematic_visual_quality,
    evaluate_visual_quality,
    plan_cosmetic_transaction,
    verify_rotation_independence,
)

__all__ = [
    "adapt_assessment_to_verdict",
    "adapt_finding",
    "adapt_snapshot_to_verdict",
    "apply_cosmetic_transaction",
    "bind_snapshot_to_evidence",
    "build_standard_rule_catalog",
    "build_verified_design_workflow",
    "calculate_cpl_rotation",
    "check_rectangular_outline",
    "ComponentRotationState",
    "ComponentStressContract",
    "compute_coverage",
    "CosmeticTransactionPlan",
    "detect_pin1_marker_visibility",
    "evaluate_component_derating",
    "evaluate_component_stress",
    "evaluate_connector_mating_orientation",
    "evaluate_crystal_placement",
    "evaluate_decoupling_connectivity",
    "evaluate_external_evidence",
    "evaluate_mechanical_stage_gate",
    "evaluate_pcb_visual_quality",
    "evaluate_routing_style",
    "evaluate_schematic_visual_quality",
    "evaluate_specialist_safety_review",
    "evaluate_stage_readiness",
    "evaluate_thermal_spreading",
    "evaluate_trace_dc_loss",
    "evaluate_visual_quality",
    "ExternalAnalysisReport",
    "is_connector_footprint",
    "load_external_analysis_report",
    "plan_cosmetic_transaction",
    "report_to_evidence_record",
    "ReviewRuleCatalog",
    "ReviewStage",
    "StageGateDecision",
    "verify_rotation_independence",
]
