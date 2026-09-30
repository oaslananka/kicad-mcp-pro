"""Adapter from the existing semantic IRCircuit to Engineering Graph v1."""

from __future__ import annotations

from copy import deepcopy

from .circuit_ir import IRCircuit, IRNet
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
    imported = GraphProvenance(
        GraphProvenanceKind.IMPORTED,
        source="IRCircuit",
        detail="adapted from semantic circuit IR",
    )
    project_id = canonical_entity_id(resolved_project_key, GraphEntityKind.PROJECT, "project")
    native_links: tuple[NativeLink, ...] = ()
    if circuit.source_path or circuit.source_uuid:
        native_links = (
            NativeLink(
                system="kicad",
                kind="schematic",
                key=circuit.source_path or circuit.title,
                uuid=circuit.source_uuid,
            ),
        )
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
            native_links=native_links,
        )
    )

    component_ids: dict[str, str] = {}
    pin_ids: dict[tuple[str, str], str] = {}
    for reference, component in sorted(circuit.components.items()):
        component_id = canonical_entity_id(
            resolved_project_key, GraphEntityKind.COMPONENT, reference
        )
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
        for pin in component.pins:
            pin_key = f"{reference}:{pin.number}"
            pin_id = canonical_entity_id(resolved_project_key, GraphEntityKind.PIN, pin_key)
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

    net_ids: dict[str, str] = {}
    for name, net in sorted(circuit.nets.items()):
        net_key = _net_stable_key(net)
        net_id = canonical_entity_id(resolved_project_key, GraphEntityKind.NET, net_key)
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
        for connection in sorted(net.connections):
            pin_id = pin_ids.get(connection)
            if pin_id is not None:
                graph.add_edge(GraphEdge(pin_id, net_id, GraphEdgeKind.CONNECTS_TO))

    for name, rail in sorted(circuit.power_rails.items()):
        rail_id = canonical_entity_id(resolved_project_key, GraphEntityKind.POWER_RAIL, name)
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
        for net_name in sorted(rail.net_names):
            net_id = net_ids.get(net_name)
            if net_id is not None:
                graph.add_edge(GraphEdge(rail_id, net_id, GraphEdgeKind.REFERENCES, "rail_net"))

    for name, interface in sorted(circuit.interfaces.items()):
        interface_id = canonical_entity_id(resolved_project_key, GraphEntityKind.INTERFACE, name)
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
        for role, net_name in sorted(interface.net_roles.items()):
            net_id = net_ids.get(net_name)
            if net_id is not None:
                graph.add_edge(
                    GraphEdge(
                        interface_id,
                        net_id,
                        GraphEdgeKind.REFERENCES,
                        f"net_role:{role}",
                    )
                )
        for reference in sorted(interface.refs):
            component_id = component_ids.get(reference)
            if component_id is not None:
                graph.add_edge(
                    GraphEdge(
                        interface_id,
                        component_id,
                        GraphEdgeKind.REFERENCES,
                        "participant",
                    )
                )

    for key, constraint in sorted(circuit.constraints.items()):
        constraint_id = canonical_entity_id(resolved_project_key, GraphEntityKind.CONSTRAINT, key)
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
            net_id = net_ids.get(net_name)
            if net_id is not None:
                graph.add_edge(
                    GraphEdge(
                        constraint_id,
                        net_id,
                        GraphEdgeKind.APPLIES_TO,
                        "constraint_target",
                    )
                )
    return graph


def _net_stable_key(net: IRNet) -> str:
    """Use semantic connectivity for anonymous-net identity when possible."""
    if not net.name.startswith("~"):
        return net.name
    if net.connections:
        joined = "|".join(f"{reference}.{pin}" for reference, pin in sorted(net.connections))
        return f"connections:{joined}"
    return f"anonymous:{net.name}"
