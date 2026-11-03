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

__all__ = [
    "ReviewRuleCatalog",
    "ReviewStage",
    "StageGateDecision",
    "adapt_assessment_to_verdict",
    "adapt_finding",
    "adapt_snapshot_to_verdict",
    "bind_snapshot_to_evidence",
    "build_standard_rule_catalog",
    "build_verified_design_workflow",
    "compute_coverage",
    "evaluate_crystal_placement",
    "evaluate_decoupling_connectivity",
    "evaluate_routing_style",
    "evaluate_stage_readiness",
]
