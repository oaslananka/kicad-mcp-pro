"""Experimental #944 persistent Engineering Graph state with fail-closed file checks.

A sidecar snapshot is an optimization hint, NEVER native KiCad authority.
Only attribute-only IRCircuit changes supported by #940 may be applied
incrementally. Unknown filesystem state and other edits require a clean rebuild.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, BinaryIO, cast

from kicad_mcp.ir.circuit_ir import IRCircuit
from kicad_mcp.ir.engineering_graph import (
    ENGINEERING_GRAPH_SCHEMA_VERSION,
    EngineeringGraph,
    GraphEntityKind,
    canonical_entity_id,
)
from kicad_mcp.ir.engineering_graph_from_ir import (
    graph_from_circuit,
    update_graph_from_circuit,
)
from kicad_mcp.project.evidence_current_state import canonical_graph_entity_sha256

STATE_SCHEMA_VERSION = 1
MAX_CHANGE_JOURNAL = 32
# Caller-owned compatibility identity must include KiCad/parser/IR schema versions.
SUPPORTED_SOURCES = frozenset({".kicad_sch", ".kicad_pcb", ".kicad_pro", ".kicad_dru"})


class StateRebuildRequiredError(ValueError):
    """Discard the cache and reparse the authoritative KiCad project."""


def _source_name(name: str) -> Path:
    if not name or "\\" in name:
        raise StateRebuildRequiredError("invalid source path")
    relative = Path(name)
    if relative.is_absolute() or ".." in relative.parts or "." in relative.parts:
        raise StateRebuildRequiredError("source escapes project")
    if relative.suffix not in SUPPORTED_SOURCES:
        raise StateRebuildRequiredError("unsupported native KiCad source")
    return relative


def _require_no_native_child_sheets(stream: BinaryIO) -> None:
    """Reject root-level KiCad sheet nodes in the IRCircuit-only cache pilot.

    Scan the actual file descriptor used for hashing, rather than relying on
    caller-supplied hierarchy metadata. Strings and nested library data are
    not native sheet instances. Streaming bounds additional memory usage.
    """
    depth = 0
    quoted = False
    escaped = False
    child_name = bytearray()
    reading_child_name = False
    whitespace = (9, 10, 13, 32)
    for chunk in iter(lambda: stream.read(65536), b""):
        for byte in chunk:
            if quoted:
                if escaped:
                    escaped = False
                elif byte == 92:
                    escaped = True
                elif byte == 34:
                    quoted = False
                continue
            if reading_child_name:
                if byte in whitespace and not child_name:
                    continue
                if byte not in (*whitespace, 40, 41, 34):
                    child_name.append(byte)
                    if len(child_name) > 5:
                        reading_child_name = False
                    continue
                if child_name == b"sheet":
                    raise StateRebuildRequiredError(
                        "native hierarchical sheet present; root-only graph is incomplete"
                    )
                reading_child_name = False
            if byte == 34:
                quoted = True
            elif byte == 40:
                depth += 1
                if depth == 2:
                    reading_child_name = True
                    child_name.clear()
            elif byte == 41:
                depth -= 1
                if depth < 0:
                    raise StateRebuildRequiredError("invalid native schematic structure")
    if quoted or depth != 0:
        raise StateRebuildRequiredError("invalid native schematic structure")


def source_digests(root: Path, names: tuple[str, ...]) -> dict[str, str]:
    """Verify exact project-file bytes without following symlinked paths.

    A before/after fstat comparison detects common concurrent writes. The
    caller must still ensure exclusive native mutation/read-back ownership.
    """
    if root.is_symlink() or not root.is_dir() or len(set(names)) != len(names):
        raise StateRebuildRequiredError("uncertain project root or source list")
    real_root = root.resolve(strict=True)
    if not names:
        raise StateRebuildRequiredError("project must track at least one native source")
    # Detect newly added/renamed sheets and boards. A tracked-list-only check
    # could otherwise silently reuse a graph after a new hierarchy was added.
    discovered = {
        path.relative_to(real_root).as_posix()
        for path in real_root.rglob("*")
        if path.suffix in SUPPORTED_SOURCES
    }
    if discovered != set(names):
        raise StateRebuildRequiredError("native project source inventory changed")
    return {name: _digest_one_source(real_root, name) for name in sorted(names)}


_CHANGED_DURING_READ = "native source changed during read"


def _file_identity(info: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _verify_ambiguous_windows_identity(
    path: Path, digest: str, original_identity: tuple[int, int, int, int, int]
) -> None:
    """Re-authenticate contents when Windows fstat/path stat disagree."""
    if path.is_symlink() or not path.is_file():
        raise StateRebuildRequiredError(_CHANGED_DURING_READ)
    try:
        with path.open("rb") as stream:
            path_digest = hashlib.file_digest(stream, "sha256").hexdigest()
        verified = path.stat(follow_symlinks=False)
    except OSError as exc:
        raise StateRebuildRequiredError(_CHANGED_DURING_READ) from exc
    if path_digest != digest or original_identity != _file_identity(verified):
        raise StateRebuildRequiredError(_CHANGED_DURING_READ)


def _digest_one_source(real_root: Path, name: str) -> str:
    rel = _source_name(name)
    parent = real_root
    for part in rel.parts[:-1]:
        parent /= part
        if parent.is_symlink():
            raise StateRebuildRequiredError("symlinked source directory")
    path = real_root / rel
    if path.is_symlink() or not path.is_file():
        raise StateRebuildRequiredError("missing or symlinked native source")
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            before = os.fstat(fd)
            with os.fdopen(os.dup(fd), "rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
                if rel.suffix == ".kicad_sch":
                    stream.seek(0)
                    _require_no_native_child_sheets(stream)
            after = os.fstat(fd)
        finally:
            os.close(fd)
    except OSError as exc:
        raise StateRebuildRequiredError("cannot safely read native source") from exc
    try:
        path_stat = path.stat(follow_symlinks=False)
    except OSError as exc:
        raise StateRebuildRequiredError("native file disappeared during read") from exc
    before_identity = _file_identity(before)
    after_identity = _file_identity(after)
    if before_identity != after_identity:
        raise StateRebuildRequiredError(_CHANGED_DURING_READ)
    path_identity = _file_identity(path_stat)
    if path_identity != after_identity:
        # File descriptor and path inode/device values can be incomparable on
        # Windows. Verify original bytes and path identity independently.
        _verify_ambiguous_windows_identity(path, digest, path_identity)
    return digest


def _entity_hashes(graph: EngineeringGraph) -> dict[str, str]:
    return {
        entity_id: canonical_graph_entity_sha256(entity)
        for entity_id, entity in sorted(graph.entities.items())
    }


def _require_single_sheet_scope(native_sources: tuple[str, ...], sheet_hierarchy: object) -> None:
    """Do not persist an IR-only graph as verified whole-project hierarchy.

    The #940 IRCircuit adapter only covers the root schematic. #1141 must
    establish native instance UUID/net parity before multi-sheet persistence
    is safe, even when all native file hashes are available.
    """
    schematic_count = sum(name.endswith(".kicad_sch") for name in native_sources)
    if (
        schematic_count != 1
        or not isinstance(sheet_hierarchy, (list, tuple))
        or len(sheet_hierarchy) > 1
    ):
        raise StateRebuildRequiredError(
            "hierarchical native graph completeness is unverified; "
            "do not persist root-only IRCircuit state"
        )


@dataclass(frozen=True, slots=True)
class EditToken:
    project_key: str
    generation: int
    source_hashes: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class ChangeJournalEntry:
    generation: int
    changed_sources: tuple[str, ...]
    updated_entities: tuple[str, ...]
    invalidated_entities: tuple[str, ...]
    work_units: int

    def to_document(self) -> dict[str, Any]:
        return {
            "generation": self.generation,
            "changed_sources": list(self.changed_sources),
            "updated_entities": list(self.updated_entities),
            "invalidated_entities": list(self.invalidated_entities),
            "work_units": self.work_units,
        }


@dataclass(slots=True)
class PersistentProjectState:
    root: Path
    graph: EngineeringGraph
    source_hashes: dict[str, str]
    entity_hashes: dict[str, str]
    compatibility_key: str
    generation: int = 0
    journal: tuple[ChangeJournalEntry, ...] = ()
    derived_dependencies: dict[str, dict[str, str]] = field(default_factory=dict)

    @classmethod
    def rebuild(
        cls,
        root: Path,
        native_sources: tuple[str, ...],
        circuit: IRCircuit,
        *,
        compatibility_key: str,
    ) -> PersistentProjectState:
        """Create a baseline only after a full native parse and version probe."""
        if not compatibility_key.strip():
            raise StateRebuildRequiredError("missing KiCad/parser compatibility identity")
        _require_single_sheet_scope(native_sources, circuit.sheet_hierarchy)
        graph = graph_from_circuit(circuit)
        return cls(
            root,
            graph,
            source_digests(root, native_sources),
            _entity_hashes(graph),
            compatibility_key,
        )

    @property
    def project_key(self) -> str:
        return self.graph.project_key

    def verify_sources(self) -> None:
        actual = source_digests(self.root, tuple(self.source_hashes))
        if actual != self.source_hashes:
            raise StateRebuildRequiredError("unrecognized native file edit; full rebuild required")

    def prepare_native_edit(self) -> EditToken:
        self.verify_sources()
        return EditToken(
            self.project_key, self.generation, tuple(sorted(self.source_hashes.items()))
        )

    def apply_native_edit(
        self,
        token: EditToken,
        before: IRCircuit,
        after: IRCircuit,
        *,
        expected_new_hashes: Mapping[str, str],
    ) -> ChangeJournalEntry:
        """Record a verified-on-disk native edit using #940 bounded graph semantics.

        The caller owns native KiCad mutation and must derive 'after' from an
        authoritative read-back. Unsupported edits force a clean rebuild.
        """
        if (
            token.project_key != self.project_key
            or token.generation != self.generation
            or dict(token.source_hashes) != self.source_hashes
        ):
            raise StateRebuildRequiredError("stale edit token or switched project")
        actual = source_digests(self.root, tuple(self.source_hashes))
        if dict(expected_new_hashes) != actual:
            raise StateRebuildRequiredError("native read-back hash mismatch")
        changed_sources = tuple(
            sorted(name for name, digest in actual.items() if digest != self.source_hashes[name])
        )
        if not changed_sources:
            raise StateRebuildRequiredError("native edit produced no changed project source")
        try:
            result = update_graph_from_circuit(self.graph, before, after)
        except ValueError as exc:
            raise StateRebuildRequiredError(str(exc)) from exc
        if not result.updated_entity_ids:
            raise StateRebuildRequiredError("source changed without bounded graph update")
        invalidated = result.updated_entity_ids | self.graph.impacted_by(result.updated_entity_ids)
        # Rehash ONLY modified graph entities. Unmodified node digests persist.
        for entity_id in result.updated_entity_ids:
            self.entity_hashes[entity_id] = canonical_graph_entity_sha256(
                self.graph.entities[entity_id]
            )
        self.derived_dependencies = {
            key: hashes
            for key, hashes in self.derived_dependencies.items()
            if not invalidated.intersection(hashes)
        }
        self.source_hashes = actual
        self.generation += 1
        entry = ChangeJournalEntry(
            self.generation,
            changed_sources,
            tuple(sorted(result.updated_entity_ids)),
            tuple(sorted(invalidated)),
            result.work_units,
        )
        self.journal = (*self.journal, entry)[-MAX_CHANGE_JOURNAL:]
        return entry

    def stamp_derived(self, key: str, entity_ids: tuple[str, ...]) -> None:
        """Mark analysis dependencies, NOT cached analysis output, as fresh."""
        self.verify_sources()
        if not key or not entity_ids or len(set(entity_ids)) != len(entity_ids):
            raise StateRebuildRequiredError("analysis needs an exact dependency manifest")
        if not set(entity_ids) <= self.entity_hashes.keys():
            raise StateRebuildRequiredError("unknown analysis dependency")
        self.derived_dependencies[key] = {
            entity_id: self.entity_hashes[entity_id] for entity_id in sorted(entity_ids)
        }

    def derived_is_current(self, key: str) -> bool:
        """No stale analysis is returned, even after external native changes."""
        try:
            self.verify_sources()
        except StateRebuildRequiredError:
            return False
        dependencies = self.derived_dependencies.get(key)
        if not dependencies:
            return False
        return all(
            self.entity_hashes.get(entity_id) == digest
            for entity_id, digest in dependencies.items()
        )

    def to_document(self) -> dict[str, Any]:
        return {
            "schema_version": STATE_SCHEMA_VERSION,
            "graph_schema_version": ENGINEERING_GRAPH_SCHEMA_VERSION,
            "project_key": self.project_key,
            "root_identity": _root_identity(self.root),
            "compatibility_key": self.compatibility_key,
            "source_hashes": dict(sorted(self.source_hashes.items())),
            "entity_hashes": dict(sorted(self.entity_hashes.items())),
            "generation": self.generation,
            "journal": [entry.to_document() for entry in self.journal],
            "derived_dependencies": self.derived_dependencies,
            "graph": self.graph.to_document(),
        }

    def save_atomic(self, state_path: Path) -> None:
        """Persist an opt-in sidecar using atomic replace, never a KiCad file."""
        path = _state_path(self.root, state_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Recheck after mkdir: a symlinked directory must not redirect writes.
        path = _state_path(self.root, state_path)
        self.verify_sources()
        encoded = (
            json.dumps(self.to_document(), sort_keys=True, separators=(",", ":")) + "\n"
        ).encode()
        import tempfile

        temporary: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb", dir=path.parent, prefix=".incremental-", delete=False
            ) as stream:
                temporary = stream.name
                os.fchmod(stream.fileno(), 0o600)
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            if path.is_symlink():
                raise StateRebuildRequiredError("symlinked state target")
            os.replace(temporary, path)
        finally:
            if temporary is not None and os.path.exists(temporary):
                os.unlink(temporary)

    @classmethod
    def load_verified(
        cls,
        root: Path,
        state_path: Path,
        *,
        project_key: str,
        native_sources: tuple[str, ...],
        compatibility_key: str,
    ) -> PersistentProjectState:
        """Return state only when schema, graph, sources and hashes all agree."""
        path = _state_path(root, state_path)
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(document, dict):
                raise ValueError("not an object")
            if (
                document.get("schema_version") != STATE_SCHEMA_VERSION
                or document.get("graph_schema_version") != ENGINEERING_GRAPH_SCHEMA_VERSION
                or document.get("project_key") != project_key
                or document.get("compatibility_key") != compatibility_key
                or document.get("root_identity") != _root_identity(root)
                or not compatibility_key.strip()
            ):
                raise ValueError("incompatible project or state schema")
            graph_document = document["graph"]
            if (
                not isinstance(graph_document, dict)
                or graph_document.get("schema_version") != ENGINEERING_GRAPH_SCHEMA_VERSION
            ):
                raise ValueError("incompatible cached Engineering Graph schema")
            graph = EngineeringGraph.from_document(graph_document)
            if graph.project_key != project_key:
                raise ValueError("Engineering Graph project identity mismatch")
            project_entity = graph.entities.get(
                canonical_entity_id(project_key, GraphEntityKind.PROJECT, "project")
            )
            if project_entity is None:
                raise ValueError("missing Engineering Graph project entity")
            _require_single_sheet_scope(
                native_sources, project_entity.attributes.get("sheet_hierarchy")
            )
            stored_sources = document["source_hashes"]
            stored_entities = document["entity_hashes"]
            generation = document["generation"]
            journal = document["journal"]
            derived = document["derived_dependencies"]
            if (
                not isinstance(stored_sources, dict)
                or not isinstance(stored_entities, dict)
                or not isinstance(generation, int)
                or isinstance(generation, bool)
                or generation < 0
                or not isinstance(journal, list)
                or len(journal) > MAX_CHANGE_JOURNAL
                or not isinstance(derived, dict)
            ):
                raise ValueError("invalid state metadata")
            if set(stored_sources) != set(native_sources):
                raise ValueError("tracked source list changed")
            if source_digests(root, native_sources) != stored_sources:
                raise ValueError("unrecognized native change")
            if _entity_hashes(graph) != stored_entities:
                raise ValueError("cached entity digest mismatch")
            records = _validate_stored_journal(journal, generation, stored_sources, stored_entities)
            _validate_derived_dependencies(derived, stored_entities)
            return cls(
                root,
                graph,
                stored_sources,
                stored_entities,
                compatibility_key,
                generation,
                records,
                derived,
            )
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise StateRebuildRequiredError("snapshot cannot be safely reused") from exc


def _validate_stored_journal(
    journal: list[object],
    generation: int,
    sources: Mapping[str, str],
    entities: Mapping[str, str],
) -> tuple[ChangeJournalEntry, ...]:
    records = tuple(_read_journal_entry(item) for item in journal)
    if len(records) != min(generation, MAX_CHANGE_JOURNAL):
        raise ValueError("journal must record every retained generation")
    if records and records[-1].generation != generation:
        raise ValueError("journal generation mismatch")
    if records and [item.generation for item in records] != list(
        range(generation - len(records) + 1, generation + 1)
    ):
        raise ValueError("non-contiguous journal generations")
    for record in records:
        if (
            not record.changed_sources
            or not set(record.changed_sources) <= sources.keys()
            or not record.updated_entities
            or not set(record.updated_entities) <= entities.keys()
            or not set(record.updated_entities) <= set(record.invalidated_entities)
            or record.work_units != len(record.updated_entities)
        ):
            raise ValueError("invalid journal change scope")
    return records


def _validate_derived_dependencies(
    derived: Mapping[str, object], entities: Mapping[str, str]
) -> None:
    for key, hashes in derived.items():
        if (
            not isinstance(key, str)
            or not isinstance(hashes, dict)
            or not hashes
            or any(entities.get(k) != v for k, v in hashes.items())
        ):
            raise ValueError("invalid analysis dependency stamp")


def _state_path(root: Path, state_path: Path) -> Path:
    """Constrain writable sidecars to a dedicated project-local directory."""
    if root.is_symlink() or not root.is_dir():
        raise StateRebuildRequiredError("invalid project directory")
    actual_root = root.resolve(strict=True)
    candidate = state_path if state_path.is_absolute() else actual_root / state_path
    try:
        relative = candidate.relative_to(actual_root)
    except ValueError as exc:
        raise StateRebuildRequiredError("cache path outside project") from exc
    if (
        len(relative.parts) != 2
        or relative.parts[0] != ".kicad-mcp-cache"
        or relative.suffix != ".json"
        or relative.name.startswith(".")
    ):
        raise StateRebuildRequiredError("state must be a dedicated JSON sidecar")
    parent = actual_root / ".kicad-mcp-cache"
    if parent.is_symlink() or candidate.is_symlink():
        raise StateRebuildRequiredError("symlinked cache path")
    return candidate


def _read_journal_entry(value: object) -> ChangeJournalEntry:
    if not isinstance(value, dict):
        raise ValueError("invalid journal entry")
    generation = value.get("generation")
    work_units = value.get("work_units")
    if any(
        not isinstance(x, int) or isinstance(x, bool) or x < 0 for x in (generation, work_units)
    ):
        raise ValueError("invalid journal generation or work units")
    fields: dict[str, tuple[str, ...]] = {}
    for key in ("changed_sources", "updated_entities", "invalidated_entities"):
        items = value.get(key)
        if (
            not isinstance(items, list)
            or any(not isinstance(x, str) or not x for x in items)
            or len(set(items)) != len(items)
            or items != sorted(items)
        ):
            raise ValueError("invalid journal entity IDs")
        fields[key] = tuple(items)
    return ChangeJournalEntry(
        cast(int, generation),
        fields["changed_sources"],
        fields["updated_entities"],
        fields["invalidated_entities"],
        cast(int, work_units),
    )


def _root_identity(root: Path) -> str:
    if root.is_symlink() or not root.is_dir():
        raise StateRebuildRequiredError("invalid project root")
    return hashlib.sha256(os.fsencode(root.resolve(strict=True))).hexdigest()
