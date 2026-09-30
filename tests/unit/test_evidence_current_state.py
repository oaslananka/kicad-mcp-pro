"""Current-state evidence hash resolver."""

from __future__ import annotations

from datetime import UTC, datetime

from kicad_mcp.ir.engineering_graph import (
    EngineeringGraph,
    GraphEntity,
    GraphEntityKind,
    GraphProvenance,
    GraphProvenanceKind,
    NativeLink,
    canonical_entity_id,
)
from kicad_mcp.project.evidence_current_state import (
    assess_evidence_current_state,
    canonical_graph_entity_sha256,
)
from kicad_mcp.project.evidence_freshness import (
    EvidenceFreshnessState,
    EvidenceRecord,
)

SOURCE = "b" * 64


def _graph() -> tuple[EngineeringGraph, str]:
    graph = EngineeringGraph(project_key="fixture")
    entity_id = canonical_entity_id("fixture", GraphEntityKind.NET, "USB_DP")
    graph.add_entity(
        GraphEntity(
            entity_id=entity_id,
            kind=GraphEntityKind.NET,
            stable_key="USB_DP",
            attributes={"name": "USB_DP", "connections": [["U1", "1"]]},
            provenance=GraphProvenance(GraphProvenanceKind.IMPORTED, source="IRCircuit"),
            native_links=(NativeLink("kicad", "net", "USB_DP"),),
        )
    )
    return graph, entity_id


def _record(graph: EngineeringGraph, entity_id: str) -> EvidenceRecord:
    digest = canonical_graph_entity_sha256(graph.entities[entity_id])
    return EvidenceRecord.model_validate(
        {
            "schema_version": 1,
            "evidence_id": "EVID-USB-1",
            "kind": "evidence_artifact",
            "project_key": "fixture",
            "source_revision": "rev-1",
            "source_sha256": SOURCE,
            "producer": "native-check",
            "producer_version": "10.0.3",
            "captured_at": datetime(2026, 9, 30, 16, 0, tzinfo=UTC),
            "dependency_manifest_complete": True,
            "inputs": [{"entity_id": entity_id, "sha256": digest}],
            "provenance_source": "native-fixture",
        }
    )


def test_canonical_hash_is_stable_across_attribute_insertion_and_native_link_order() -> None:
    graph, entity_id = _graph()
    first = graph.entities[entity_id]
    second = GraphEntity(
        entity_id=first.entity_id,
        kind=first.kind,
        stable_key=first.stable_key,
        attributes={"connections": [["U1", "1"]], "name": "USB_DP"},
        provenance=first.provenance,
        native_links=tuple(reversed(first.native_links)),
    )
    assert canonical_graph_entity_sha256(first) == canonical_graph_entity_sha256(second)


def test_exact_current_graph_and_source_hash_is_still_valid() -> None:
    graph, entity_id = _graph()
    record = _record(graph, entity_id)
    result = assess_evidence_current_state(record, graph=graph, current_source_sha256=SOURCE)
    assert result.state is EvidenceFreshnessState.STILL_VALID
    assert result.reasons == ()


def test_changed_current_entity_hash_invalidates() -> None:
    graph, entity_id = _graph()
    record = _record(graph, entity_id)
    graph.entities[entity_id] = GraphEntity(
        entity_id=entity_id,
        kind=GraphEntityKind.NET,
        stable_key="USB_DP",
        attributes={"name": "USB_DP", "connections": [["U1", "2"]]},
    )
    result = assess_evidence_current_state(record, graph=graph, current_source_sha256=SOURCE)
    assert result.state is EvidenceFreshnessState.INVALIDATED
    assert result.reasons[0].code == "exact_input_hash_changed"


def test_changed_source_hash_invalidates() -> None:
    graph, entity_id = _graph()
    record = _record(graph, entity_id)
    result = assess_evidence_current_state(record, graph=graph, current_source_sha256="c" * 64)
    assert result.state is EvidenceFreshnessState.INVALIDATED
    assert "source_hash_changed" in [reason.code for reason in result.reasons]


def test_missing_dependency_requires_recheck() -> None:
    graph, entity_id = _graph()
    record = _record(graph, entity_id)
    graph.entities.pop(entity_id)
    result = assess_evidence_current_state(record, graph=graph, current_source_sha256=SOURCE)
    assert result.state is EvidenceFreshnessState.REQUIRES_RECHECK
    codes = [reason.code for reason in result.reasons]
    assert codes == ["unresolved_dependency_entity"]


def test_unknown_source_or_project_identity_requires_recheck() -> None:
    graph, entity_id = _graph()
    record = _record(graph, entity_id)
    missing_source = assess_evidence_current_state(record, graph=graph, current_source_sha256=None)
    assert missing_source.state is EvidenceFreshnessState.REQUIRES_RECHECK

    other = EngineeringGraph(project_key="other")
    result = assess_evidence_current_state(
        record,
        graph=other,
        current_source_sha256=SOURCE,
        current_hashes={entity_id: record.inputs[0].sha256},
    )
    assert result.state is EvidenceFreshnessState.REQUIRES_RECHECK
    assert result.reasons[0].code == "project_identity_mismatch"


def test_incomplete_manifest_or_invalid_supplied_hash_requires_recheck() -> None:
    graph, entity_id = _graph()
    record = _record(graph, entity_id)
    incomplete = record.model_copy(update={"dependency_manifest_complete": False})
    result = assess_evidence_current_state(
        incomplete,
        graph=graph,
        current_source_sha256=SOURCE,
        current_hashes={entity_id: "UNKNOWN"},
    )
    assert result.state is EvidenceFreshnessState.REQUIRES_RECHECK
    codes = [reason.code for reason in result.reasons]
    assert "unknown_dependency_or_mutation_scope" in codes
    assert "current_input_hash_missing_or_invalid" in codes


def test_canonical_hash_preserves_semantic_attribute_list_order() -> None:
    graph, entity_id = _graph()
    first = graph.entities[entity_id]
    reordered = GraphEntity(
        entity_id=first.entity_id,
        kind=first.kind,
        stable_key=first.stable_key,
        attributes={"name": "USB_DP", "connections": [["U2", "2"], ["U1", "1"]]},
        provenance=first.provenance,
        native_links=first.native_links,
    )
    ordered = GraphEntity(
        entity_id=first.entity_id,
        kind=first.kind,
        stable_key=first.stable_key,
        attributes={"name": "USB_DP", "connections": [["U1", "1"], ["U2", "2"]]},
        provenance=first.provenance,
        native_links=first.native_links,
    )
    assert canonical_graph_entity_sha256(ordered) != canonical_graph_entity_sha256(reordered)


def test_canonical_hash_tolerates_none_native_links_payload(monkeypatch) -> None:
    graph, entity_id = _graph()
    entity = graph.entities[entity_id]
    payload = entity.to_dict()
    payload["native_links"] = None
    monkeypatch.setattr(GraphEntity, "to_dict", lambda _self: payload)
    digest = canonical_graph_entity_sha256(entity)
    assert len(digest) == 64
