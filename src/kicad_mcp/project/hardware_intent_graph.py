"""Fail-closed, graph-local links for explicit HardwareIntentContract v1 records."""

from __future__ import annotations

from ..ir.engineering_graph import (
    EngineeringGraph,
    GraphEdge,
    GraphEdgeKind,
    GraphEntity,
    GraphEntityKind,
    GraphProvenance,
    canonical_entity_id,
)
from .hardware_intent_contract import HardwareIntentContract

_SCOPE_ENTITY_KIND = {
    "project": GraphEntityKind.PROJECT,
    "component": GraphEntityKind.COMPONENT,
    "net": GraphEntityKind.NET,
    "interface": GraphEntityKind.INTERFACE,
    "rail": GraphEntityKind.POWER_RAIL,
    "artifact": GraphEntityKind.EVIDENCE_ARTIFACT,
}


def link_hardware_intent_contract(
    graph: EngineeringGraph,
    contract: HardwareIntentContract,
    *,
    provenance: GraphProvenance,
) -> str:
    """Link an already approved record without fabricating missing graph entities.

    Region selectors are valid *contract* metadata, but Graph v1 has no native
    region entity kind. They must remain unresolved until an explicit mapping is
    available; treating a region as a constraint would invent a semantic link.

    Existing contract IDs are stable. A changed version is not silently inserted
    over a previously linked version; graph callers must explicitly rebuild or
    reconcile those records through the graph change process.
    """
    target_kind = _SCOPE_ENTITY_KIND.get(contract.applicability.kind)
    if target_kind is None:
        raise ValueError("region scope has no Engineering Graph v1 entity mapping")

    requirement_id = canonical_entity_id(
        graph.project_key, GraphEntityKind.REQUIREMENT, contract.requirement_id
    )
    target_id = canonical_entity_id(graph.project_key, target_kind, contract.applicability.key)
    if graph.entity(requirement_id) is None:
        raise ValueError("referenced requirement must already exist in Engineering Graph")
    if graph.entity(target_id) is None:
        raise ValueError("applicability target must already exist in Engineering Graph")

    contract_id = canonical_entity_id(
        graph.project_key, GraphEntityKind.INTENT_CONTRACT, contract.contract_id
    )
    entity = GraphEntity(
        entity_id=contract_id,
        kind=GraphEntityKind.INTENT_CONTRACT,
        stable_key=contract.contract_id,
        attributes={"contract": contract.model_dump(mode="json")},
        provenance=provenance,
    )
    # All semantic prerequisites are checked before the first graph mutation.
    graph.add_entity(entity)
    graph.add_edge(GraphEdge(requirement_id, contract_id, GraphEdgeKind.REFERENCES))
    graph.add_edge(GraphEdge(contract_id, target_id, GraphEdgeKind.APPLIES_TO))
    return contract_id
