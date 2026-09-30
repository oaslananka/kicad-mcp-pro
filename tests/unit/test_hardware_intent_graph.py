"""#941: deterministic Requirement/IntentContract/target graph links."""

from __future__ import annotations

import pytest

from kicad_mcp.ir.engineering_graph import (
    EngineeringGraph,
    GraphEntity,
    GraphEntityKind,
    GraphProvenance,
    GraphProvenanceKind,
    canonical_entity_id,
)
from kicad_mcp.project.hardware_intent_contract import HardwareIntentContract
from kicad_mcp.project.hardware_intent_graph import link_hardware_intent_contract


def _record(**overrides: object) -> HardwareIntentContract:
    fields: dict[str, object] = {
        "schema_version": 1,
        "contract_id": "INTENT-USB-001",
        "contract_version": 1,
        "requirement_id": "REQ-USB-001",
        "applicability": {"kind": "net", "key": "USB_DP"},
        "severity": "blocking",
        "release_blocking": True,
        "verification": [{"method_ref": "drc", "evidence_classes": ["drc"]}],
    }
    fields.update(overrides)
    return HardwareIntentContract.model_validate(fields)


def _graph() -> EngineeringGraph:
    graph = EngineeringGraph(project_key="demo-project")
    for kind, key in [
        (GraphEntityKind.REQUIREMENT, "REQ-USB-001"),
        (GraphEntityKind.NET, "USB_DP"),
    ]:
        graph.add_entity(
            GraphEntity(
                entity_id=canonical_entity_id(graph.project_key, kind, key),
                kind=kind,
                stable_key=key,
            )
        )
    return graph


def _provenance() -> GraphProvenance:
    return GraphProvenance(GraphProvenanceKind.USER_AUTHORED, source="test")


def test_requirement_contract_net_impact_chain_and_idempotency() -> None:
    graph = _graph()
    contract_id = link_hardware_intent_contract(graph, _record(), provenance=_provenance())
    contract_entity = graph.entity(contract_id)
    assert contract_entity is not None
    assert contract_entity.kind is GraphEntityKind.INTENT_CONTRACT
    requirement_id = canonical_entity_id(
        graph.project_key, GraphEntityKind.REQUIREMENT, "REQ-USB-001"
    )
    net_id = canonical_entity_id(graph.project_key, GraphEntityKind.NET, "USB_DP")
    assert contract_id in graph.dependencies_of(requirement_id)
    assert net_id in graph.dependencies_of(contract_id)
    assert {contract_id, requirement_id} <= graph.impacted_by({net_id})
    edges_before = len(graph.edges)
    assert link_hardware_intent_contract(graph, _record(), provenance=_provenance()) == contract_id
    assert len(graph.edges) == edges_before
    assert EngineeringGraph.from_document(graph.to_document()).to_document() == graph.to_document()


def test_missing_requirement_or_target_and_region_fail_before_mutation() -> None:
    graph = _graph()
    provenance = _provenance()
    before = graph.to_document()
    missing_requirement = _record(requirement_id="REQ-UNKNOWN")
    missing_target = _record(applicability={"kind": "component", "key": "U7"})
    unsupported_region = _record(applicability={"kind": "region", "key": "rf-zone"})

    with pytest.raises(ValueError, match="referenced requirement"):
        link_hardware_intent_contract(graph, missing_requirement, provenance=provenance)
    with pytest.raises(ValueError, match="applicability target"):
        link_hardware_intent_contract(graph, missing_target, provenance=provenance)
    with pytest.raises(ValueError, match="region scope"):
        link_hardware_intent_contract(graph, unsupported_region, provenance=provenance)
    assert graph.to_document() == before


def test_contract_revision_conflict_never_rebinds_silently() -> None:
    graph = _graph()
    provenance = _provenance()
    initial = _record()
    conflicting_revision = _record(contract_version=2)
    link_hardware_intent_contract(graph, initial, provenance=provenance)
    before = graph.to_document()
    with pytest.raises(ValueError, match="conflicting entity"):
        link_hardware_intent_contract(graph, conflicting_revision, provenance=provenance)
    assert graph.to_document() == before
