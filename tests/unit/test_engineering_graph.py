"""Focused Engineering Graph v1 core tests for issue #940."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from kicad_mcp.ir import (
    IRCircuit,
    IRComponent,
    IRConstraint,
    IRInterface,
    IRNet,
    IRPin,
    IRPowerRail,
    graph_from_circuit,
    update_graph_from_circuit,
)
from kicad_mcp.ir.engineering_graph import (
    DRAFT_ENGINEERING_GRAPH_SCHEMA_VERSION,
    ENGINEERING_GRAPH_SCHEMA_VERSION,
    EngineeringGraph,
    GraphDiffKind,
    GraphEdge,
    GraphEdgeKind,
    GraphEntity,
    GraphEntityKind,
    GraphProvenance,
    GraphProvenanceKind,
    canonical_entity_id,
    engineering_graph_diff,
)


def _entity(
    graph: EngineeringGraph,
    kind: GraphEntityKind,
    stable_key: str,
    *,
    attributes: dict[str, object] | None = None,
) -> GraphEntity:
    entity = GraphEntity(
        entity_id=canonical_entity_id(graph.project_key, kind, stable_key),
        kind=kind,
        stable_key=stable_key,
        attributes=attributes or {},
        provenance=GraphProvenance(GraphProvenanceKind.USER_AUTHORED, source="test"),
    )
    graph.add_entity(entity)
    return entity


def _sample_circuit(*, source_path: str = "fixtures/board/main.kicad_sch") -> IRCircuit:
    circuit = IRCircuit(
        source_path=source_path,
        source_uuid="10000000-0000-0000-0000-100000000001",
        title="main",
    )
    circuit.components["U7"] = IRComponent(
        "U7",
        "MCU:STM32",
        "STM32G4",
        "Package_QFP:LQFP-64",
        pins=(IRPin("1", "VDD"), IRPin("2", "USB_DP")),
    )
    circuit.nets["USB_DP"] = IRNet(
        "USB_DP",
        connections=frozenset({("U7", "2")}),
    )
    circuit.interfaces["USB"] = IRInterface(
        "USB",
        "usb",
        net_roles={"dp": "USB_DP"},
        refs=("U7",),
    )
    circuit.constraints["usb_impedance"] = IRConstraint(
        "impedance",
        net_names=frozenset({"USB_DP"}),
        params={"target_ohm": 90},
    )
    return circuit


def test_graph_ids_survive_equivalent_ir_rebuild_and_path_change() -> None:
    first = graph_from_circuit(_sample_circuit(source_path="fixtures/a/main.kicad_sch"))
    second = graph_from_circuit(_sample_circuit(source_path="fixtures/b/main.kicad_sch"))

    first_ids = {
        (entity.kind, entity.stable_key): entity.entity_id
        for entity in first.entities.values()
        if entity.kind is not GraphEntityKind.PROJECT
    }
    second_ids = {
        (entity.kind, entity.stable_key): entity.entity_id
        for entity in second.entities.values()
        if entity.kind is not GraphEntityKind.PROJECT
    }

    assert first_ids == second_ids
    assert first.entities_of_kind(GraphEntityKind.COMPONENT)[0].stable_key == "U7"


def test_incremental_component_update_preserves_unrelated_graph_subtree() -> None:
    before = _sample_circuit()
    before.components["U8"] = IRComponent(
        "U8",
        "Device:R",
        "10k",
        "Resistor_SMD:R_0603_1608Metric",
        pins=(IRPin("1", "1"), IRPin("2", "2")),
    )
    after = _sample_circuit()
    after.components["U8"] = before.components["U8"]
    after.components["U7"] = replace(after.components["U7"], value="STM32H5")

    graph = graph_from_circuit(before)
    u7_id = canonical_entity_id(graph.project_key, GraphEntityKind.COMPONENT, "U7")
    u8_id = canonical_entity_id(graph.project_key, GraphEntityKind.COMPONENT, "U8")
    u8_before = graph.entity(u8_id)
    u8_pin_ids = {
        entity.entity_id
        for entity in graph.entities_of_kind(GraphEntityKind.PIN)
        if entity.stable_key.startswith("U8:")
    }

    result = update_graph_from_circuit(graph, before, after)
    clean_rebuild = graph_from_circuit(after)

    assert result.updated_entity_ids == frozenset({u7_id})
    assert result.work_units == 1
    assert u8_id in result.preserved_entity_ids
    assert u8_pin_ids <= result.preserved_entity_ids
    assert graph.entity(u8_id) is u8_before
    updated_u7 = graph.entity(u7_id)
    assert updated_u7 is not None
    assert updated_u7.attributes["value"] == "STM32H5"
    assert engineering_graph_diff(graph, clean_rebuild) == []


def test_incremental_update_preconditions_fail_without_partial_mutation() -> None:
    before = _sample_circuit()
    before.components["U8"] = IRComponent(
        "U8",
        "Device:R",
        "10k",
        "Resistor_SMD:R_0603_1608Metric",
    )
    after = _sample_circuit()
    after.components["U7"] = replace(after.components["U7"], value="STM32H5")
    after.components["U8"] = replace(before.components["U8"], value="22k")

    graph = graph_from_circuit(before)
    u7_id = canonical_entity_id(graph.project_key, GraphEntityKind.COMPONENT, "U7")
    u8_id = canonical_entity_id(graph.project_key, GraphEntityKind.COMPONENT, "U8")
    u7_before = graph.entity(u7_id)
    u8_before = graph.entity(u8_id)
    assert u8_before is not None
    graph.entities[u8_id] = replace(u8_before, attributes={"value": "stale"})

    with pytest.raises(ValueError, match="does not match the declared before-state"):
        update_graph_from_circuit(graph, before, after)

    assert graph.entity(u7_id) is u7_before


def test_incremental_update_rejects_project_metadata_change() -> None:
    before = _sample_circuit()
    after = _sample_circuit()
    after.title = "renamed"
    graph = graph_from_circuit(before)

    with pytest.raises(ValueError, match="project metadata changed"):
        update_graph_from_circuit(graph, before, after)


def test_incremental_update_rejects_net_state_change() -> None:
    before = _sample_circuit()
    after = _sample_circuit()
    after.nets["USB_DP"] = replace(after.nets["USB_DP"], net_class="USB")
    graph = graph_from_circuit(before)

    with pytest.raises(ValueError, match="non-component circuit state changed"):
        update_graph_from_circuit(graph, before, after)


def test_incremental_update_rejects_component_pin_structure_change() -> None:
    before = _sample_circuit()
    after = _sample_circuit()
    after.components["U7"] = replace(
        after.components["U7"],
        pins=(*after.components["U7"].pins, IRPin("3", "USB_DN")),
    )
    graph = graph_from_circuit(before)

    with pytest.raises(ValueError, match="component pin structure changed"):
        update_graph_from_circuit(graph, before, after)


def test_incremental_update_rejects_structural_changes_instead_of_rebuilding() -> None:
    before = _sample_circuit()
    after = _sample_circuit()
    after.components["U8"] = IRComponent(
        "U8",
        "Device:R",
        "10k",
        "Resistor_SMD:R_0603_1608Metric",
    )
    graph = graph_from_circuit(before)

    with pytest.raises(ValueError, match="full Engineering Graph rebuild required"):
        update_graph_from_circuit(graph, before, after)


def test_graph_from_circuit_preserves_semantic_entities_and_native_links() -> None:
    graph = graph_from_circuit(_sample_circuit())

    assert len(graph.entities_of_kind(GraphEntityKind.COMPONENT)) == 1
    assert len(graph.entities_of_kind(GraphEntityKind.PIN)) == 2
    assert len(graph.entities_of_kind(GraphEntityKind.NET)) == 1
    assert len(graph.entities_of_kind(GraphEntityKind.INTERFACE)) == 1
    assert len(graph.entities_of_kind(GraphEntityKind.CONSTRAINT)) == 1

    component = graph.entities_of_kind(GraphEntityKind.COMPONENT)[0]
    assert component.attributes["value"] == "STM32G4"
    assert component.native_links[0].key == "U7"
    constraint = graph.entities_of_kind(GraphEntityKind.CONSTRAINT)[0]
    assert graph.dependencies_of(constraint.entity_id) == {
        graph.entities_of_kind(GraphEntityKind.NET)[0].entity_id
    }


def test_adapter_requires_explicit_project_identity_without_source_uuid() -> None:
    circuit = IRCircuit(title="ambiguous")

    with pytest.raises(ValueError, match="project_key is required"):
        graph_from_circuit(circuit)

    graph = graph_from_circuit(circuit, project_key="fixture-project")
    assert graph.project_key == "fixture-project"


def test_requirement_net_interface_verification_evidence_chain_is_queryable() -> None:
    graph = EngineeringGraph(project_key="demo-project")
    component = _entity(graph, GraphEntityKind.COMPONENT, "U7")
    net = _entity(graph, GraphEntityKind.NET, "USB_DP")
    interface = _entity(graph, GraphEntityKind.INTERFACE, "USB")
    requirement = _entity(graph, GraphEntityKind.REQUIREMENT, "REQ-USB-001")
    verification = _entity(graph, GraphEntityKind.VERIFICATION_RUN, "verify-usb-001")
    evidence = _entity(graph, GraphEntityKind.EVIDENCE_ARTIFACT, "usb-drc.json")

    graph.add_edge(GraphEdge(requirement.entity_id, component.entity_id, GraphEdgeKind.APPLIES_TO))
    graph.add_edge(GraphEdge(requirement.entity_id, net.entity_id, GraphEdgeKind.APPLIES_TO))
    graph.add_edge(GraphEdge(requirement.entity_id, interface.entity_id, GraphEdgeKind.APPLIES_TO))
    graph.add_edge(
        GraphEdge(
            verification.entity_id,
            requirement.entity_id,
            GraphEdgeKind.DEPENDS_ON,
        )
    )
    graph.add_edge(GraphEdge(verification.entity_id, evidence.entity_id, GraphEdgeKind.PRODUCES))

    assert graph.dependencies_of(requirement.entity_id) == {
        component.entity_id,
        interface.entity_id,
        net.entity_id,
    }
    assert {
        requirement.entity_id,
        verification.entity_id,
        evidence.entity_id,
    } <= graph.impacted_by({net.entity_id})


def test_required_provenance_kinds_remain_distinct_across_persistence() -> None:
    graph = EngineeringGraph(project_key="demo-project")
    required_kinds = (
        GraphProvenanceKind.IMPORTED,
        GraphProvenanceKind.INFERRED,
        GraphProvenanceKind.USER_APPROVED,
        GraphProvenanceKind.TOOL_GENERATED,
    )
    for provenance_kind in required_kinds:
        stable_key = f"provenance:{provenance_kind.value}"
        graph.add_entity(
            GraphEntity(
                entity_id=canonical_entity_id(
                    graph.project_key,
                    GraphEntityKind.COMPONENT,
                    stable_key,
                ),
                kind=GraphEntityKind.COMPONENT,
                stable_key=stable_key,
                provenance=GraphProvenance(provenance_kind, source="acceptance-test"),
            )
        )

    restored = EngineeringGraph.from_document(graph.to_document())

    assert {
        entity.provenance.kind for entity in restored.entities_of_kind(GraphEntityKind.COMPONENT)
    } == set(required_kinds)


def test_u7_change_returns_requirement_contract_verification_and_evidence_impacts() -> None:
    graph = EngineeringGraph(project_key="demo-project")
    u7 = _entity(graph, GraphEntityKind.COMPONENT, "U7")
    u8 = _entity(graph, GraphEntityKind.COMPONENT, "U8")
    requirement = _entity(graph, GraphEntityKind.REQUIREMENT, "REQ-USB-001")
    contract = _entity(graph, GraphEntityKind.INTENT_CONTRACT, "INTENT-USB-001")
    verification = _entity(graph, GraphEntityKind.VERIFICATION_RUN, "verify-usb-001")
    evidence = _entity(graph, GraphEntityKind.EVIDENCE_ARTIFACT, "usb-drc.json")

    graph.add_edge(GraphEdge(requirement.entity_id, u7.entity_id, GraphEdgeKind.APPLIES_TO))
    graph.add_edge(GraphEdge(contract.entity_id, requirement.entity_id, GraphEdgeKind.DEPENDS_ON))
    graph.add_edge(GraphEdge(verification.entity_id, contract.entity_id, GraphEdgeKind.DEPENDS_ON))
    graph.add_edge(GraphEdge(verification.entity_id, u7.entity_id, GraphEdgeKind.VERIFIES))
    graph.add_edge(GraphEdge(verification.entity_id, evidence.entity_id, GraphEdgeKind.PRODUCES))

    impacted = graph.impacted_by({u7.entity_id})

    assert requirement.entity_id in impacted
    assert contract.entity_id in impacted
    assert verification.entity_id in impacted
    assert evidence.entity_id in impacted
    assert u8.entity_id not in impacted


def test_circuit_component_change_propagates_through_pins_to_connected_net() -> None:
    graph = graph_from_circuit(_sample_circuit())
    component = graph.entities_of_kind(GraphEntityKind.COMPONENT)[0]
    pin_ids = {entity.entity_id for entity in graph.entities_of_kind(GraphEntityKind.PIN)}
    net_id = graph.entities_of_kind(GraphEntityKind.NET)[0].entity_id

    impacted = graph.impacted_by({component.entity_id})

    assert pin_ids <= impacted
    assert net_id in impacted


def test_canonical_ids_disambiguate_project_and_stable_key_boundaries() -> None:
    first = canonical_entity_id("a/component/b", GraphEntityKind.COMPONENT, "c")
    second = canonical_entity_id("a", GraphEntityKind.COMPONENT, "b/component/c")

    assert first != second


def test_graph_rejects_noncanonical_persisted_entity_id() -> None:
    graph = EngineeringGraph(project_key="demo")
    invalid = GraphEntity(
        entity_id="eg:component:not-canonical",
        kind=GraphEntityKind.COMPONENT,
        stable_key="U7",
    )

    with pytest.raises(ValueError, match="does not match canonical id"):
        graph.add_entity(invalid)


def test_graph_normalizes_project_key_before_canonical_identity() -> None:
    graph = EngineeringGraph(project_key="  demo  ")
    component = _entity(graph, GraphEntityKind.COMPONENT, "U7")

    assert graph.project_key == "demo"
    assert component.entity_id == canonical_entity_id("demo", GraphEntityKind.COMPONENT, "U7")


def test_graph_diff_rejects_different_project_identities() -> None:
    before = EngineeringGraph(project_key="project-a")
    after = EngineeringGraph(project_key="project-b")

    with pytest.raises(ValueError, match="different projects"):
        engineering_graph_diff(before, after)


def test_transitive_dependency_cycle_does_not_report_self() -> None:
    graph = EngineeringGraph(project_key="demo")
    requirement = _entity(graph, GraphEntityKind.REQUIREMENT, "REQ-1")
    contract = _entity(graph, GraphEntityKind.INTENT_CONTRACT, "INTENT-1")
    graph.add_edge(GraphEdge(requirement.entity_id, contract.entity_id, GraphEdgeKind.DEPENDS_ON))
    graph.add_edge(GraphEdge(contract.entity_id, requirement.entity_id, GraphEdgeKind.DEPENDS_ON))

    dependencies = graph.dependencies_of(requirement.entity_id, transitive=True)

    assert contract.entity_id in dependencies
    assert requirement.entity_id not in dependencies


def test_graph_diff_preserves_identity_for_attribute_change() -> None:
    before = EngineeringGraph(project_key="demo")
    component = _entity(
        before,
        GraphEntityKind.COMPONENT,
        "U7",
        attributes={"value": "STM32G4"},
    )
    after = EngineeringGraph.from_document(before.to_document())
    after.entities[component.entity_id] = replace(
        component,
        attributes={"value": "STM32H5"},
    )

    changes = engineering_graph_diff(before, after)

    assert [change.kind for change in changes] == [GraphDiffKind.ENTITY_CHANGED]
    assert changes[0].subject_id == component.entity_id


def test_graph_diff_distinguishes_add_remove_from_identity_preserving_change() -> None:
    before = EngineeringGraph(project_key="demo")
    u7 = _entity(before, GraphEntityKind.COMPONENT, "U7")
    after = EngineeringGraph(project_key="demo")
    _entity(after, GraphEntityKind.COMPONENT, "U8")

    changes = engineering_graph_diff(before, after)
    kinds = {change.kind for change in changes}

    assert kinds == {GraphDiffKind.ENTITY_ADDED, GraphDiffKind.ENTITY_REMOVED}
    assert any(change.subject_id == u7.entity_id for change in changes)


def test_v1_draft_fixture_rewrites_legacy_ids_to_canonical_identity() -> None:
    fixture = Path(__file__).parents[1] / "fixtures" / "engineering_graph" / "v1-draft.json"
    draft = json.loads(fixture.read_text(encoding="utf-8"))
    assert draft["schema_version"] == DRAFT_ENGINEERING_GRAPH_SCHEMA_VERSION

    legacy_project_id = draft["nodes"][0]["id"]
    legacy_component_id = draft["nodes"][1]["id"]
    project_id = canonical_entity_id("demo", GraphEntityKind.PROJECT, "project")
    component_id = canonical_entity_id("demo", GraphEntityKind.COMPONENT, "U7")
    assert legacy_project_id != project_id
    assert legacy_component_id != component_id

    graph = EngineeringGraph.from_document(draft)
    document = graph.to_document()

    assert document["schema_version"] == ENGINEERING_GRAPH_SCHEMA_VERSION
    assert graph.entity(legacy_component_id) is None
    migrated_component = graph.entity(component_id)
    assert migrated_component is not None
    assert migrated_component.stable_key == "U7"
    assert GraphEdge(project_id, component_id, GraphEdgeKind.CONTAINS) in graph.edges


def test_document_round_trip_is_deterministic() -> None:
    graph = graph_from_circuit(_sample_circuit())

    document = graph.to_document()
    restored = EngineeringGraph.from_document(document)

    assert restored.to_document() == document


def test_power_rail_references_existing_net_and_ignores_unknown_net() -> None:
    circuit = _sample_circuit()
    circuit.power_rails["3V3"] = IRPowerRail(
        name="3V3",
        voltage=3.3,
        net_names=frozenset({"USB_DP", "MISSING_NET"}),
        source_ref="U7",
        source_pin="1",
    )

    graph = graph_from_circuit(circuit)

    rail = graph.entities_of_kind(GraphEntityKind.POWER_RAIL)[0]
    net = graph.entities_of_kind(GraphEntityKind.NET)[0]
    assert rail.attributes["voltage"] == 3.3
    assert rail.attributes["source_ref"] == "U7"
    rail_edge = GraphEdge(rail.entity_id, net.entity_id, GraphEdgeKind.REFERENCES, "rail_net")
    assert rail_edge in graph.edges


def test_anonymous_net_identity_prefers_connectivity_then_falls_back_to_name() -> None:
    circuit = _sample_circuit()
    circuit.nets["~N1"] = IRNet("~N1", connections=frozenset({("U7", "1")}))
    circuit.nets["~N2"] = IRNet("~N2")

    graph = graph_from_circuit(circuit)
    stable_keys = {entity.stable_key for entity in graph.entities_of_kind(GraphEntityKind.NET)}

    assert "connections:U7.1" in stable_keys
    assert "anonymous:~N2" in stable_keys


def test_architecture_checker_tracks_engineering_graph_modules() -> None:
    from scripts import check_architecture_boundaries as boundaries

    for module_name in (
        "kicad_mcp.ir.engineering_graph",
        "kicad_mcp.ir.engineering_graph_from_ir",
    ):
        assert module_name in boundaries.DOMAIN_MODULES
        assert module_name in boundaries.PURE_HELPERS


def test_engineering_graph_modules_stay_outside_runtime_and_tool_layers() -> None:
    from scripts import check_architecture_boundaries as boundaries

    for module_name in (
        "kicad_mcp.ir.engineering_graph",
        "kicad_mcp.ir.engineering_graph_from_ir",
    ):
        path = boundaries.DOMAIN_MODULES[module_name]
        imports = boundaries._imports_for(module_name, path)
        assert not any(
            imported.startswith(boundaries.FORBIDDEN_PURE_IMPORT_PREFIXES) for imported in imports
        )
