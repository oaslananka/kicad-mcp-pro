"""Adapter from the existing semantic IRCircuit to Engineering Graph v1."""

from __future__ import annotations

from copy import deepcopy

from .circuit_ir import IRCircuit, IRNet, IRPin
from .engineering_graph import (
    EngineeringGraph,
    GraphEdge,
    GraphEdgeKind,
    GraphEntity,
    GraphEntityKind,
    GraphProvenance,
    GraphProvenanceKind,
    NativeLink,
    canonical_entity_id,
)


def graph_from_circuit(
    circuit: IRCircuit,
    *,
    project_key: str | None = None,
) -> EngineeringGraph:
    """Adapt an IRCircuit without replacing it as semantic circuit truth."""
    resolved_project_key = (project_key or circuit.source_uuid or "").strip()
    if not resolved_project_key:
        raise ValueError(
            "project_key is required when IRCircuit.source_uuid is unavailable; "
            "path/title fallbacks are intentionally not used for durable identity"
        )

    graph = EngineeringGraph(project_key=resolved_project_key)
    imported = _imported_provenance()
    project_id = _add_project_entity(graph, circuit, resolved_project_key, imported)
    component_ids, pin_ids = _add_components(
        graph,
        circuit,
        resolved_project_key,
        project_id,
        imported,
    )
    net_ids = _add_nets(
        graph,
        circuit,
        resolved_project_key,
        project_id,
        imported,
        pin_ids,
    )
    _add_power_rails(graph, circuit, resolved_project_key, project_id, imported, net_ids)
    _add_interfaces(
        graph,
        circuit,
        resolved_project_key,
        project_id,
        imported,
        net_ids,
        component_ids,
    )
    _add_constraints(graph, circuit, resolved_project_key, project_id, imported, net_ids)
    return graph


def _imported_provenance() -> GraphProvenance:
    return GraphProvenance(
        GraphProvenanceKind.IMPORTED,
        source="IRCircuit",
        detail="adapted from semantic circuit IR",
    )


def _project_native_links(circuit: IRCircuit) -> tuple[NativeLink, ...]:
    if not (circuit.source_path or circuit.source_uuid):
        return ()
    return (
        NativeLink(
            system="kicad",
            kind="schematic",
            key=circuit.source_path or circuit.title,
            uuid=circuit.source_uuid,
        ),
    )


def _add_project_entity(
    graph: EngineeringGraph,
    circuit: IRCircuit,
    project_key: str,
    imported: GraphProvenance,
) -> str:
    project_id = canonical_entity_id(project_key, GraphEntityKind.PROJECT, "project")
    graph.add_entity(
        GraphEntity(
            entity_id=project_id,
            kind=GraphEntityKind.PROJECT,
            stable_key="project",
            attributes={
                "title": circuit.title,
                "source_path": circuit.source_path,
                "source_uuid": circuit.source_uuid,
                "sheet_hierarchy": list(circuit.sheet_hierarchy),
            },
            provenance=imported,
            native_links=_project_native_links(circuit),
        )
    )
    return project_id


def _add_components(
    graph: EngineeringGraph,
    circuit: IRCircuit,
    project_key: str,
    project_id: str,
    imported: GraphProvenance,
) -> tuple[dict[str, str], dict[tuple[str, str], str]]:
    component_ids: dict[str, str] = {}
    pin_ids: dict[tuple[str, str], str] = {}
    for reference, component in sorted(circuit.components.items()):
        component_id = canonical_entity_id(project_key, GraphEntityKind.COMPONENT, reference)
        component_ids[reference] = component_id
        graph.add_entity(
            GraphEntity(
                component_id,
                GraphEntityKind.COMPONENT,
                reference,
                {
                    "lib_id": component.lib_id,
                    "value": component.value,
                    "footprint": component.footprint,
                    "dnp": component.dnp,
                    "in_bom": component.in_bom,
                },
                imported,
                (NativeLink("kicad", "symbol_reference", reference),),
            )
        )
        graph.add_edge(GraphEdge(project_id, component_id, GraphEdgeKind.CONTAINS))
        _add_component_pins(
            graph,
            project_key,
            component_id,
            reference,
            component.pins,
            imported,
            pin_ids,
        )
    return component_ids, pin_ids


def _add_component_pins(
    graph: EngineeringGraph,
    project_key: str,
    component_id: str,
    reference: str,
    pins: tuple[IRPin, ...],
    imported: GraphProvenance,
    pin_ids: dict[tuple[str, str], str],
) -> None:
    for pin in pins:
        pin_key = f"{reference}:{pin.number}"
        pin_id = canonical_entity_id(project_key, GraphEntityKind.PIN, pin_key)
        pin_ids[(reference, pin.number)] = pin_id
        graph.add_entity(
            GraphEntity(
                pin_id,
                GraphEntityKind.PIN,
                pin_key,
                {
                    "number": pin.number,
                    "name": pin.name,
                    "electrical_type": pin.electrical_type.value,
                    "role": pin.role.value,
                },
                imported,
                (NativeLink("kicad", "symbol_pin", pin_key),),
            )
        )
        graph.add_edge(GraphEdge(component_id, pin_id, GraphEdgeKind.CONTAINS))


