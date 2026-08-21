"""Compatibility exports for project edit-impact analysis."""

from __future__ import annotations

from ..project.edit_impact import (
    ALL_GATES,
    ImpactReport,
    IntentChange,
    impact_of_changes,
    render_impact_report,
    semantic_intent_diff,
)

__all__ = [
    "ALL_GATES",
    "ImpactReport",
    "IntentChange",
    "impact_of_changes",
    "render_impact_report",
    "semantic_intent_diff",
]
