"""Versioned Engineering Graph v1 core.

The graph adds durable semantic identity, provenance, typed dependency edges,
impact queries, deterministic persistence, migration, and semantic diffing on
top of the existing EDA intermediate representation.

This module is intentionally independent of FastMCP and KiCad runtime adapters.
"""

from __future__ import annotations

import json
from collections import deque
from collections.abc import Iterable, Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
from uuid import NAMESPACE_URL, uuid5

ENGINEERING_GRAPH_SCHEMA_VERSION = 1
DRAFT_ENGINEERING_GRAPH_SCHEMA_VERSION = "1-draft"


class GraphEntityKind(StrEnum):
    """Entity kinds represented by Engineering Graph v1."""

    PROJECT = "project"
    COMPONENT = "component"
    PIN = "pin"
    NET = "net"
    POWER_RAIL = "power_rail"
    INTERFACE = "interface"
    CONSTRAINT = "constraint"
    REQUIREMENT = "requirement"
    INTENT_CONTRACT = "intent_contract"
    COMPONENT_CONTRACT = "component_contract"
    FIRMWARE_MAPPING = "firmware_mapping"
    VERIFICATION_RUN = "verification_run"
    EVIDENCE_ARTIFACT = "evidence_artifact"
    APPROVAL = "approval"
    WAIVER = "waiver"
    CHANGE = "change"


class GraphProvenanceKind(StrEnum):
    """Origin classification for graph facts."""

    IMPORTED = "imported"
    INFERRED = "inferred"
    USER_AUTHORED = "user_authored"
    USER_APPROVED = "user_approved"
    TOOL_GENERATED = "tool_generated"


class GraphEdgeKind(StrEnum):
    """Typed relationships between Engineering Graph entities."""

    CONTAINS = "contains"
    CONNECTS_TO = "connects_to"
    APPLIES_TO = "applies_to"
    DEPENDS_ON = "depends_on"
    DERIVED_FROM = "derived_from"
    VERIFIES = "verifies"
    PRODUCES = "produces"
    REFERENCES = "references"


_REVERSE_IMPACT_KINDS = frozenset(
    {
        GraphEdgeKind.APPLIES_TO,
        GraphEdgeKind.DEPENDS_ON,
        GraphEdgeKind.DERIVED_FROM,
        GraphEdgeKind.VERIFIES,
        GraphEdgeKind.REFERENCES,
    }
)
_FORWARD_IMPACT_KINDS = frozenset({GraphEdgeKind.CONTAINS, GraphEdgeKind.PRODUCES})
_SYMMETRIC_IMPACT_KINDS = frozenset({GraphEdgeKind.CONNECTS_TO})
_DEPENDENCY_QUERY_KINDS = frozenset(
    {
        GraphEdgeKind.APPLIES_TO,
        GraphEdgeKind.DEPENDS_ON,
        GraphEdgeKind.DERIVED_FROM,
        GraphEdgeKind.VERIFIES,
        GraphEdgeKind.REFERENCES,
    }
)


def _impact_neighbor(edge: GraphEdge, current_id: str) -> str | None:
    if edge.kind in _REVERSE_IMPACT_KINDS and edge.target_id == current_id:
        return edge.source_id
    if edge.kind in _FORWARD_IMPACT_KINDS and edge.source_id == current_id:
        return edge.target_id
    if edge.kind in _SYMMETRIC_IMPACT_KINDS:
        if edge.source_id == current_id:
            return edge.target_id
        if edge.target_id == current_id:
            return edge.source_id
    return None


def _impact_neighbors(edges: Iterable[GraphEdge], current_id: str) -> set[str]:
    neighbors: set[str] = set()
    for edge in edges:
        neighbor = _impact_neighbor(edge, current_id)
        if neighbor is not None:
            neighbors.add(neighbor)
    return neighbors


