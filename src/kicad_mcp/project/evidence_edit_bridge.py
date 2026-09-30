"""Pure edit-impact bridge for graph-based evidence freshness.

The legacy intent-category gate map remains useful for selecting re-runs, but
it cannot certify native proof freshness. The bridge consumes the shared #942
dependency classifier, and missing native hashes fail toward recheck.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from ..ir.engineering_graph import EngineeringGraph
from .evidence_freshness import (
    EvidenceFreshnessState,
    EvidenceRecord,
    FreshnessAssessment,
    assess_evidence_freshness,
)


@dataclass(frozen=True, slots=True)
class EvidenceImpactSnapshot:
    """Inputs supplied by an authoritative host, not inferred from intent text."""

    before: EngineeringGraph
    after: EngineeringGraph
    records: tuple[EvidenceRecord, ...]
    current_hashes: Mapping[str, str]
    mutation_scope_known: bool
    hashes_authoritative: bool = False


@dataclass(frozen=True, slots=True)
class EvidenceImpactReport:
    """Deterministic per-artifact diagnostics shared by the edit-impact service."""

    state: EvidenceFreshnessState
    assessments: tuple[FreshnessAssessment, ...]


def compile_evidence_impact(snapshot: EvidenceImpactSnapshot) -> EvidenceImpactReport:
    """Classify all supplied artifacts; absent or untrusted proof never passes."""
    if not snapshot.records:
        return EvidenceImpactReport(EvidenceFreshnessState.REQUIRES_RECHECK, ())
    ids = [record.evidence_id for record in snapshot.records]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate evidence ID in edit-impact batch")
    assessments = tuple(
        assess_evidence_freshness(
            record,
            before=snapshot.before,
            after=snapshot.after,
            current_hashes=snapshot.current_hashes,
            mutation_scope_known=(snapshot.mutation_scope_known and snapshot.hashes_authoritative),
        )
        for record in sorted(snapshot.records, key=lambda item: item.evidence_id)
    )
    states = {assessment.state for assessment in assessments}
    if EvidenceFreshnessState.INVALIDATED in states:
        overall = EvidenceFreshnessState.INVALIDATED
    elif EvidenceFreshnessState.REQUIRES_RECHECK in states:
        overall = EvidenceFreshnessState.REQUIRES_RECHECK
    else:
        overall = EvidenceFreshnessState.STILL_VALID
    return EvidenceImpactReport(overall, assessments)


def render_evidence_impact(report: EvidenceImpactReport) -> str:
    """Stable readable diagnostics; no approval or release-signoff inference."""
    lines = [f"Evidence freshness: {report.state.value}"]
    if not report.assessments:
        lines.append("- No authoritative evidence records; recheck required.")
    for assessment in report.assessments:
        codes = ",".join(reason.code for reason in assessment.reasons) or "exact_hashes_match"
        lines.append(f"- {assessment.evidence_id}: {assessment.state.value} ({codes})")
    return "\n".join(lines)
