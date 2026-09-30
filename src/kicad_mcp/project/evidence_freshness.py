"""Evidence freshness v1: exact-input proof over Engineering Graph dependencies.

This pure project layer never infers a fresh result from absence of a broad
intent change. Unknown input hashes, dependency closure or mutation scope
always produce requires_recheck; native KiCad remains the authority.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from ..ir.engineering_graph import (
    EngineeringGraph,
    GraphDiffKind,
    GraphEdge,
    GraphEdgeKind,
    GraphEntity,
    GraphEntityKind,
    GraphProvenance,
    canonical_entity_id,
    engineering_graph_diff,
)
from .hardware_intent_contract import StrictContractModel

_SHA256_PATTERN = r"^[0-9a-f]{64}$"
_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.:/-]*$"


class EvidenceRecordKind(StrEnum):
    ARTIFACT = "evidence_artifact"
    VERIFICATION_RUN = "verification_run"
    MEASUREMENT = "measurement"
    APPROVAL = "approval"
    WAIVER = "waiver"


class EvidenceFreshnessState(StrEnum):
    STILL_VALID = "still_valid"
    REQUIRES_RECHECK = "requires_recheck"
    INVALIDATED = "invalidated"


class EvidenceInputDigest(StrictContractModel):
    """Hash of one explicitly declared, relevant authoritative graph input."""

    entity_id: str = Field(min_length=1, max_length=180)
    sha256: str = Field(pattern=_SHA256_PATTERN)


class EvidenceRecord(StrictContractModel):
    """Versioned immutable evidence envelope; no synthetic verification claims."""

    schema_version: Literal[1]
    evidence_id: str = Field(min_length=3, max_length=128, pattern=_ID_PATTERN)
    kind: EvidenceRecordKind
    project_key: str = Field(min_length=1, max_length=128)
    source_revision: str = Field(min_length=1, max_length=256)
    source_sha256: str = Field(pattern=_SHA256_PATTERN)
    producer: str = Field(min_length=1, max_length=128)
    producer_version: str = Field(min_length=1, max_length=64)
    captured_at: datetime
    dependency_manifest_complete: bool
    inputs: tuple[EvidenceInputDigest, ...] = Field(min_length=1)
    contract_id: str | None = Field(default=None, min_length=3, max_length=120, pattern=_ID_PATTERN)
    contract_version: int | None = Field(default=None, ge=1)
    provenance_source: str = Field(min_length=1, max_length=256)

    @field_validator("captured_at")
    @classmethod
    def require_utc_timestamp(cls, value: datetime) -> datetime:
        if value.utcoffset() != timedelta(0):
            raise ValueError("captured_at must carry explicit UTC timezone")
        return value

    @model_validator(mode="after")
    def validate_manifest(self) -> EvidenceRecord:
        entity_ids = [entry.entity_id for entry in self.inputs]
        if entity_ids != sorted(entity_ids) or len(set(entity_ids)) != len(entity_ids):
            raise ValueError("input entity IDs must be unique and sorted")
        if (self.contract_id is None) != (self.contract_version is None):
            raise ValueError("contract ID and version must appear together")
        if self.kind in {EvidenceRecordKind.APPROVAL, EvidenceRecordKind.WAIVER}:
            if self.contract_id is None:
                raise ValueError("approval and waiver records need an exact contract revision")
        return self


class InvalidationReason(StrictContractModel):
    code: str = Field(min_length=1, max_length=80)
    entity_id: str = ""
    detail: str = ""


class FreshnessAssessment(StrictContractModel):
    evidence_id: str
    state: EvidenceFreshnessState
    reasons: tuple[InvalidationReason, ...] = ()


def evidence_graph_kind(record: EvidenceRecord) -> GraphEntityKind:
    if record.kind is EvidenceRecordKind.VERIFICATION_RUN:
        return GraphEntityKind.VERIFICATION_RUN
    if record.kind is EvidenceRecordKind.APPROVAL:
        return GraphEntityKind.APPROVAL
    if record.kind is EvidenceRecordKind.WAIVER:
        return GraphEntityKind.WAIVER
    return GraphEntityKind.EVIDENCE_ARTIFACT


def evidence_graph_id(record: EvidenceRecord) -> str:
    """Stable v1 evidence ID independent of native object UUIDs."""
    return canonical_entity_id(
        record.project_key,
        evidence_graph_kind(record),
        f"{record.kind.value}:{record.evidence_id}",
    )


def attach_evidence_record(
    graph: EngineeringGraph, record: EvidenceRecord, *, provenance: GraphProvenance
) -> str:
    """Persist existing dependencies atomically without inventing native facts."""
    if graph.project_key != record.project_key:
        raise ValueError("evidence project identity mismatch")
    dependency_ids = {entry.entity_id for entry in record.inputs}
    if record.contract_id is not None:
        contract_id = canonical_entity_id(
            graph.project_key, GraphEntityKind.INTENT_CONTRACT, record.contract_id
        )
        if contract_id not in dependency_ids:
            raise ValueError("contract must be an explicitly hashed evidence dependency")
    missing = dependency_ids - graph.entities.keys()
    if missing:
        raise ValueError("missing evidence dependencies: " + ", ".join(sorted(missing)))
    entity_id = evidence_graph_id(record)
    entity = GraphEntity(
        entity_id=entity_id,
        kind=evidence_graph_kind(record),
        stable_key=f"{record.kind.value}:{record.evidence_id}",
        attributes={"record": record.model_dump(mode="json")},
        provenance=provenance,
    )
    graph.add_entity(entity)
    for dependency_id in sorted(dependency_ids):
        graph.add_edge(GraphEdge(entity_id, dependency_id, GraphEdgeKind.DEPENDS_ON))
    return entity_id


def _result(
    record: EvidenceRecord,
    state: EvidenceFreshnessState,
    reasons: list[InvalidationReason],
) -> FreshnessAssessment:
    return FreshnessAssessment(evidence_id=record.evidence_id, state=state, reasons=tuple(reasons))


def _known_mutations(
    before: EngineeringGraph, after: EngineeringGraph
) -> tuple[set[str], set[str]]:
    """Find changed entity IDs and incident edge endpoints by semantic diff."""
    entities: set[str] = set()
    endpoints: set[str] = set()
    for change in engineering_graph_diff(before, after):
        if change.kind in {
            GraphDiffKind.ENTITY_ADDED,
            GraphDiffKind.ENTITY_CHANGED,
            GraphDiffKind.ENTITY_REMOVED,
        }:
            entities.add(change.subject_id)
        elif isinstance(change.before, GraphEdge):
            endpoints.update((change.before.source_id, change.before.target_id))
        elif isinstance(change.after, GraphEdge):
            endpoints.update((change.after.source_id, change.after.target_id))
    return entities, endpoints


def _dependency_impact(
    before: EngineeringGraph, after: EngineeringGraph, changed: set[str]
) -> set[str]:
    impacted = set(changed)
    for graph in (before, after):
        known = changed & graph.entities.keys()
        if known:
            impacted.update(graph.impacted_by(known))
    return impacted


def _input_hash_reasons(
    record: EvidenceRecord, current_hashes: Mapping[str, str]
) -> tuple[list[InvalidationReason], list[InvalidationReason]]:
    definite: list[InvalidationReason] = []
    unresolved: list[InvalidationReason] = []
    for entry in record.inputs:
        digest = current_hashes.get(entry.entity_id)
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(c not in "0123456789abcdef" for c in digest)
        ):
            unresolved.append(
                InvalidationReason(
                    code="current_input_hash_missing_or_invalid", entity_id=entry.entity_id
                )
            )
        elif digest != entry.sha256:
            definite.append(
                InvalidationReason(code="exact_input_hash_changed", entity_id=entry.entity_id)
            )
    return definite, unresolved


def _graph_manifest_reasons(
    record: EvidenceRecord,
    *,
    before: EngineeringGraph,
    after: EngineeringGraph,
    evidence_id: str,
    dependencies: set[str],
) -> list[InvalidationReason]:
    """Check immutable record and complete, exact graph dependency links."""
    unresolved: list[InvalidationReason] = []
    persisted_payload = record.model_dump(mode="json")
    for graph in (before, after):
        stored = graph.entity(evidence_id)
        if stored is None:
            unresolved.append(InvalidationReason(code="evidence_graph_record_missing"))
        elif stored.attributes.get("record") != persisted_payload:
            unresolved.append(InvalidationReason(code="evidence_record_payload_mismatch"))
    if not dependencies <= before.entities.keys() or not dependencies <= after.entities.keys():
        unresolved.append(InvalidationReason(code="unresolved_dependency_entity"))
    for graph in (before, after):
        linked = {
            edge.target_id
            for edge in graph.edges
            if edge.source_id == evidence_id and edge.kind is GraphEdgeKind.DEPENDS_ON
        }
        if linked != dependencies:
            unresolved.append(InvalidationReason(code="dependency_manifest_link_mismatch"))
    return unresolved


def assess_evidence_freshness(
    record: EvidenceRecord,
    *,
    before: EngineeringGraph,
    after: EngineeringGraph,
    current_hashes: Mapping[str, str],
    mutation_scope_known: bool,
) -> FreshnessAssessment:
    """Classify exact graph+hash evidence; uncertainty never yields PASS."""
    if record.project_key != before.project_key or before.project_key != after.project_key:
        return _result(
            record,
            EvidenceFreshnessState.REQUIRES_RECHECK,
            [InvalidationReason(code="project_identity_mismatch")],
        )
    evidence_id = evidence_graph_id(record)
    dependencies = {entry.entity_id for entry in record.inputs}
    definite, unresolved = _input_hash_reasons(record, current_hashes)

    if not mutation_scope_known or not record.dependency_manifest_complete:
        unresolved.append(InvalidationReason(code="unknown_dependency_or_mutation_scope"))
    unresolved.extend(
        _graph_manifest_reasons(
            record,
            before=before,
            after=after,
            evidence_id=evidence_id,
            dependencies=dependencies,
        )
    )

    changed, edge_endpoints = _known_mutations(before, after)
    implicated = _dependency_impact(before, after, changed)
    if implicated.intersection(dependencies | {evidence_id}):
        definite.append(InvalidationReason(code="changed_relevant_graph_entity"))
    if edge_endpoints.intersection(dependencies | {evidence_id}):
        definite.append(InvalidationReason(code="changed_relevant_dependency_edge"))

    if definite:
        return _result(record, EvidenceFreshnessState.INVALIDATED, definite)
    if unresolved:
        return _result(record, EvidenceFreshnessState.REQUIRES_RECHECK, unresolved)
    return _result(record, EvidenceFreshnessState.STILL_VALID, [])


EVIDENCE_FRESHNESS_SCHEMA_ID = (
    "https://raw.githubusercontent.com/oaslananka/kicad-mcp-pro/main/"
    "src/kicad_mcp/project/schemas/evidence-freshness-v1.schema.json"
)


def evidence_record_json_schema() -> dict[str, Any]:
    """Deterministic v1 JSON Schema draft 2020-12 export."""
    schema = EvidenceRecord.model_json_schema(mode="validation")
    schema["$id"] = EVIDENCE_FRESHNESS_SCHEMA_ID
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    return schema