@dataclass(frozen=True, slots=True)
class GraphProvenance:
    """Provenance for an entity or persisted graph fact."""

    kind: GraphProvenanceKind
    source: str = ""
    detail: str = ""

    def to_dict(self) -> dict[str, str]:
        return {"kind": self.kind.value, "source": self.source, "detail": self.detail}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> GraphProvenance:
        kind = data.get("kind")
        source = data.get("source", "")
        detail = data.get("detail", "")
        if not isinstance(kind, str):
            raise ValueError("provenance.kind must be a string")
        if not isinstance(source, str) or not isinstance(detail, str):
            raise ValueError("provenance source/detail must be strings")
        return cls(GraphProvenanceKind(kind), source, detail)


@dataclass(frozen=True, slots=True)
class NativeLink:
    """Link to a native EDA/runtime object without using it as graph identity."""

    system: str
    kind: str
    key: str
    uuid: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return {"system": self.system, "kind": self.kind, "key": self.key, "uuid": self.uuid}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> NativeLink:
        system = data.get("system")
        kind = data.get("kind")
        key = data.get("key")
        uuid = data.get("uuid")
        if not isinstance(system, str) or not isinstance(kind, str) or not isinstance(key, str):
            raise ValueError("native link system/kind/key must be strings")
        if uuid is not None and not isinstance(uuid, str):
            raise ValueError("native link uuid must be a string or null")
        return cls(system=system, kind=kind, key=key, uuid=uuid)


