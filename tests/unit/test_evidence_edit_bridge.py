"""#942 stacked tranche: reuse one freshness classifier in edit-impact tools."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from kicad_mcp.ir.engineering_graph import (
    EngineeringGraph,
    GraphEntity,
    GraphEntityKind,
    GraphProvenance,
    GraphProvenanceKind,
    canonical_entity_id,
)
from kicad_mcp.project.edit_impact import ProjectEditImpactService
from kicad_mcp.project.evidence_edit_bridge import (
    EvidenceImpactSnapshot,
    compile_evidence_impact,
    render_evidence_impact,
)
from kicad_mcp.project.evidence_freshness import (
    EvidenceFreshnessState,
    EvidenceRecord,
    attach_evidence_record,
)

HASH = "a" * 64


def _snapshot(*, change_net: bool = False, trusted: bool = True) -> EvidenceImpactSnapshot:
    before = EngineeringGraph(project_key="fixture-usb")
    usb = canonical_entity_id("fixture-usb", GraphEntityKind.NET, "USB_DP")
    before.add_entity(GraphEntity(entity_id=usb, kind=GraphEntityKind.NET, stable_key="USB_DP"))
    record = EvidenceRecord.model_validate(
        {
            "schema_version": 1,
            "evidence_id": "EVID-USB-IMPEDANCE",
            "kind": "evidence_artifact",
            "project_key": "fixture-usb",
            "source_revision": "board-revision-12",
            "source_sha256": "b" * 64,
            "producer": "trusted-kicad-check",
            "producer_version": "10.0.3",
            "captured_at": datetime(2026, 9, 30, 14, 0, tzinfo=UTC),
            "dependency_manifest_complete": True,
            "inputs": [{"entity_id": usb, "sha256": HASH}],
            "provenance_source": "native-result-12",
        }
    )
    attach_evidence_record(
        before,
        record,
        provenance=GraphProvenance(GraphProvenanceKind.TOOL_GENERATED, source="native"),
    )
    after = EngineeringGraph.from_document(before.to_document())
    if change_net:
        after.entities[usb] = GraphEntity(
            entity_id=usb,
            kind=GraphEntityKind.NET,
            stable_key="USB_DP",
            attributes={"geometry_revision": "13"},
        )
    return EvidenceImpactSnapshot(
        before=before,
        after=after,
        records=(record,),
        current_hashes={usb: HASH},
        mutation_scope_known=True,
        hashes_authoritative=trusted,
    )


def _service(
    snapshot: EvidenceImpactSnapshot | None = None,
    *,
    without_provider: bool = False,
) -> ProjectEditImpactService:
    baseline = {"critical_nets": ["USB_DP"], "manufacturer": "ACME"}
    service = ProjectEditImpactService(
        load_baseline=lambda: baseline,
        infer_current=lambda: dict(baseline),
        evaluate_project_gate=lambda **_: [],
        combined_status=lambda _: "PASS",
        format_gate=lambda _: "never-called",
        project_gate_categories=frozenset({"pcb", "connectivity"}),
    )
    if without_provider:
        return service
    if snapshot is None:
        snapshot = _snapshot()
    return replace(service, evidence_snapshot=lambda: snapshot)


def test_default_existing_api_never_certifies_missing_evidence() -> None:
    service = _service(without_provider=True)
    report = service.assess()
    assert "Gates to re-run: (none)" in report
    assert "Evidence freshness: requires_recheck" in report
    assert "gate reuse is not evidence proof" in report
    report2 = service.revalidate()
    assert "Evidence freshness: requires_recheck" in report2
    assert "No gates were re-run" in report2


def test_explicit_authoritative_snapshot_keeps_unchanged_usb_proof() -> None:
    service = _service(_snapshot())
    report = service.assess()
    assert "Evidence freshness: still_valid" in report
    assert "EVID-USB-IMPEDANCE: still_valid" in report
    assert "Gates to re-run: (none)" in report
    assert "Evidence freshness: still_valid" in service.revalidate()


def test_graph_change_invalidates_proof_despite_identical_intent() -> None:
    service = _service(_snapshot(change_net=True))
    report = service.assess()
    assert "Changes:\n  (none)" in report
    assert "Evidence freshness: invalidated" in report
    assert "changed_relevant_graph_entity" in report
    assert "Evidence freshness: invalidated" in service.revalidate()


def test_untrusted_snapshot_and_missing_evidence_fail_toward_recheck() -> None:
    snapshot = _snapshot(trusted=False)
    result = compile_evidence_impact(snapshot)
    assert result.state is EvidenceFreshnessState.REQUIRES_RECHECK
    assert "requires_recheck" in render_evidence_impact(result)
    empty = replace(snapshot, records=())
    assert compile_evidence_impact(empty).state is EvidenceFreshnessState.REQUIRES_RECHECK
    assert "No authoritative evidence records" in render_evidence_impact(
        compile_evidence_impact(empty)
    )


def test_duplicate_artifact_identity_refuses_ambiguous_batch() -> None:
    snapshot = _snapshot()
    ambiguous = replace(snapshot, records=(snapshot.records[0], snapshot.records[0]))
    with pytest.raises(ValueError, match="duplicate evidence ID"):
        compile_evidence_impact(ambiguous)


def test_multiple_artifacts_do_not_hide_definite_invalidation() -> None:
    snapshot = _snapshot(change_net=True)
    report = compile_evidence_impact(snapshot)
    assert report.state is EvidenceFreshnessState.INVALIDATED
    reason_codes = {reason.code for result in report.assessments for reason in result.reasons}
    assert "changed_relevant_graph_entity" in reason_codes
