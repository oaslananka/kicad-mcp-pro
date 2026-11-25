"""Explicit PCB footprint graph projection, not a model of PCB connectivity."""

from __future__ import annotations

from ..ir.engineering_graph import (
    PHYSICAL_GRAPH_SCHEMA_VERSION,
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
from ..pcb.footprint_index import FootprintListRecord


def footprint_entity(project_key: str, board_name: str, row: FootprintListRecord) -> GraphEntity:
    kind = GraphEntityKind.PCB_FOOTPRINT
    key = f"{board_name}:{row.native_uuid}"
    return GraphEntity(
        canonical_entity_id(project_key, kind, key),
        kind,
        key,
        {
            "reference": row.reference,
            "value": row.value,
            "x_mm": row.x_mm,
            "y_mm": row.y_mm,
            "layer": row.layer_name,
            "block_sha256": row.block_sha256,
            "nonplacement_sha256": row.nonplacement_sha256,
        },
        GraphProvenance(GraphProvenanceKind.IMPORTED, "saved PCB", "footprint placement only"),
        (NativeLink("kicad", "pcb_footprint", key, row.native_uuid),),
    )


def add_physical_footprints(
    graph: EngineeringGraph, board_name: str, rows: tuple[FootprintListRecord, ...]
) -> None:
    """Extend the verified schematic graph without guessing component relationships."""
    project_id = canonical_entity_id(graph.project_key, GraphEntityKind.PROJECT, "project")
    graph.schema_version = PHYSICAL_GRAPH_SCHEMA_VERSION
    for row in rows:
        entity = footprint_entity(graph.project_key, board_name, row)
        graph.add_entity(entity)
        graph.add_edge(GraphEdge(project_id, entity.entity_id, GraphEdgeKind.CONTAINS))


def placement_delta(
    graph: EngineeringGraph,
    board_name: str,
    rows: tuple[FootprintListRecord, ...],
    *,
    native_uuid: str,
    x_mm: float,
    y_mm: float,
) -> GraphEntity:
    """Validate the complete footprint inventory, construct only the changed node."""
    existing = {
        item.stable_key: item for item in graph.entities_of_kind(GraphEntityKind.PCB_FOOTPRINT)
    }
    target = f"{board_name}:{native_uuid}"
    if len(rows) != len(existing) or target not in existing:
        raise ValueError("physical footprint inventory changed; rebuild required")
    changed = []
    seen = set()
    for row in rows:
        key = f"{board_name}:{row.native_uuid}"
        prior = existing.get(key)
        if prior is None or key in seen:
            raise ValueError("physical footprint identity changed; rebuild required")
        seen.add(key)
        if prior.attributes["block_sha256"] != row.block_sha256:
            changed.append(row)
    if len(changed) != 1 or changed[0].native_uuid != native_uuid:
        raise ValueError("not a single requested footprint placement; rebuild required")
    row = changed[0]
    prior = existing[target]
    if (
        prior.attributes["nonplacement_sha256"] != row.nonplacement_sha256
        or row.x_mm != x_mm
        or row.y_mm != y_mm
        or (row.x_mm, row.y_mm) == (prior.attributes["x_mm"], prior.attributes["y_mm"])
    ):
        raise ValueError("unverified or unsupported footprint edit; rebuild required")
    return footprint_entity(graph.project_key, board_name, row)