@dataclass(frozen=True, slots=True)
class GraphEntity:
    """A durable semantic entity with canonical identity and provenance."""

    entity_id: str
    kind: GraphEntityKind
    stable_key: str
    attributes: dict[str, Any] = field(default_factory=dict)
    provenance: GraphProvenance = field(
        default_factory=lambda: GraphProvenance(GraphProvenanceKind.TOOL_GENERATED)
    )
    native_links: tuple[NativeLink, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "kind": self.kind.value,
            "stable_key": self.stable_key,
            "attributes": deepcopy(self.attributes),
            "provenance": self.provenance.to_dict(),
            "native_links": [link.to_dict() for link in self.native_links],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> GraphEntity:
        entity_id = data.get("entity_id")
        kind = data.get("kind")
        stable_key = data.get("stable_key")
        attributes = data.get("attributes", {})
        provenance = data.get("provenance", {"kind": GraphProvenanceKind.IMPORTED.value})
        native_links = data.get("native_links", [])
        if not isinstance(entity_id, str) or not isinstance(kind, str):
            raise ValueError("entity_id and kind must be strings")
        if not isinstance(stable_key, str):
            raise ValueError("stable_key must be a string")
        if not isinstance(attributes, dict):
            raise ValueError("entity attributes must be an object")
        if not isinstance(provenance, Mapping):
            raise ValueError("entity provenance must be an object")
        if not isinstance(native_links, list):
            raise ValueError("entity native_links must be a list")
        parsed_links: list[NativeLink] = []
        for item in native_links:
            if not isinstance(item, Mapping):
                raise ValueError("native link entries must be objects")
            parsed_links.append(NativeLink.from_dict(item))
        return cls(
            entity_id=entity_id,
            kind=GraphEntityKind(kind),
            stable_key=stable_key,
            attributes=deepcopy(attributes),
            provenance=GraphProvenance.from_dict(provenance),
            native_links=tuple(parsed_links),
        )


@dataclass(frozen=True, slots=True)
class GraphEdge:
    """A typed directed relationship between two graph entities."""

    source_id: str
    target_id: str
    kind: GraphEdgeKind
    role: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "source_id": self.source_id,
            "target_id": self.target_id,
            "kind": self.kind.value,
            "role": self.role,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> GraphEdge:
        source_id = data.get("source_id")
        target_id = data.get("target_id")
        kind = data.get("kind")
        role = data.get("role", "")
        if not isinstance(source_id, str) or not isinstance(target_id, str):
            raise ValueError("edge source_id and target_id must be strings")
        if not isinstance(kind, str) or not isinstance(role, str):
            raise ValueError("edge kind and role must be strings")
        return cls(source_id, target_id, GraphEdgeKind(kind), role)


@dataclass(slots=True)
class EngineeringGraph:
    """Mutable graph container with deterministic persistence and impact queries."""

    project_key: str
    schema_version: int = ENGINEERING_GRAPH_SCHEMA_VERSION
    entities: dict[str, GraphEntity] = field(default_factory=dict)
    edges: set[GraphEdge] = field(default_factory=set)

    def __post_init__(self) -> None:
        normalized_project_key = self.project_key.strip()
        if not normalized_project_key:
            raise ValueError("project_key must be a non-empty string")
        self.project_key = normalized_project_key
        if self.schema_version != ENGINEERING_GRAPH_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported Engineering Graph schema version: {self.schema_version!r}"
            )

    def add_entity(self, entity: GraphEntity) -> None:
        if not entity.stable_key or entity.stable_key != entity.stable_key.strip():
            raise ValueError("entity stable_key must be non-empty and normalized")
        expected_id = canonical_entity_id(self.project_key, entity.kind, entity.stable_key)
        if entity.entity_id != expected_id:
            raise ValueError(
                f"entity id {entity.entity_id!r} does not match canonical id {expected_id!r}"
            )
        existing = self.entities.get(entity.entity_id)
        if existing is not None and existing != entity:
            raise ValueError(f"conflicting entity for canonical id {entity.entity_id}")
        self.entities[entity.entity_id] = entity

    def add_edge(self, edge: GraphEdge) -> None:
        missing = {edge.source_id, edge.target_id} - self.entities.keys()
        if missing:
            raise ValueError("edge references unknown entity id(s): " + ", ".join(sorted(missing)))
        self.edges.add(edge)

    def entity(self, entity_id: str) -> GraphEntity | None:
        return self.entities.get(entity_id)

    def entities_of_kind(self, kind: GraphEntityKind) -> tuple[GraphEntity, ...]:
        return tuple(
            sorted(
                (entity for entity in self.entities.values() if entity.kind == kind),
                key=lambda entity: (entity.stable_key, entity.entity_id),
            )
        )

    def dependencies_of(self, entity_id: str, *, transitive: bool = False) -> set[str]:
        """Return entities this entity depends on through dependency-like edges."""
        if entity_id not in self.entities:
            raise KeyError(entity_id)
        dependencies: set[str] = set()
        queue: deque[str] = deque([entity_id])
        visited = {entity_id}
        while queue:
            current = queue.popleft()
            direct = {
                edge.target_id
                for edge in self.edges
                if edge.source_id == current and edge.kind in _DEPENDENCY_QUERY_KINDS
            }
            direct.discard(entity_id)
            dependencies.update(direct)
            if transitive:
                for dependency in sorted(direct):
                    if dependency not in visited:
                        visited.add(dependency)
                        queue.append(dependency)
        return dependencies

    def impacted_by(self, changed_ids: Iterable[str]) -> set[str]:
        """Return transitive semantic dependents of changed entities."""
        changed = set(changed_ids)
        missing = changed - self.entities.keys()
        if missing:
            raise KeyError("unknown changed entity id(s): " + ", ".join(sorted(missing)))

        impacted: set[str] = set()
        visited = set(changed)
        queue: deque[str] = deque(sorted(changed))
        while queue:
            current = queue.popleft()
            for neighbor in sorted(_impact_neighbors(self.edges, current)):
                if neighbor in visited:
                    continue
                visited.add(neighbor)
                impacted.add(neighbor)
                queue.append(neighbor)
        return impacted

    def to_document(self) -> dict[str, Any]:
        """Return a deterministic JSON-compatible document."""
        entities = [
            entity.to_dict()
            for entity in sorted(
                self.entities.values(),
                key=lambda entity: (entity.kind.value, entity.stable_key, entity.entity_id),
            )
        ]
        edges = [
            edge.to_dict()
            for edge in sorted(
                self.edges,
                key=lambda edge: (edge.kind.value, edge.source_id, edge.target_id, edge.role),
            )
        ]
        return {
            "schema_version": self.schema_version,
            "project_key": self.project_key,
            "entities": entities,
            "edges": edges,
        }

    @classmethod
    def from_document(cls, document: Mapping[str, Any]) -> EngineeringGraph:
        """Load schema v1 or a supported draft document."""
        migrated = migrate_graph_document(document)
        project_key = migrated.get("project_key")
        entities = migrated.get("entities")
        edges = migrated.get("edges")
        if not isinstance(project_key, str) or not project_key.strip():
            raise ValueError("project_key must be a non-empty string")
        if not isinstance(entities, list) or not isinstance(edges, list):
            raise ValueError("entities and edges must be lists")
        graph = cls(project_key=project_key)
        for item in entities:
            if not isinstance(item, Mapping):
                raise ValueError("entity entries must be objects")
            graph.add_entity(GraphEntity.from_dict(item))
        for item in edges:
            if not isinstance(item, Mapping):
                raise ValueError("edge entries must be objects")
            graph.add_edge(GraphEdge.from_dict(item))
        return graph


