"""Current-state exact hash resolver for persisted EvidenceRecord dependencies."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping

from ..ir.engineering_graph import EngineeringGraph, GraphEntity
from .evidence_freshness import (
    EvidenceFreshnessState,
    EvidenceRecord,
    FreshnessAssessment,
    InvalidationReason,
)

_SHA256_HEX = frozenset("0123456789abcdef")


def canonical_graph_entity_sha256(entity: GraphEntity) -> str:
    """Hash one canonical GraphEntity document deterministically."""
    payload = entity.to_dict()
    # Attribute list order is preserved intentionally: some GraphEntity attributes
    # encode semantic sequence. Builders must canonicalize unordered collections
    # before entity construction; only native_links are explicitly order-insensitive.
    payload["native_links"] = sorted(
        payload.get("native_links") or [],
        key=lambda item: (
            str(item.get("system", "")),
            str(item.get("kind", "")),
            str(item.get("key", "")),
            str(item.get("uuid") or ""),
        ),
    )
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def graph_entity_hashes(
    graph: EngineeringGraph,
    entity_ids: tuple[str, ...],
) -> tuple[dict[str, str], tuple[str, ...]]:
    hashes: dict[str, str] = {}
    missing: list[str] = []
    for entity_id in sorted(set(entity_ids)):
        entity = graph.entity(entity_id)
        if entity is None:
            missing.append(entity_id)
            continue
        hashes[entity_id] = canonical_graph_entity_sha256(entity)
    return hashes, tuple(missing)


def _valid_sha256(value: str | None) -> bool:
    return (
        isinstance(value, str) and len(value) == 64 and all(char in _SHA256_HEX for char in value)
    )


def assess_evidence_current_state(
    record: EvidenceRecord,
    *,
    graph: EngineeringGraph,
    current_source_sha256: str | None,
    current_hashes: Mapping[str, str] | None = None,
) -> FreshnessAssessment:
    """Assess complete exact evidence against the current authoritative graph state."""
    unresolved: list[InvalidationReason] = []
    invalidated: list[InvalidationReason] = []

    if record.project_key != graph.project_key:
        unresolved.append(InvalidationReason(code="project_identity_mismatch"))
    if not record.dependency_manifest_complete:
        unresolved.append(InvalidationReason(code="unknown_dependency_or_mutation_scope"))

    if not _valid_sha256(current_source_sha256):
        unresolved.append(InvalidationReason(code="current_source_hash_missing_or_invalid"))
    elif current_source_sha256 != record.source_sha256:
        invalidated.append(InvalidationReason(code="source_hash_changed"))

    resolved_hashes: Mapping[str, str]
    if current_hashes is None:
        resolved_hashes, missing_tuple = graph_entity_hashes(
            graph, tuple(entry.entity_id for entry in record.inputs)
        )
        missing = set(missing_tuple)
    else:
        resolved_hashes = current_hashes
        missing = {
            entry.entity_id for entry in record.inputs if graph.entity(entry.entity_id) is None
        }
    unresolved.extend(
        InvalidationReason(code="unresolved_dependency_entity", entity_id=entity_id)
        for entity_id in sorted(missing)
    )

    for entry in record.inputs:
        if entry.entity_id in missing:
            continue
        digest = resolved_hashes.get(entry.entity_id)
        if not _valid_sha256(digest):
            unresolved.append(
                InvalidationReason(
                    code="current_input_hash_missing_or_invalid",
                    entity_id=entry.entity_id,
                )
            )
        elif digest != entry.sha256:
            invalidated.append(
                InvalidationReason(
                    code="exact_input_hash_changed",
                    entity_id=entry.entity_id,
                )
            )

    if invalidated:
        return FreshnessAssessment(
            evidence_id=record.evidence_id,
            state=EvidenceFreshnessState.INVALIDATED,
            reasons=tuple(invalidated),
        )
    if unresolved:
        return FreshnessAssessment(
            evidence_id=record.evidence_id,
            state=EvidenceFreshnessState.REQUIRES_RECHECK,
            reasons=tuple(unresolved),
        )
    return FreshnessAssessment(
        evidence_id=record.evidence_id,
        state=EvidenceFreshnessState.STILL_VALID,
    )