def _add_nets(
    graph: EngineeringGraph,
    circuit: IRCircuit,
    project_key: str,
    project_id: str,
    imported: GraphProvenance,
    pin_ids: dict[tuple[str, str], str],
) -> dict[str, str]:
    net_ids: dict[str, str] = {}
    for name, net in sorted(circuit.nets.items()):
        net_key = _net_stable_key(net)
        net_id = canonical_entity_id(project_key, GraphEntityKind.NET, net_key)
        net_ids[name] = net_id
        graph.add_entity(
            GraphEntity(
                net_id,
                GraphEntityKind.NET,
                net_key,
                {
                    "name": net.name,
                    "is_power": net.is_power,
                    "voltage": net.voltage,
                    "net_class": net.net_class,
                    "connections": [list(connection) for connection in sorted(net.connections)],
                },
                imported,
                (NativeLink("kicad", "net", name),),
            )
        )
        graph.add_edge(GraphEdge(project_id, net_id, GraphEdgeKind.CONTAINS))
        _connect_net_pins(graph, net_id, net.connections, pin_ids)
    return net_ids


def _connect_net_pins(
    graph: EngineeringGraph,
    net_id: str,
    connections: frozenset[tuple[str, str]],
    pin_ids: dict[tuple[str, str], str],
) -> None:
    for connection in sorted(connections):
        connected_pin_id = pin_ids.get(connection)
        if connected_pin_id is not None:
            graph.add_edge(GraphEdge(connected_pin_id, net_id, GraphEdgeKind.CONNECTS_TO))


def _add_power_rails(
    graph: EngineeringGraph,
    circuit: IRCircuit,
    project_key: str,
    project_id: str,
    imported: GraphProvenance,
    net_ids: dict[str, str],
) -> None:
    for name, rail in sorted(circuit.power_rails.items()):
        rail_id = canonical_entity_id(project_key, GraphEntityKind.POWER_RAIL, name)
        graph.add_entity(
            GraphEntity(
                rail_id,
                GraphEntityKind.POWER_RAIL,
                name,
                {
                    "voltage": rail.voltage,
                    "net_names": sorted(rail.net_names),
                    "source_ref": rail.source_ref,
                    "source_pin": rail.source_pin,
                },
                imported,
            )
        )
        graph.add_edge(GraphEdge(project_id, rail_id, GraphEdgeKind.CONTAINS))
        _add_reference_edges(graph, rail_id, rail.net_names, net_ids, "rail_net")


def _add_interfaces(
    graph: EngineeringGraph,
    circuit: IRCircuit,
    project_key: str,
    project_id: str,
    imported: GraphProvenance,
    net_ids: dict[str, str],
    component_ids: dict[str, str],
) -> None:
    for name, interface in sorted(circuit.interfaces.items()):
        interface_id = canonical_entity_id(project_key, GraphEntityKind.INTERFACE, name)
        graph.add_entity(
            GraphEntity(
                interface_id,
                GraphEntityKind.INTERFACE,
                name,
                {
                    "kind": interface.kind,
                    "net_roles": dict(sorted(interface.net_roles.items())),
                    "refs": list(interface.refs),
                },
                imported,
            )
        )
        graph.add_edge(GraphEdge(project_id, interface_id, GraphEdgeKind.CONTAINS))
        _add_interface_net_edges(graph, interface_id, interface.net_roles, net_ids)
        _add_interface_component_edges(graph, interface_id, interface.refs, component_ids)


def _add_interface_net_edges(
    graph: EngineeringGraph,
    interface_id: str,
    net_roles: dict[str, str],
    net_ids: dict[str, str],
) -> None:
    for role, net_name in sorted(net_roles.items()):
        role_net_id = net_ids.get(net_name)
        if role_net_id is not None:
            graph.add_edge(
                GraphEdge(
                    interface_id,
                    role_net_id,
                    GraphEdgeKind.REFERENCES,
                    f"net_role:{role}",
                )
            )


def _add_interface_component_edges(
    graph: EngineeringGraph,
    interface_id: str,
    references: tuple[str, ...],
    component_ids: dict[str, str],
) -> None:
    for reference in sorted(references):
        participant_component_id = component_ids.get(reference)
        if participant_component_id is not None:
            graph.add_edge(
                GraphEdge(
                    interface_id,
                    participant_component_id,
                    GraphEdgeKind.REFERENCES,
                    "participant",
                )
            )


def _add_constraints(
    graph: EngineeringGraph,
    circuit: IRCircuit,
    project_key: str,
    project_id: str,
    imported: GraphProvenance,
    net_ids: dict[str, str],
) -> None:
    for key, constraint in sorted(circuit.constraints.items()):
        constraint_id = canonical_entity_id(project_key, GraphEntityKind.CONSTRAINT, key)
        graph.add_entity(
            GraphEntity(
                constraint_id,
                GraphEntityKind.CONSTRAINT,
                key,
                {
                    "kind": constraint.kind,
                    "net_names": sorted(constraint.net_names),
                    "params": deepcopy(constraint.params),
                },
                imported,
            )
        )
        graph.add_edge(GraphEdge(project_id, constraint_id, GraphEdgeKind.CONTAINS))
        for net_name in sorted(constraint.net_names):
            constraint_net_id = net_ids.get(net_name)
            if constraint_net_id is not None:
                graph.add_edge(
                    GraphEdge(
                        constraint_id,
                        constraint_net_id,
                        GraphEdgeKind.APPLIES_TO,
                        "constraint_target",
                    )
                )


def _add_reference_edges(
    graph: EngineeringGraph,
    source_id: str,
    names: frozenset[str],
    target_ids: dict[str, str],
    role: str,
) -> None:
    for name in sorted(names):
        target_id = target_ids.get(name)
        if target_id is not None:
            graph.add_edge(GraphEdge(source_id, target_id, GraphEdgeKind.REFERENCES, role))


def _net_stable_key(net: IRNet) -> str:
    """Use semantic connectivity for anonymous-net identity when possible."""
    if not net.name.startswith("~"):
        return net.name
    if net.connections:
        joined = "|".join(f"{reference}.{pin}" for reference, pin in sorted(net.connections))
        return f"connections:{joined}"
    return f"anonymous:{net.name}"
