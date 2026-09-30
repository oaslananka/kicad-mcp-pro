"""#942 Evidence freshness: exact known graph/hash changes and conservative unknowns."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from kicad_mcp.ir.engineering_graph import (
    EngineeringGraph,
    GraphEdge,
    GraphEdgeKind,
    GraphEntity,
    GraphEntityKind,
    GraphProvenance,
    GraphProvenanceKind,
    canonical_entity_id,
)
from kicad_mcp.project.evidence_freshness import (
    EvidenceFreshnessState,
    EvidenceRecord,
    assess_evidence_freshness,
    attach_evidence_record,
    evidence_graph_id,
    evidence_record_json_schema,
)

PROJECT = "usb-layout-fixture"
A = "a" * 64
B = "b" * 64
C = "c" * 64
D = "d" * 64
E = "e" * 64


def _entity(graph: EngineeringGraph, kind: GraphEntityKind, key: str) -> str:
    entity_id = canonical_entity_id(graph.project_key, kind, key)
    graph.add_entity(GraphEntity(entity_id=entity_id, kind=kind, stable_key=key))
    return entity_id


def _provenance() -> GraphProvenance:
    return GraphProvenance(GraphProvenanceKind.TOOL_GENERATED, source="native-oracle")


def _fixture() -> tuple[EngineeringGraph, EvidenceRecord, dict[str, str], dict[str, str]]:
    graph = EngineeringGraph(project_key=PROJECT)
    names = {
        "usb": _entity(graph, GraphEntityKind.NET, "USB_DP"),
        "stackup": _entity(graph, GraphEntityKind.CONSTRAINT, "PCB_STACKUP"),
        "u8": _entity(graph, GraphEntityKind.COMPONENT, "U8"),
        "contract": _entity(graph, GraphEntityKind.INTENT_CONTRACT, "INTENT-USB-SI"),
    }
    all_hashes = {
        names["usb"]: A,
        names["stackup"]: B,
        names["contract"]: C,
    }
    record = EvidenceRecord(
        schema_version=1,
        evidence_id="EVID-USB-Z0",
        kind="evidence_artifact",
        project_key=PROJECT,
        source_revision="board-revision-17",
        source_sha256=D,
        producer="kicad-cli-drc",
        producer_version="10.0.3",
        captured_at=datetime(2026, 9, 30, 12, 0, tzinfo=UTC),
        dependency_manifest_complete=True,
        inputs=[{"entity_id": key, "sha256": value} for key, value in sorted(all_hashes.items())],
        contract_id="INTENT-USB-SI",
        contract_version=1,
        provenance_source="native-drc-fixture-17",
    )
    attach_evidence_record(graph, record, provenance=_provenance())
    return graph, record, all_hashes, names


def _copy(graph: EngineeringGraph) -> EngineeringGraph:
    return EngineeringGraph.from_document(graph.to_document())


def _mutate(graph: EngineeringGraph, entity_id: str) -> EngineeringGraph:
    after = _copy(graph)
    original = after.entities[entity_id]
    after.entities[entity_id] = GraphEntity(
        entity_id=original.entity_id,
        kind=original.kind,
        stable_key=original.stable_key,
        attributes={"edited": "2026-09-30T13:00:00Z"},
        provenance=original.provenance,
        native_links=original.native_links,
    )
    return after


def _assess(
    record: EvidenceRecord,
    before: EngineeringGraph,
    after: EngineeringGraph,
    hashes: dict[str, str],
    *,
    mutation_scope_known: bool = True,
):
    return assess_evidence_freshness(
        record,
        before=before,
        after=after,
        current_hashes=hashes,
        mutation_scope_known=mutation_scope_known,
    )


def test_unrelated_u8_change_keeps_usb_impedance_evidence_still_valid() -> None:
    before, record, hashes, ids = _fixture()
    after = _mutate(before, ids["u8"])
    report = _assess(record, before, after, hashes)
    assert report.state is EvidenceFreshnessState.STILL_VALID
    assert report.reasons == ()
    assert evidence_graph_id(record) in after.entities


@pytest.mark.parametrize("changed", ["usb", "stackup"])
def test_relevant_geometry_or_stackup_change_invalidates_usb_proof(changed: str) -> None:
    before, record, hashes, ids = _fixture()
    after = _mutate(before, ids[changed])
    report = _assess(record, before, after, hashes)
    assert report.state is EvidenceFreshnessState.INVALIDATED
    assert [reason.code for reason in report.reasons] == ["changed_relevant_graph_entity"]


def test_exact_hash_mismatch_invalidates_without_graph_change() -> None:
    before, record, hashes, ids = _fixture()
    changed = dict(hashes)
    changed[ids["usb"]] = E
    report = _assess(record, before, _copy(before), changed)
    assert report.state is EvidenceFreshnessState.INVALIDATED
    assert report.reasons[0].code == "exact_input_hash_changed"
    assert report.reasons[0].entity_id == ids["usb"]


def test_unknown_change_scope_never_reports_still_valid() -> None:
    before, record, hashes, _ = _fixture()
    report = _assess(record, before, _copy(before), hashes, mutation_scope_known=False)
    assert report.state is EvidenceFreshnessState.REQUIRES_RECHECK
    assert "unknown_dependency_or_mutation_scope" in [r.code for r in report.reasons]


def test_missing_or_invalid_current_digest_never_reports_still_valid() -> None:
    before, record, hashes, ids = _fixture()
    missing = dict(hashes)
    missing.pop(ids["stackup"])
    for current_hashes in (missing, {**hashes, ids["stackup"]: "UNKNOWN"}):
        report = _assess(record, before, _copy(before), current_hashes)
        assert report.state is EvidenceFreshnessState.REQUIRES_RECHECK
        assert "current_input_hash_missing_or_invalid" in [r.code for r in report.reasons]


def test_declared_incomplete_manifest_fails_closed() -> None:
    before, record, hashes, _ = _fixture()
    incomplete = record.model_copy(update={"dependency_manifest_complete": False})
    report = _assess(incomplete, before, _copy(before), hashes)
    assert report.state is EvidenceFreshnessState.REQUIRES_RECHECK


def test_deleted_dependency_and_changed_edge_are_not_preserved() -> None:
    before, record, hashes, ids = _fixture()
    after = _copy(before)
    after.edges = {edge for edge in after.edges if edge.target_id != ids["stackup"]}
    report = _assess(record, before, after, hashes)
    assert report.state is EvidenceFreshnessState.INVALIDATED
    assert "changed_relevant_dependency_edge" in [r.code for r in report.reasons]

    after2 = _copy(before)
    after2.edges = {edge for edge in after2.edges if edge.target_id != ids["stackup"]}
    after2.entities.pop(ids["stackup"])
    report2 = _assess(record, before, after2, hashes)
    assert report2.state is EvidenceFreshnessState.INVALIDATED


def test_missing_graph_record_or_dependency_mapping_requires_recheck() -> None:
    before, record, hashes, ids = _fixture()
    unlinked = _copy(before)
    unlinked.edges = {
        edge
        for edge in unlinked.edges
        if not (edge.kind is GraphEdgeKind.DEPENDS_ON and edge.target_id == ids["usb"])
    }
    assert _assess(record, unlinked, _copy(unlinked), hashes).state is (
        EvidenceFreshnessState.REQUIRES_RECHECK
    )
    missing_record = _copy(before)
    missing_record.entities.pop(evidence_graph_id(record))
    missing_record.edges.clear()
    assert _assess(record, missing_record, _copy(missing_record), hashes).state is (
        EvidenceFreshnessState.REQUIRES_RECHECK
    )


def test_conflicting_evidence_record_rejected_without_graph_mutation() -> None:
    graph, record, _, _ = _fixture()
    initial = graph.to_document()
    different = record.model_copy(update={"source_sha256": E})
    provenance = _provenance()
    with pytest.raises(ValueError, match="conflicting entity"):
        attach_evidence_record(graph, different, provenance=provenance)
    assert graph.to_document() == initial


def test_missing_dependency_rejected_atomically() -> None:
    graph, record, _, ids = _fixture()
    before = graph.to_document()
    more = record.model_copy(
        update={"evidence_id": "EVID-USB-Z1", "contract_id": None, "contract_version": None}
    )
    absent = canonical_entity_id(PROJECT, GraphEntityKind.NET, "NOT_A_NET")
    inputs = tuple(
        sorted(
            [*more.inputs, {"entity_id": absent, "sha256": E}],
            key=lambda item: item.entity_id if hasattr(item, "entity_id") else item["entity_id"],
        )
    )
    # Revalidate after the intentional type-preserving edit to the record.
    updated = EvidenceRecord.model_validate(
        {
            **more.model_dump(),
            "inputs": [
                item.model_dump() if hasattr(item, "model_dump") else item for item in inputs
            ],
        }
    )
    provenance = _provenance()
    with pytest.raises(ValueError, match="missing evidence dependencies"):
        attach_evidence_record(graph, updated, provenance=provenance)
    assert graph.to_document() == before
    assert ids["usb"] in graph.entities


def test_explicit_revision_binding_for_approval_and_waiver() -> None:
    graph, base, _, _ = _fixture()
    for kind in ("approval", "waiver"):
        verified = EvidenceRecord.model_validate(
            {**base.model_dump(), "evidence_id": f"{kind.upper()}-1", "kind": kind}
        )
        assert verified.contract_id == "INTENT-USB-SI"
        assert verified.contract_version == 1
        attach_evidence_record(graph, verified, provenance=_provenance())
        assert evidence_graph_id(verified) in graph.entities

    no_contract = {
        **base.model_dump(),
        "kind": "approval",
        "contract_id": None,
        "contract_version": None,
    }
    with pytest.raises(ValidationError, match="exact contract revision"):
        EvidenceRecord.model_validate(no_contract)


def test_timestamp_digest_identity_and_input_contract_validation() -> None:
    _, rec, hashes, ids = _fixture()
    assert EvidenceRecord.model_validate_json(rec.model_dump_json()) == rec
    changed = rec.model_dump()
    changed["captured_at"] = "2026-09-30T12:00:00"
    with pytest.raises(ValidationError, match="UTC timezone"):
        EvidenceRecord.model_validate(changed)
    changed = rec.model_dump()
    changed["inputs"] = [{"entity_id": ids["usb"], "sha256": "bad"}]
    with pytest.raises(ValidationError, match="sha256"):
        EvidenceRecord.model_validate(changed)
    changed = rec.model_dump()
    changed["inputs"] = list(reversed(changed["inputs"]))
    with pytest.raises(ValidationError, match="unique and sorted"):
        EvidenceRecord.model_validate(changed)
    changed = rec.model_dump()
    changed["contract_version"] = None
    with pytest.raises(ValidationError, match="appear together"):
        EvidenceRecord.model_validate(changed)
    assert hashes


def test_project_mismatch_requires_recheck_and_attach_rejects() -> None:
    graph, record, hashes, _ = _fixture()
    other = EngineeringGraph(project_key="different")
    provenance = _provenance()
    with pytest.raises(ValueError, match="project identity mismatch"):
        attach_evidence_record(other, record, provenance=provenance)
    report = _assess(record, graph, other, hashes)
    assert report.state is EvidenceFreshnessState.REQUIRES_RECHECK


def test_missing_explicit_contract_digest_binding_rejected() -> None:
    before, rec, _, ids = _fixture()
    payload = rec.model_dump()
    payload["inputs"] = [
        {"entity_id": ids["usb"], "sha256": A},
        {"entity_id": ids["stackup"], "sha256": B},
    ]
    payload["inputs"] = sorted(payload["inputs"], key=lambda entry: entry["entity_id"])
    copied = EvidenceRecord.model_validate(payload)
    provenance = _provenance()
    graph = _copy(before)
    with pytest.raises(ValueError, match="explicitly hashed"):
        attach_evidence_record(graph, copied, provenance=provenance)


def test_tampered_or_narrowed_record_cannot_report_still_valid() -> None:
    graph, record, hashes, _ = _fixture()
    modified = record.model_copy(update={"inputs": record.inputs[:-1]})
    report = _assess(modified, graph, _copy(graph), hashes)
    assert report.state is EvidenceFreshnessState.REQUIRES_RECHECK
    assert "evidence_record_payload_mismatch" in [reason.code for reason in report.reasons]


def test_repeated_identical_record_attachment_is_idempotent() -> None:
    graph, record, _, _ = _fixture()
    before = graph.to_document()
    assert attach_evidence_record(graph, record, provenance=_provenance()) == evidence_graph_id(
        record
    )
    assert graph.to_document() == before


def test_versioned_evidence_schema_fixture_is_exact_and_reproducible() -> None:
    path = (
        Path(__file__).resolve().parents[2]
        / "src/kicad_mcp/project/schemas/evidence-freshness-v1.schema.json"
    )
    fixture = json.loads(path.read_text(encoding="utf-8"))
    assert fixture == evidence_record_json_schema()
    assert fixture["properties"]["schema_version"]["const"] == 1


def test_undeclared_extra_graph_dependency_cannot_produce_still_valid() -> None:
    before, record, hashes, ids = _fixture()
    before.add_edge(GraphEdge(evidence_graph_id(record), ids["u8"], GraphEdgeKind.DEPENDS_ON))
    report = _assess(record, before, _copy(before), hashes)
    assert report.state is EvidenceFreshnessState.REQUIRES_RECHECK
    assert "dependency_manifest_link_mismatch" in [reason.code for reason in report.reasons]


def test_runtime_invalid_digest_type_requires_recheck_instead_of_crashing() -> None:
    before, record, hashes, ids = _fixture()
    malformed = {**hashes, ids["usb"]: 5}
    report = _assess(record, before, _copy(before), malformed)
    assert report.state is EvidenceFreshnessState.REQUIRES_RECHECK
    assert "current_input_hash_missing_or_invalid" in [reason.code for reason in report.reasons]
