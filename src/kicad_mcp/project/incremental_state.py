"""Experimental #944 persistent Engineering Graph state with fail-closed file checks.

A sidecar snapshot is an optimization hint, NEVER native KiCad authority.
Only supported IRCircuit attribute edits and saved PCB translations may update
incrementally. Unknown filesystem state and other edits require a clean rebuild.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, BinaryIO, cast

from kicad_mcp.ir.circuit_ir import IRCircuit
from kicad_mcp.ir.engineering_graph import (
    ENGINEERING_GRAPH_SCHEMA_VERSION,
    PHYSICAL_GRAPH_SCHEMA_VERSION,
    EngineeringGraph,
    GraphEntityKind,
    canonical_entity_id,
)
from kicad_mcp.ir.engineering_graph_from_ir import (
    graph_from_circuit,
    update_graph_from_circuit,
)
from kicad_mcp.ir.native_netlist import parse_native_netlist
from kicad_mcp.pcb.footprint_index import FileFootprintIndex, FootprintListRecord
from kicad_mcp.project.evidence_current_state import canonical_graph_entity_sha256
from kicad_mcp.project.native_hierarchy import inspect_sheet_instances
from kicad_mcp.project.physical_graph import add_physical_footprints, placement_delta

STATE_SCHEMA_VERSION = 1
SCHEMATIC_SOURCE_SUFFIX = ".kicad_sch"
MAX_CHANGE_JOURNAL = 32
# Caller-owned compatibility identity must include KiCad/parser/IR schema versions.
SUPPORTED_SOURCES = frozenset({SCHEMATIC_SOURCE_SUFFIX, ".kicad_pcb", ".kicad_pro", ".kicad_dru"})


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


def _handle_quoted_byte(byte: int, escaped: bool) -> tuple[bool, bool]:
    """Return updated (quoted, escaped) state inside an S-expression string literal."""
    if escaped:
        return True, False
    if byte == 92:
        return True, True
    if byte == 34:
        return False, False
    return True, False


def _step_child_name(
    byte: int,
    child_name: bytearray,
    whitespace: frozenset[int],
    delimiters: frozenset[int],
) -> tuple[bool, bool]:
    """Process a byte while reading a depth-2 child node name.

    Returns (continue_reading, is_sheet_node).
    """
    if byte in whitespace and not child_name:
        return True, False
    if byte not in delimiters:
        child_name.append(byte)
        if len(child_name) > 5:
            return False, False
        return True, False
    return False, child_name == b"sheet"


@dataclass
class _NativeSheetScanState:
    depth: int = 0
    quoted: bool = False
    escaped: bool = False
    child_name: bytearray = field(default_factory=bytearray)
    reading_child_name: bool = False


def _step_native_sheet_scan(
    state: _NativeSheetScanState,
    byte: int,
    whitespace: frozenset[int],
    delimiters: frozenset[int],
) -> None:
    if state.quoted:
        state.quoted, state.escaped = _handle_quoted_byte(byte, state.escaped)
        return
    if state.reading_child_name:
        state.reading_child_name, is_sheet = _step_child_name(
            byte, state.child_name, whitespace, delimiters
        )
        if is_sheet:
            raise StateRebuildRequiredError(
                "native hierarchical sheet present; root-only graph is incomplete"
            )
    if byte == 34:
        state.quoted = True
    elif byte == 40:
        state.depth += 1
        if state.depth == 2:
            state.reading_child_name = True
            state.child_name.clear()
    elif byte == 41:
        state.depth -= 1
        if state.depth < 0:
            raise StateRebuildRequiredError("invalid native schematic structure")


def _require_no_native_child_sheets(stream: BinaryIO) -> None:
    """Reject root-level KiCad sheet nodes in the IRCircuit-only cache pilot.

    Scan the actual file descriptor used for hashing, rather than relying on
    caller-supplied hierarchy metadata. Strings and nested library data are
    not native sheet instances. Streaming bounds additional memory usage.
    """
    state = _NativeSheetScanState()
    whitespace = frozenset((9, 10, 13, 32))
    delimiters = whitespace | {34, 40, 41}
    for chunk in iter(lambda: stream.read(65536), b""):
        for byte in chunk:
            _step_native_sheet_scan(state, byte, whitespace, delimiters)
    if state.quoted or state.depth != 0:
        raise StateRebuildRequiredError("invalid native schematic structure")


def source_digests(root: Path, names: tuple[str, ...]) -> dict[str, str]:
    """Hash the legacy single-sheet source inventory, rejecting hierarchy."""
    return _source_digests(root, names, allow_hierarchy=False)


def _source_digests(root: Path, names: tuple[str, ...], *, allow_hierarchy: bool) -> dict[str, str]:
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
    return {
        name: _digest_one_source(real_root, name, allow_hierarchy=allow_hierarchy)
        for name in sorted(names)
    }


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


def _digest_one_source(
    real_root: Path,
    name: str,
    *,
    allow_hierarchy: bool = False,
    copy_to: Path | None = None,
    read_digest: Callable[[BinaryIO], str] | None = None,
) -> str:
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
                digest = (
                    read_digest(stream)
                    if read_digest is not None
                    else hashlib.file_digest(stream, "sha256").hexdigest()
                )
                if copy_to is not None:
                    stream.seek(0)
                    with copy_to.open("xb") as target:
                        shutil.copyfileobj(stream, target)
                if rel.suffix == SCHEMATIC_SOURCE_SUFFIX and not allow_hierarchy:
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


@dataclass(frozen=True, slots=True)
class NativeHierarchySnapshot:
    """Source-bound native read-back; not a graph supplied by a cache file."""

    root: Path
    source_hashes: tuple[tuple[str, str], ...]
    circuit: IRCircuit


def capture_native_hierarchy(
    root: Path,
    root_name: str,
    native_sources: tuple[str, ...],
    *,
    run_cli: Callable[..., tuple[int, str, str]],
) -> NativeHierarchySnapshot:
    """Export a read-only hierarchy through the caller's trusted KiCad CLI seam.

    The caller owns a stable project snapshot and a bounded CLI runner. We
    stage only verified native sources, reject unknown hierarchy paths before
    invoking KiCad, and bind the result to exact original and copied hashes.
    """
    import tempfile

    before = _source_digests(root, native_sources, allow_hierarchy=True)
    with tempfile.TemporaryDirectory(prefix="kicad-native-graph-") as directory:
        staging = Path(directory) / "project"
        staging.mkdir()
        for name, digest in before.items():
            relative = _source_name(name)
            target = staging / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            copied_digest = _digest_one_source(
                root.resolve(strict=True), name, allow_hierarchy=True, copy_to=target
            )
            if (
                copied_digest != digest
                or _digest_one_source(staging, name, allow_hierarchy=True) != digest
            ):
                raise StateRebuildRequiredError("staged native source changed")
        root_uuid, expected_sheets, expected_stamps = inspect_sheet_instances(
            staging, root_name, native_sources
        )
        output = Path(directory) / "native.xml"
        code, _stdout, _stderr = run_cli(
            "sch",
            "export",
            "netlist",
            "--format",
            "kicadxml",
            "--output",
            str(output),
            str(staging / root_name),
        )
        if code != 0 or output.is_symlink() or not output.is_file():
            raise StateRebuildRequiredError("native netlist export failed")
        with output.open("rb") as stream:
            xml = stream.read(32 * 1024 * 1024 + 1)
        circuit = parse_native_netlist(
            xml,
            root_uuid=root_uuid,
            root_name=root_name,
            expected_sheets=expected_sheets,
            expected_stamps=expected_stamps,
        )
        if _source_digests(staging, native_sources, allow_hierarchy=True) != before:
            raise StateRebuildRequiredError("native export changed staged source")
    if _source_digests(root, native_sources, allow_hierarchy=True) != before:
        raise StateRebuildRequiredError("source changed during native export")
    return NativeHierarchySnapshot(root.resolve(strict=True), tuple(before.items()), circuit)


@dataclass(frozen=True, slots=True)
class NativePcbSnapshot:
    """Bounded saved-board placement read-back, bound to the native source inventory."""

    root: Path
    board_name: str
    source_hashes: tuple[tuple[str, str], ...]
    board_context_sha256: str
    records: tuple[FootprintListRecord, ...]
    decoded_footprints: int


def capture_native_pcb(
    root: Path,
    board_name: str,
    native_sources: tuple[str, ...],
    *,
    index: FileFootprintIndex | None = None,
) -> NativePcbSnapshot:
    """Read a supported saved PCB without writing any project or cache file."""
    reader = index if index is not None else FileFootprintIndex()
    try:
        return _capture_native_pcb(root, board_name, native_sources, reader)
    except (OSError, ValueError) as exc:
        reader.clear()
        raise StateRebuildRequiredError("native PCB snapshot unavailable") from exc


def _capture_native_pcb(
    root: Path, board_name: str, native_sources: tuple[str, ...], reader: FileFootprintIndex
) -> NativePcbSnapshot:
    relative = _source_name(board_name)
    if relative.suffix != ".kicad_pcb" or board_name not in native_sources:
        raise StateRebuildRequiredError("invalid native PCB identity")
    before = _source_digests(root, native_sources, allow_hierarchy=True)
    root = root.resolve(strict=True)
    raw = b""

    def capture(stream: BinaryIO) -> str:
        nonlocal raw
        raw = stream.read(128 * 1024 * 1024 + 1)
        if len(raw) > 128 * 1024 * 1024:
            raise ValueError("PCB bytes exceed supported size")
        return hashlib.sha256(raw).hexdigest()

    digest = _digest_one_source(root, board_name, allow_hierarchy=True, read_digest=capture)
    if digest != before[board_name]:
        raise ValueError("PCB bytes changed during read")
    result = reader.refresh(root / relative, raw.decode("utf-8"))
    if result is None:
        raise ValueError("unsupported native PCB inventory")
    if _source_digests(root, native_sources, allow_hierarchy=True) != before:
        raise ValueError("native source changed during PCB read-back")
    return NativePcbSnapshot(
        root,
        board_name,
        tuple(before.items()),
        result.board_context_sha256,
        tuple(result.records.values()),
        result.work_units,
    )


def _validate_pcb_snapshot(
    snapshot: NativePcbSnapshot, root: Path, hashes: Mapping[str, str]
) -> None:
    if (
        snapshot.root != root.resolve(strict=True)
        or dict(snapshot.source_hashes) != hashes
        or snapshot.board_name not in hashes
        or _source_name(snapshot.board_name).suffix != ".kicad_pcb"
    ):
        raise StateRebuildRequiredError("native PCB snapshot identity mismatch")


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
    schematic_count = sum(name.endswith(SCHEMATIC_SOURCE_SUFFIX) for name in native_sources)
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
    state_scope: object = field(repr=False)


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


def _validate_document_header(
    document: object, root: Path, project_key: str, compatibility_key: str
) -> None:
    if not isinstance(document, dict):
        raise ValueError("not an object")
    if (
        document.get("schema_version") != STATE_SCHEMA_VERSION
        or type(document.get("graph_schema_version")) is not int
        or document.get("graph_schema_version")
        not in (ENGINEERING_GRAPH_SCHEMA_VERSION, PHYSICAL_GRAPH_SCHEMA_VERSION)
        or document.get("project_key") != project_key
        or document.get("compatibility_key") != compatibility_key
        or document.get("root_identity") != _root_identity(root)
        or not compatibility_key.strip()
    ):
        raise ValueError("incompatible project or state schema")


def _load_verified_graph(
    graph_document: object,
    project_key: str,
    native_sources: tuple[str, ...],
    native_snapshot: NativeHierarchySnapshot | None = None,
    pcb_snapshot: NativePcbSnapshot | None = None,
) -> EngineeringGraph:
    if not isinstance(graph_document, dict) or graph_document.get("schema_version") != (
        PHYSICAL_GRAPH_SCHEMA_VERSION
        if pcb_snapshot is not None
        else ENGINEERING_GRAPH_SCHEMA_VERSION
    ):
        raise ValueError("incompatible cached Engineering Graph schema")
    if native_snapshot is not None:
        return _verify_native_graph(graph_document, project_key, native_snapshot, pcb_snapshot)
    graph = EngineeringGraph.from_document(graph_document)
    if graph.project_key != project_key:
        raise ValueError("Engineering Graph project identity mismatch")
    project_entity = graph.entities.get(
        canonical_entity_id(project_key, GraphEntityKind.PROJECT, "project")
    )
    if project_entity is None:
        raise ValueError("missing Engineering Graph project entity")
    _require_single_sheet_scope(native_sources, project_entity.attributes.get("sheet_hierarchy"))
    return graph


def _verify_native_graph(
    graph_document: dict[str, Any],
    project_key: str,
    native_snapshot: NativeHierarchySnapshot,
    pcb_snapshot: NativePcbSnapshot | None = None,
) -> EngineeringGraph:
    """Use native authority directly; the sidecar must match its canonical document."""
    graph = graph_from_circuit(native_snapshot.circuit)
    if pcb_snapshot is not None:
        add_physical_footprints(graph, pcb_snapshot.board_name, pcb_snapshot.records)
    if graph.project_key != project_key:
        raise ValueError("Engineering Graph project identity mismatch")
    # JSON comparison preserves types (e.g. false versus 0) and detects
    # duplicate or extra graph entries instead of normalizing them away.
    expected = json.dumps(
        graph.to_document(), sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    actual = json.dumps(graph_document, sort_keys=True, separators=(",", ":"), allow_nan=False)
    if actual != expected:
        raise ValueError("cached native graph differs from authoritative read-back")
    return graph


def _validate_state_metadata_and_hashes(
    document: dict[str, object],
    graph: EngineeringGraph,
    native_sources: tuple[str, ...],
) -> None:
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
    if _entity_hashes(graph) != stored_entities:
        raise ValueError("cached entity digest mismatch")


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
    native_root_name: str | None = None
    pcb_board_name: str | None = None
    pcb_context_sha256: str | None = None
    # Edit tokens authorize read-back only within this live state lifetime.
    _edit_scope: object = field(default_factory=object, init=False, repr=False, compare=False)

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
        if circuit.native_instances:
            raise StateRebuildRequiredError("native snapshot requires rebuild_native")
        graph = graph_from_circuit(circuit)
        return cls(
            root,
            graph,
            source_digests(root, native_sources),
            _entity_hashes(graph),
            compatibility_key,
        )

    @classmethod
    def rebuild_native(
        cls,
        snapshot: NativeHierarchySnapshot,
        *,
        compatibility_key: str,
        pcb_snapshot: NativePcbSnapshot | None = None,
    ) -> PersistentProjectState:
        """Build the opt-in native state without accepting an injected graph."""
        if not compatibility_key.strip() or snapshot.circuit.source_path is None:
            raise StateRebuildRequiredError("missing native compatibility or root identity")
        hashes = dict(snapshot.source_hashes)
        if _source_digests(snapshot.root, tuple(hashes), allow_hierarchy=True) != hashes:
            raise StateRebuildRequiredError("native snapshot is stale")
        graph = graph_from_circuit(snapshot.circuit)
        if pcb_snapshot is not None:
            _validate_pcb_snapshot(pcb_snapshot, snapshot.root, hashes)
            add_physical_footprints(graph, pcb_snapshot.board_name, pcb_snapshot.records)
        return cls(
            snapshot.root,
            graph,
            hashes,
            _entity_hashes(graph),
            compatibility_key,
            native_root_name=snapshot.circuit.source_path,
            pcb_board_name=pcb_snapshot.board_name if pcb_snapshot else None,
            pcb_context_sha256=pcb_snapshot.board_context_sha256 if pcb_snapshot else None,
        )

    @property
    def project_key(self) -> str:
        return self.graph.project_key

    def verify_sources(self) -> None:
        actual = _source_digests(
            self.root, tuple(self.source_hashes), allow_hierarchy=self.native_root_name is not None
        )
        if actual != self.source_hashes:
            raise StateRebuildRequiredError("unrecognized native file edit; full rebuild required")

    def prepare_native_edit(self) -> EditToken:
        self.verify_sources()
        return EditToken(
            self.project_key,
            self.generation,
            tuple(sorted(self.source_hashes.items())),
            self._edit_scope,
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
        if self.native_root_name is not None:
            raise StateRebuildRequiredError("use verified native hierarchy snapshots for edits")
        return self._apply_native_edit(
            token, before, after, expected_new_hashes=expected_new_hashes
        )

    def apply_hierarchy_edit(
        self, token: EditToken, before: NativeHierarchySnapshot, after: NativeHierarchySnapshot
    ) -> ChangeJournalEntry:
        """Record an attribute-only edit from a fresh native read-back."""
        if (
            self.native_root_name is None
            or before.root != self.root
            or after.root != self.root
            or before.circuit.source_path != self.native_root_name
            or after.circuit.source_path != self.native_root_name
            or dict(before.source_hashes) != self.source_hashes
        ):
            raise StateRebuildRequiredError("native snapshot identity mismatch")
        return self._apply_native_edit(
            token, before.circuit, after.circuit, expected_new_hashes=dict(after.source_hashes)
        )

    def _validate_edit_token(self, token: EditToken) -> None:
        if (
            token.state_scope is not self._edit_scope
            or token.project_key != self.project_key
            or token.generation != self.generation
            or dict(token.source_hashes) != self.source_hashes
        ):
            raise StateRebuildRequiredError("stale edit token or switched project")

    def apply_pcb_placement(
        self,
        token: EditToken,
        after: NativePcbSnapshot,
        *,
        native_uuid: str,
        x_mm: float,
        y_mm: float,
    ) -> ChangeJournalEntry:
        """Update one saved native footprint translation; all other edits rebuild."""
        self._validate_edit_token(token)
        actual = _source_digests(self.root, tuple(self.source_hashes), allow_hierarchy=True)
        _validate_pcb_snapshot(after, self.root, actual)
        changed_sources = tuple(
            sorted(name for name, digest in actual.items() if digest != self.source_hashes[name])
        )
        if (
            self.pcb_board_name is None
            or after.board_name != self.pcb_board_name
            or after.board_context_sha256 != self.pcb_context_sha256
            or changed_sources != (self.pcb_board_name,)
        ):
            raise StateRebuildRequiredError("unsupported PCB source change; rebuild required")
        try:
            entity = placement_delta(
                self.graph,
                after.board_name,
                after.records,
                native_uuid=native_uuid,
                x_mm=x_mm,
                y_mm=y_mm,
            )
        except ValueError as exc:
            raise StateRebuildRequiredError(str(exc)) from exc
        self.graph.entities[entity.entity_id] = entity
        # Connectivity/physical evidence is deliberately conservative until
        # native pad/net relationships are modeled. Never preserve unknown stamps.
        invalidated = {entity.entity_id} | {
            key for dependencies in self.derived_dependencies.values() for key in dependencies
        }
        return self._record_update(actual, changed_sources, {entity.entity_id}, invalidated)

    def _apply_native_edit(
        self,
        token: EditToken,
        before: IRCircuit,
        after: IRCircuit,
        *,
        expected_new_hashes: Mapping[str, str],
    ) -> ChangeJournalEntry:
        self._validate_edit_token(token)
        actual = _source_digests(
            self.root, tuple(self.source_hashes), allow_hierarchy=self.native_root_name is not None
        )
        if dict(expected_new_hashes) != actual:
            raise StateRebuildRequiredError("native read-back hash mismatch")
        changed_sources = tuple(
            sorted(name for name, digest in actual.items() if digest != self.source_hashes[name])
        )
        if self.pcb_board_name is not None and any(
            not name.endswith(SCHEMATIC_SOURCE_SUFFIX) for name in changed_sources
        ):
            raise StateRebuildRequiredError(
                "non-schematic source changed; use verified physical rebuild"
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
        if self.pcb_board_name is not None:
            invalidated |= {
                key for dependencies in self.derived_dependencies.values() for key in dependencies
            }
        return self._record_update(actual, changed_sources, result.updated_entity_ids, invalidated)

    def _record_update(
        self,
        actual: dict[str, str],
        changed_sources: tuple[str, ...],
        updated: set[str] | frozenset[str],
        invalidated: set[str] | frozenset[str],
    ) -> ChangeJournalEntry:
        # Rehash ONLY modified graph entities. Unmodified node digests persist.
        for entity_id in updated:
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
            tuple(sorted(updated)),
            tuple(sorted(invalidated)),
            len(updated),
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
            "graph_schema_version": self.graph.schema_version,
            "project_key": self.project_key,
            "root_identity": _root_identity(self.root),
            "compatibility_key": self.compatibility_key,
            "source_hashes": dict(sorted(self.source_hashes.items())),
            "entity_hashes": dict(sorted(self.entity_hashes.items())),
            "generation": self.generation,
            "journal": [entry.to_document() for entry in self.journal],
            "derived_dependencies": self.derived_dependencies,
            "graph": self.graph.to_document(),
            **({"native_root_name": self.native_root_name} if self.native_root_name else {}),
            **(
                {
                    "pcb_board_name": self.pcb_board_name,
                    "pcb_context_sha256": self.pcb_context_sha256,
                }
                if self.pcb_board_name
                else {}
            ),
        }

    def save_atomic(self, state_path: Path) -> None:
        """Persist an opt-in sidecar using atomic replace, never a KiCad file."""
        path = _state_path(self.root, state_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Recheck after mkdir: a symlinked directory must not redirect writes.
        path = _state_path(self.root, state_path)
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
            # An external change during serialization or staging must not
            # publish a stale snapshot. Keep the existing single hash pass.
            self.verify_sources()
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
        native_snapshot: NativeHierarchySnapshot | None = None,
        pcb_snapshot: NativePcbSnapshot | None = None,
    ) -> PersistentProjectState:
        """Return state only when schema, graph, sources and hashes all agree."""
        path = _state_path(root, state_path)
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
            _validate_document_header(document, root, project_key, compatibility_key)
            native_root = document.get("native_root_name")
            if native_snapshot is None:
                if native_root is not None:
                    raise ValueError("native state requires authoritative read-back")
            elif (
                native_root != native_snapshot.circuit.source_path
                or native_snapshot.root != root.resolve(strict=True)
                or dict(native_snapshot.source_hashes) != document["source_hashes"]
            ):
                raise ValueError("native snapshot identity mismatch")
            _validate_pcb_reopen(document, root, native_snapshot, pcb_snapshot)
            graph = _load_verified_graph(
                document["graph"], project_key, native_sources, native_snapshot, pcb_snapshot
            )
            _validate_state_metadata_and_hashes(document, graph, native_sources)

            stored_sources = document["source_hashes"]
            stored_entities = document["entity_hashes"]
            generation = document["generation"]
            journal = document["journal"]
            derived = document["derived_dependencies"]

            records = _validate_stored_journal(journal, generation, stored_sources, stored_entities)
            _validate_derived_dependencies(derived, stored_entities)
            # Validate native bytes after all potentially expensive cache checks.
            if (
                _source_digests(root, native_sources, allow_hierarchy=native_snapshot is not None)
                != stored_sources
            ):
                raise ValueError("unrecognized native change")
            return cls(
                root,
                graph,
                stored_sources,
                stored_entities,
                compatibility_key,
                generation,
                records,
                derived,
                native_root,
                pcb_snapshot.board_name if pcb_snapshot else None,
                pcb_snapshot.board_context_sha256 if pcb_snapshot else None,
            )
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise StateRebuildRequiredError("snapshot cannot be safely reused") from exc


def _validate_pcb_reopen(
    document: dict[str, Any],
    root: Path,
    native_snapshot: NativeHierarchySnapshot | None,
    pcb_snapshot: NativePcbSnapshot | None,
) -> None:
    if pcb_snapshot is None:
        if (
            document["graph_schema_version"] != ENGINEERING_GRAPH_SCHEMA_VERSION
            or "pcb_board_name" in document
            or "pcb_context_sha256" in document
        ):
            raise ValueError("physical state requires native PCB read-back")
        return
    if (
        native_snapshot is None
        or document["graph_schema_version"] != PHYSICAL_GRAPH_SCHEMA_VERSION
        or document.get("pcb_board_name") != pcb_snapshot.board_name
        or document.get("pcb_context_sha256") != pcb_snapshot.board_context_sha256
    ):
        raise ValueError("physical state identity mismatch")
    _validate_pcb_snapshot(pcb_snapshot, root, document["source_hashes"])


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