class GraphDiffKind(StrEnum):
    """Kinds of Engineering Graph semantic changes."""

    ENTITY_ADDED = "entity_added"
    ENTITY_REMOVED = "entity_removed"
    ENTITY_CHANGED = "entity_changed"
    EDGE_ADDED = "edge_added"
    EDGE_REMOVED = "edge_removed"


@dataclass(frozen=True, slots=True)
class GraphDiff:
    """A semantic graph difference that preserves canonical identity."""

    kind: GraphDiffKind
    subject_id: str
    before: GraphEntity | GraphEdge | None = None
    after: GraphEntity | GraphEdge | None = None


def canonical_entity_id(project_key: str, kind: GraphEntityKind, stable_key: str) -> str:
    """Return a deterministic ID independent of native KiCad object UUIDs."""
    normalized_project = project_key.strip()
    normalized_key = stable_key.strip()
    if not normalized_project or not normalized_key:
        raise ValueError("project_key and stable_key must be non-empty")
    identity_tuple = json.dumps(
        [normalized_project, kind.value, normalized_key],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    seed = f"https://github.com/oaslananka/kicad-mcp-pro/engineering-graph/v1/{identity_tuple}"
    return f"eg:{kind.value}:{uuid5(NAMESPACE_URL, seed)}"


def engineering_graph_diff(before: EngineeringGraph, after: EngineeringGraph) -> list[GraphDiff]:
    """Compare graph states by canonical identity and typed edges."""
    if before.project_key != after.project_key:
        raise ValueError("cannot diff Engineering Graph documents from different projects")
    changes: list[GraphDiff] = []
    before_ids = set(before.entities)
    after_ids = set(after.entities)

    for entity_id in sorted(after_ids - before_ids):
        changes.append(
            GraphDiff(GraphDiffKind.ENTITY_ADDED, entity_id, after=after.entities[entity_id])
        )
    for entity_id in sorted(before_ids - after_ids):
        changes.append(
            GraphDiff(GraphDiffKind.ENTITY_REMOVED, entity_id, before=before.entities[entity_id])
        )
    for entity_id in sorted(before_ids & after_ids):
        before_entity = before.entities[entity_id]
        after_entity = after.entities[entity_id]
        if before_entity != after_entity:
            changes.append(
                GraphDiff(
                    GraphDiffKind.ENTITY_CHANGED,
                    entity_id,
                    before=before_entity,
                    after=after_entity,
                )
            )

    def edge_key(edge: GraphEdge) -> tuple[str, str, str, str]:
        return (edge.kind.value, edge.source_id, edge.target_id, edge.role)

    for edge in sorted(after.edges - before.edges, key=edge_key):
        changes.append(
            GraphDiff(
                GraphDiffKind.EDGE_ADDED,
                f"{edge.source_id}->{edge.target_id}",
                after=edge,
            )
        )
    for edge in sorted(before.edges - after.edges, key=edge_key):
        changes.append(
            GraphDiff(
                GraphDiffKind.EDGE_REMOVED,
                f"{edge.source_id}->{edge.target_id}",
                before=edge,
            )
        )
    return changes


def _canonicalize_draft_entity_id(
    project_key: object,
    legacy_id: object,
    entity_kind: object,
    stable_key: object,
    legacy_id_map: dict[str, str],
) -> object:
    if not (
        isinstance(project_key, str)
        and isinstance(legacy_id, str)
        and isinstance(entity_kind, str)
        and isinstance(stable_key, str)
    ):
        return legacy_id
    canonical_id = canonical_entity_id(
        project_key,
        GraphEntityKind(entity_kind),
        stable_key,
    )
    legacy_id_map[legacy_id] = canonical_id
    return canonical_id


def _migrate_draft_provenance(provenance: object) -> object:
    if isinstance(provenance, str):
        return {"kind": provenance, "source": "v1-draft", "detail": ""}
    return deepcopy(provenance)


def _migrate_draft_entity(
    node: object,
    project_key: object,
    legacy_id_map: dict[str, str],
) -> dict[str, Any]:
    if not isinstance(node, Mapping):
        raise ValueError("draft node entries must be objects")
    legacy_id = node.get("id")
    entity_kind = node.get("type")
    stable_key = node.get("stable_key", node.get("key"))
    entity_id = _canonicalize_draft_entity_id(
        project_key,
        legacy_id,
        entity_kind,
        stable_key,
        legacy_id_map,
    )
    provenance = _migrate_draft_provenance(
        node.get("provenance", GraphProvenanceKind.IMPORTED.value)
    )
    return {
        "entity_id": entity_id,
        "kind": entity_kind,
        "stable_key": stable_key,
        "attributes": deepcopy(node.get("attributes", {})),
        "provenance": provenance,
        "native_links": deepcopy(node.get("native_links", [])),
    }


def _rewrite_draft_entity_id(value: object, legacy_id_map: Mapping[str, str]) -> object:
    if isinstance(value, str):
        return legacy_id_map.get(value, value)
    return value


def _migrate_draft_edge(
    link: object,
    legacy_id_map: Mapping[str, str],
) -> dict[str, Any]:
    if not isinstance(link, Mapping):
        raise ValueError("draft link entries must be objects")
    return {
        "source_id": _rewrite_draft_entity_id(link.get("from"), legacy_id_map),
        "target_id": _rewrite_draft_entity_id(link.get("to"), legacy_id_map),
        "kind": link.get("type"),
        "role": link.get("role", ""),
    }


def migrate_graph_document(document: Mapping[str, Any]) -> dict[str, Any]:
    """Migrate a supported persisted graph document to schema v1."""
    payload = deepcopy(dict(document))
    version = payload.get("schema_version")
    if version == ENGINEERING_GRAPH_SCHEMA_VERSION:
        return payload
    if version != DRAFT_ENGINEERING_GRAPH_SCHEMA_VERSION:
        raise ValueError(f"unsupported Engineering Graph schema version: {version!r}")

    nodes = payload.pop("nodes", [])
    links = payload.pop("links", [])
    if not isinstance(nodes, list) or not isinstance(links, list):
        raise ValueError("draft nodes and links must be lists")

    project_key = payload.get("project_key")
    legacy_id_map: dict[str, str] = {}
    payload["schema_version"] = ENGINEERING_GRAPH_SCHEMA_VERSION
    payload["entities"] = [
        _migrate_draft_entity(node, project_key, legacy_id_map) for node in nodes
    ]
    payload["edges"] = [_migrate_draft_edge(link, legacy_id_map) for link in links]
    return payload
