"""#944 deterministic sidecar state with bounded, fail-closed graph updates."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from kicad_mcp.ir import IRCircuit, IRComponent, IRPin
from kicad_mcp.ir.engineering_graph import GraphEntityKind, canonical_entity_id
from kicad_mcp.ir.engineering_graph_from_ir import graph_from_circuit
from kicad_mcp.project.incremental_state import (
    MAX_CHANGE_JOURNAL,
    PersistentProjectState,
    StateRebuildRequiredError,
    source_digests,
)

PROJECT_KEY = "10000000-0000-0000-0000-100000000001"
SOURCES = ("main.kicad_sch", "main.kicad_pcb")
COMPATIBILITY_KEY = "kicad-10.0.6:parser-v1:engineering-graph-v1"


def _circuit() -> IRCircuit:
    circuit = IRCircuit(
        source_path="main.kicad_sch",
        source_uuid=PROJECT_KEY,
        title="bounded incremental fixture",
    )
    for ref in ("R1", "R2"):
        circuit.components[ref] = IRComponent(
            ref,
            "Device:R",
            "10k",
            "Resistor_SMD:R_0603_1608Metric",
            pins=(IRPin("1", "1"), IRPin("2", "2")),
        )
    return circuit


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / "main.kicad_sch").write_bytes(b"(kicad_sch (version 20250114))")
    (tmp_path / "main.kicad_pcb").write_bytes(b"(kicad_pcb (version 20241229))")
    return tmp_path


def _state(root: Path) -> PersistentProjectState:
    return PersistentProjectState.rebuild(
        root, SOURCES, _circuit(), compatibility_key=COMPATIBILITY_KEY
    )


def test_deterministic_persistent_reopen_and_project_switch(project: Path) -> None:
    state = _state(project)
    path = project / ".kicad-mcp-cache" / "graph.json"
    state.save_atomic(path)
    original = path.read_bytes()
    state.save_atomic(path)
    assert path.read_bytes() == original
    loaded = PersistentProjectState.load_verified(
        project,
        path,
        project_key=PROJECT_KEY,
        native_sources=SOURCES,
        compatibility_key=COMPATIBILITY_KEY,
    )
    assert loaded.graph.to_document() == state.graph.to_document()
    assert loaded.entity_hashes == state.entity_hashes
    assert loaded.generation == 0
    with pytest.raises(StateRebuildRequiredError):
        PersistentProjectState.load_verified(
            project,
            path,
            project_key="other-project",
            native_sources=SOURCES,
            compatibility_key=COMPATIBILITY_KEY,
        )


def test_bounded_edit_preserves_unrelated_entities_and_invalidates_derived(project: Path) -> None:
    state = _state(project)
    before = _circuit()
    token = state.prepare_native_edit()
    changed = canonical_entity_id(PROJECT_KEY, GraphEntityKind.COMPONENT, "R1")
    stable = canonical_entity_id(PROJECT_KEY, GraphEntityKind.COMPONENT, "R2")
    preserved = state.graph.entities[stable]
    preserved_digest = state.entity_hashes[stable]
    state.stamp_derived("r1-analysis", (changed,))
    state.stamp_derived("r2-analysis", (stable,))
    updated = _circuit()
    updated.components["R1"] = replace(updated.components["R1"], value="12k")
    (project / "main.kicad_sch").write_bytes(b"(kicad_sch (version 20250114) (R1 12k))")
    entry = state.apply_native_edit(
        token, before, updated, expected_new_hashes=source_digests(project, SOURCES)
    )
    assert entry.work_units == 1
    assert entry.updated_entities == (changed,)
    assert state.entity_hashes[stable] == preserved_digest
    assert state.graph.entities[stable] is preserved
    assert not state.derived_is_current("r1-analysis")
    assert state.derived_is_current("r2-analysis")
    assert state.graph.to_document() == graph_from_circuit(updated).to_document()
    assert state.generation == 1
    assert len(state.journal) == 1
    path = project / ".kicad-mcp-cache" / "graph.json"
    state.save_atomic(path)
    reopened = PersistentProjectState.load_verified(
        project,
        path,
        project_key=PROJECT_KEY,
        native_sources=SOURCES,
        compatibility_key=COMPATIBILITY_KEY,
    )
    assert reopened.graph.to_document() == state.graph.to_document()
    assert not reopened.derived_is_current("r1-analysis")
    assert reopened.derived_is_current("r2-analysis")


def test_unknown_external_edit_forces_rebuild(project: Path) -> None:
    state = _state(project)
    state.stamp_derived("any", (canonical_entity_id(PROJECT_KEY, GraphEntityKind.COMPONENT, "R2"),))
    state.save_atomic(project / ".kicad-mcp-cache" / "graph.json")
    (project / "main.kicad_pcb").write_bytes(b"(kicad_pcb (modified externally))")
    with pytest.raises(StateRebuildRequiredError, match="unrecognized"):
        state.prepare_native_edit()
    assert not state.derived_is_current("any")
    with pytest.raises(StateRebuildRequiredError):
        PersistentProjectState.load_verified(
            project,
            project / ".kicad-mcp-cache" / "graph.json",
            project_key=PROJECT_KEY,
            native_sources=SOURCES,
            compatibility_key=COMPATIBILITY_KEY,
        )


def test_mismatched_readback_cannot_mutate_graph(project: Path) -> None:
    state = _state(project)
    old_graph = state.graph.to_document()
    token = state.prepare_native_edit()
    edited = _circuit()
    edited.components["R1"] = replace(edited.components["R1"], value="12k")
    (project / "main.kicad_sch").write_text("new bytes")
    before = _circuit()
    with pytest.raises(StateRebuildRequiredError, match="read-back"):
        state.apply_native_edit(token, before, edited, expected_new_hashes={})
    assert state.graph.to_document() == old_graph
    assert state.generation == 0
    stale_token = replace(token, generation=1)
    expected_hashes = source_digests(project, SOURCES)
    with pytest.raises(StateRebuildRequiredError, match="stale"):
        state.apply_native_edit(
            stale_token,
            before,
            edited,
            expected_new_hashes=expected_hashes,
        )


def test_structural_edit_requires_clean_graph_rebuild(project: Path) -> None:
    state = _state(project)
    token = state.prepare_native_edit()
    changed = _circuit()
    changed.components.pop("R2")
    (project / "main.kicad_sch").write_text("removed R2")
    old = state.graph.to_document()
    before = _circuit()
    expected_hashes = source_digests(project, SOURCES)
    with pytest.raises(StateRebuildRequiredError, match="identity set changed"):
        state.apply_native_edit(
            token,
            before,
            changed,
            expected_new_hashes=expected_hashes,
        )
    assert state.graph.to_document() == old


def test_no_semantic_update_cannot_claim_native_refresh(project: Path) -> None:
    state = _state(project)
    token = state.prepare_native_edit()
    (project / "main.kicad_pcb").write_text("pcb-only edit")
    before = _circuit()
    after = _circuit()
    expected_hashes = source_digests(project, SOURCES)
    with pytest.raises(StateRebuildRequiredError, match="without bounded graph update"):
        state.apply_native_edit(
            token,
            before,
            after,
            expected_new_hashes=expected_hashes,
        )


@pytest.mark.parametrize("field", ["schema_version", "graph_schema_version", "project_key"])
def test_schema_or_identity_change_invalidates_snapshot(project: Path, field: str) -> None:
    state = _state(project)
    path = project / ".kicad-mcp-cache" / "graph.json"
    state.save_atomic(path)
    contents = json.loads(path.read_text())
    contents[field] = 999
    path.write_text(json.dumps(contents))
    with pytest.raises(StateRebuildRequiredError):
        PersistentProjectState.load_verified(
            project,
            path,
            project_key=PROJECT_KEY,
            native_sources=SOURCES,
            compatibility_key=COMPATIBILITY_KEY,
        )


def test_corrupted_graph_digests_do_not_survive_reopen(project: Path) -> None:
    state = _state(project)
    path = project / ".kicad-mcp-cache" / "graph.json"
    state.save_atomic(path)
    contents = json.loads(path.read_text())
    key = next(iter(contents["entity_hashes"]))
    contents["entity_hashes"][key] = "0" * 64
    path.write_text(json.dumps(contents))
    with pytest.raises(StateRebuildRequiredError, match="snapshot cannot"):
        PersistentProjectState.load_verified(
            project,
            path,
            project_key=PROJECT_KEY,
            native_sources=SOURCES,
            compatibility_key=COMPATIBILITY_KEY,
        )


def test_cache_and_source_symlinks_fail_closed(project: Path, tmp_path: Path) -> None:
    outsider = tmp_path.parent / f"outside-{tmp_path.name}.json"
    outsider.write_text("sentinel")
    path = project / ".kicad-mcp-cache" / "graph.json"
    path.parent.mkdir()
    path.symlink_to(outsider)
    state = _state(project)
    with pytest.raises(StateRebuildRequiredError, match="symlink"):
        state.save_atomic(path)
    assert outsider.read_text() == "sentinel"
    path.unlink()
    (project / "main.kicad_sch").unlink()
    (project / "main.kicad_sch").symlink_to(outsider)
    with pytest.raises(StateRebuildRequiredError):
        _state(project)
    outsider.unlink()


def test_tracked_path_scope_cannot_escape_project(project: Path) -> None:
    with pytest.raises(StateRebuildRequiredError):
        source_digests(project, ("../outside.kicad_sch",))
    state = _state(project)
    escaped = project.parent / "leaked.json"
    with pytest.raises(StateRebuildRequiredError):
        state.save_atomic(escaped)


def test_missing_cache_file_requires_clean_rebuild(project: Path) -> None:
    with pytest.raises(StateRebuildRequiredError):
        PersistentProjectState.load_verified(
            project,
            project / ".kicad-mcp-cache" / "not-created.json",
            project_key=PROJECT_KEY,
            native_sources=SOURCES,
            compatibility_key=COMPATIBILITY_KEY,
        )


def test_journal_is_bounded_after_repeated_native_edits(project: Path) -> None:
    state = _state(project)
    previous = _circuit()
    for generation in range(MAX_CHANGE_JOURNAL + 3):
        token = state.prepare_native_edit()
        current = _circuit()
        current.components["R1"] = replace(current.components["R1"], value=str(generation))
        # Before must reflect the last committed state, not a fabricated snapshot.
        if generation:
            previous.components["R1"] = replace(
                previous.components["R1"], value=str(generation - 1)
            )
        (project / "main.kicad_sch").write_text(f"native edit {generation}")
        state.apply_native_edit(
            token,
            previous,
            current,
            expected_new_hashes=source_digests(project, SOURCES),
        )
        previous = current
    assert state.generation == MAX_CHANGE_JOURNAL + 3
    assert len(state.journal) == MAX_CHANGE_JOURNAL
    assert state.journal[0].generation == 4
    path = project / ".kicad-mcp-cache" / "graph.json"
    state.save_atomic(path)
    reopened = PersistentProjectState.load_verified(
        project,
        path,
        project_key=PROJECT_KEY,
        native_sources=SOURCES,
        compatibility_key=COMPATIBILITY_KEY,
    )
    assert reopened.journal == state.journal


def test_new_hierarchical_sheet_invalidates_tracked_inventory(project: Path) -> None:
    state = _state(project)
    (project / "power.kicad_sch").write_text("(kicad_sch (power))")
    with pytest.raises(StateRebuildRequiredError, match="inventory changed"):
        state.prepare_native_edit()


def test_removed_or_relinked_source_invalidates_state(project: Path) -> None:
    state = _state(project)
    (project / "main.kicad_pcb").rename(project / "board.kicad_pcb")
    with pytest.raises(StateRebuildRequiredError, match="inventory changed"):
        state.prepare_native_edit()


@pytest.mark.parametrize("tamper", ["journal_gap", "journal_scope", "graph_schema"])
def test_invalid_persisted_metadata_never_reused(project: Path, tamper: str) -> None:
    state = _state(project)
    path = project / ".kicad-mcp-cache" / "graph.json"
    state.save_atomic(path)
    document = json.loads(path.read_text())
    if tamper == "journal_gap":
        document["journal"] = [
            {
                "generation": 10,
                "changed_sources": ["main.kicad_sch"],
                "updated_entities": ["test-id"],
                "invalidated_entities": ["test-id"],
                "work_units": 1,
            }
        ]
        document["generation"] = 10
    elif tamper == "journal_scope":
        document["journal"] = [
            {
                "generation": 1,
                "changed_sources": ["untracked.kicad_sch"],
                "updated_entities": ["test-id"],
                "invalidated_entities": ["test-id"],
                "work_units": 1,
            }
        ]
        document["generation"] = 1
    else:
        document["graph"]["schema_version"] = "1-draft"
    path.write_text(json.dumps(document))
    with pytest.raises(StateRebuildRequiredError):
        PersistentProjectState.load_verified(
            project,
            path,
            project_key=PROJECT_KEY,
            native_sources=SOURCES,
            compatibility_key=COMPATIBILITY_KEY,
        )


def test_rejected_untrusted_digest_cannot_poison_state(project: Path) -> None:
    state = _state(project)
    token = state.prepare_native_edit()
    edited = _circuit()
    edited.components["R1"] = replace(edited.components["R1"], value="4k7")
    (project / "main.kicad_sch").write_text("trusted native content")
    hashes = source_digests(project, SOURCES)
    hashes["main.kicad_sch"] = "f" * 64
    before = _circuit()
    with pytest.raises(StateRebuildRequiredError, match="read-back"):
        state.apply_native_edit(token, before, edited, expected_new_hashes=hashes)
    assert state.generation == 0


def test_large_synthetic_graph_bounded_update_and_full_rebuild_match(project: Path) -> None:
    """Graph-only 1,024-component fixture, NOT a KiCad-native benchmark board."""
    before = _circuit()
    before.sheet_hierarchy = ("top",)  # synthetic scale only; not native hierarchy evidence
    for number in range(3, 1025):
        ref = f"R{number}"
        before.components[ref] = IRComponent(ref, "Device:R", "10k", "Resistor_SMD:R_0603")
    state = PersistentProjectState.rebuild(
        project, SOURCES, before, compatibility_key=COMPATIBILITY_KEY
    )
    baseline_entities = len(state.graph.entities)
    unchanged = canonical_entity_id(PROJECT_KEY, GraphEntityKind.COMPONENT, "R1024")
    identity = state.graph.entities[unchanged]
    token = state.prepare_native_edit()
    after = _circuit()
    after.sheet_hierarchy = before.sheet_hierarchy
    after.components.update(before.components)
    after.components["R2"] = replace(after.components["R2"], value="22k")
    (project / "main.kicad_sch").write_text("native readback placeholder for IR-only unit test")
    entry = state.apply_native_edit(
        token, before, after, expected_new_hashes=source_digests(project, SOURCES)
    )
    assert len(state.graph.entities) == baseline_entities
    assert entry.work_units == 1
    assert state.graph.entities[unchanged] is identity
    assert state.graph.to_document() == graph_from_circuit(after).to_document()


def test_native_hierarchical_ir_cannot_be_persisted_as_complete_graph(project: Path) -> None:
    """Root-only semantic IR is not authoritative for a multi-sheet native design."""
    circuit = _circuit()
    circuit.sheet_hierarchy = ("main.kicad_sch", "power.kicad_sch")
    with pytest.raises(StateRebuildRequiredError, match="hierarch"):
        PersistentProjectState.rebuild(
            project, SOURCES, circuit, compatibility_key=COMPATIBILITY_KEY
        )


def test_multiple_native_schematics_need_proven_hierarchy_parity(project: Path) -> None:
    (project / "power.kicad_sch").write_text("(kicad_sch (power))")
    sources = (*SOURCES, "power.kicad_sch")
    with pytest.raises(StateRebuildRequiredError, match="hierarch"):
        PersistentProjectState.rebuild(
            project, sources, _circuit(), compatibility_key=COMPATIBILITY_KEY
        )


def test_prior_hierarchical_sidecar_cannot_be_reused(project: Path) -> None:
    """Existing snapshots must not sidestep tightened scope on load."""
    from kicad_mcp.project.evidence_current_state import canonical_graph_entity_sha256

    state = _state(project)
    project_entity = state.graph.entities_of_kind(GraphEntityKind.PROJECT)[0]
    project_entity.attributes["sheet_hierarchy"] = [
        "main.kicad_sch",
        "power.kicad_sch",
    ]
    state.entity_hashes[project_entity.entity_id] = canonical_graph_entity_sha256(project_entity)
    path = project / ".kicad-mcp-cache" / "graph.json"
    state.save_atomic(path)
    with pytest.raises(StateRebuildRequiredError, match="snapshot cannot"):
        PersistentProjectState.load_verified(
            project,
            path,
            project_key=PROJECT_KEY,
            native_sources=SOURCES,
            compatibility_key=COMPATIBILITY_KEY,
        )


def test_kicad_parser_version_change_forces_rebuild(project: Path) -> None:
    state = _state(project)
    path = project / ".kicad-mcp-cache" / "graph.json"
    state.save_atomic(path)
    with pytest.raises(StateRebuildRequiredError):
        PersistentProjectState.load_verified(
            project,
            path,
            project_key=PROJECT_KEY,
            native_sources=SOURCES,
            compatibility_key="kicad-11.0.0:parser-v2:engineering-graph-v1",
        )


def test_relocated_project_does_not_inherit_prior_analysis_state(
    project: Path, tmp_path: Path
) -> None:
    import shutil

    state = _state(project)
    path = project / ".kicad-mcp-cache" / "graph.json"
    state.save_atomic(path)
    relocated = tmp_path / "different-project-root"
    shutil.copytree(project, relocated)
    with pytest.raises(StateRebuildRequiredError):
        PersistentProjectState.load_verified(
            relocated,
            relocated / ".kicad-mcp-cache" / "graph.json",
            project_key=PROJECT_KEY,
            native_sources=SOURCES,
            compatibility_key=COMPATIBILITY_KEY,
        )


@pytest.mark.parametrize(
    "invalid_name",
    ["", "../other.kicad_sch", "folder\\escape.kicad_sch", "data.txt", "/outside/other.kicad_sch"],
)
def test_invalid_native_source_names_are_rejected(project: Path, invalid_name: str) -> None:
    with pytest.raises(StateRebuildRequiredError):
        source_digests(project, (invalid_name,))


def test_untrusted_inventory_duplicates_and_empty_names_rejected(project: Path) -> None:
    with pytest.raises(StateRebuildRequiredError, match="source list"):
        source_digests(project, (SOURCES[0], SOURCES[0]))
    with pytest.raises(StateRebuildRequiredError, match="at least one"):
        source_digests(project, ())


def test_windows_style_fd_identity_mismatch_verifies_real_bytes(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Windows can report incomparable fd/path inode IDs for identical files.

    A second independent digest authenticates the bytes; a blind skip of the
    cross-API identity check would silently admit concurrent replacements.
    """
    from types import SimpleNamespace

    from kicad_mcp.project import incremental_state as module

    original_fstat = module.os.fstat

    def incomparable_fd_identity(fd: int) -> SimpleNamespace:
        stat = original_fstat(fd)
        return SimpleNamespace(
            st_dev=stat.st_dev,
            st_ino=stat.st_ino + 100_000,
            st_size=stat.st_size,
            st_mtime_ns=stat.st_mtime_ns,
            st_ctime_ns=stat.st_ctime_ns,
        )

    with monkeypatch.context() as patch:
        patch.setattr(module.os, "fstat", incomparable_fd_identity)
        actual = source_digests(project, SOURCES)
    assert actual == source_digests(project, SOURCES)


def test_fd_identity_mismatch_rejects_changed_bytes_on_reopen(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace

    from kicad_mcp.project import incremental_state as module

    original_fstat = module.os.fstat
    original_digest = module.hashlib.file_digest
    target = project / "main.kicad_pcb"
    calls = 0

    def incomparable_fd_identity(fd: int) -> SimpleNamespace:
        stat = original_fstat(fd)
        return SimpleNamespace(
            st_dev=stat.st_dev,
            st_ino=stat.st_ino + 100_000,
            st_size=stat.st_size,
            st_mtime_ns=stat.st_mtime_ns,
            st_ctime_ns=stat.st_ctime_ns,
        )

    def changed_while_confirming(stream, algorithm):
        nonlocal calls
        calls += 1
        result = original_digest(stream, algorithm)
        if calls == 2:
            target.write_bytes(b"(kicad_pcb (externally changed in read))")
        return result

    with monkeypatch.context() as patch:
        patch.setattr(module.os, "fstat", incomparable_fd_identity)
        patch.setattr(module.hashlib, "file_digest", changed_while_confirming)
        with pytest.raises(StateRebuildRequiredError, match="changed during read"):
            module.source_digests(project, SOURCES)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("generation", -1),
        ("generation", True),
        ("generation", "2"),
        ("source_hashes", []),
        ("entity_hashes", None),
        ("journal", {}),
        ("derived_dependencies", None),
    ],
)
def test_invalid_persisted_metadata_types_rejected(
    project: Path, field: str, value: object
) -> None:
    state = _state(project)
    path = project / ".kicad-mcp-cache" / "graph.json"
    state.save_atomic(path)
    document = json.loads(path.read_text())
    document[field] = value
    path.write_text(json.dumps(document))
    with pytest.raises(StateRebuildRequiredError, match="snapshot cannot"):
        PersistentProjectState.load_verified(
            project,
            path,
            project_key=PROJECT_KEY,
            native_sources=SOURCES,
            compatibility_key=COMPATIBILITY_KEY,
        )


@pytest.mark.parametrize("bad_record", [None, {}, {"generation": True, "work_units": 1}])
def test_corrupt_journal_item_never_trusted(project: Path, bad_record: object) -> None:
    state = _state(project)
    path = project / ".kicad-mcp-cache" / "graph.json"
    state.save_atomic(path)
    document = json.loads(path.read_text())
    document["journal"] = [bad_record]
    document["generation"] = 1
    path.write_text(json.dumps(document))
    with pytest.raises(StateRebuildRequiredError):
        PersistentProjectState.load_verified(
            project,
            path,
            project_key=PROJECT_KEY,
            native_sources=SOURCES,
            compatibility_key=COMPATIBILITY_KEY,
        )


@pytest.mark.parametrize(
    "bad_dependencies",
    [
        {"": {"bad-id": "a" * 64}},
        {"analysis": {}},
        {"analysis": []},
        {"analysis": {"unknown-entity": "b" * 64}},
    ],
)
def test_untrusted_analysis_dependency_stamp_does_not_survive_restart(
    project: Path, bad_dependencies: object
) -> None:
    state = _state(project)
    path = project / ".kicad-mcp-cache" / "graph.json"
    state.save_atomic(path)
    document = json.loads(path.read_text())
    document["derived_dependencies"] = bad_dependencies
    path.write_text(json.dumps(document))
    with pytest.raises(StateRebuildRequiredError):
        PersistentProjectState.load_verified(
            project,
            path,
            project_key=PROJECT_KEY,
            native_sources=SOURCES,
            compatibility_key=COMPATIBILITY_KEY,
        )


@pytest.mark.parametrize(
    "dependencies",
    [
        (),
        ("unknown-entity",),
        ("same", "same"),
    ],
)
def test_derived_analysis_scope_must_be_explicit(
    project: Path, dependencies: tuple[str, ...]
) -> None:
    state = _state(project)
    with pytest.raises(StateRebuildRequiredError):
        state.stamp_derived("analysis", dependencies)


def test_sidecar_symlink_directory_and_wrong_suffix_rejected(project: Path, tmp_path: Path) -> None:
    state = _state(project)
    target = tmp_path / "different-cache"
    target.mkdir()
    cache = project / ".kicad-mcp-cache"
    cache.symlink_to(target, target_is_directory=True)
    with pytest.raises(StateRebuildRequiredError, match="symlinked"):
        state.save_atomic(cache / "graph.json")
    cache.unlink()
    with pytest.raises(StateRebuildRequiredError, match="dedicated JSON"):
        state.save_atomic(project / ".kicad-mcp-cache" / "graph.txt")


def test_missing_required_compatibility_identity_rejected(project: Path) -> None:
    graph = _circuit()
    with pytest.raises(StateRebuildRequiredError, match="compatibility identity"):
        PersistentProjectState.rebuild(project, SOURCES, graph, compatibility_key=" ")


def test_fd_identity_mismatch_rejects_identical_path_metadata_but_different_digest(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Byte checks cannot be replaced with size/mtime checks on Windows."""
    from types import SimpleNamespace

    from kicad_mcp.project import incremental_state as module

    original_fstat = module.os.fstat
    original_digest = module.hashlib.file_digest
    calls = 0

    def incompatible_inode(fd: int) -> SimpleNamespace:
        stat = original_fstat(fd)
        return SimpleNamespace(
            st_dev=stat.st_dev,
            st_ino=stat.st_ino + 100_000,
            st_size=stat.st_size,
            st_mtime_ns=stat.st_mtime_ns,
            st_ctime_ns=stat.st_ctime_ns,
        )

    def forged_second_read(stream, algorithm):
        nonlocal calls
        calls += 1
        if calls == 2:
            import hashlib

            return hashlib.sha256(b"altered native bytes")
        return original_digest(stream, algorithm)

    with monkeypatch.context() as patch:
        patch.setattr(module.os, "fstat", incompatible_inode)
        patch.setattr(module.hashlib, "file_digest", forged_second_read)
        with pytest.raises(StateRebuildRequiredError, match="changed during read"):
            source_digests(project, SOURCES)


def test_file_modified_while_descriptor_open_is_rejected(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace

    from kicad_mcp.project import incremental_state as module

    original_fstat = module.os.fstat
    calls = 0

    def changing_descriptor_metadata(fd: int) -> SimpleNamespace:
        nonlocal calls
        calls += 1
        stat = original_fstat(fd)
        return SimpleNamespace(
            st_dev=stat.st_dev,
            st_ino=stat.st_ino,
            st_size=stat.st_size + (1 if calls == 2 else 0),
            st_mtime_ns=stat.st_mtime_ns,
            st_ctime_ns=stat.st_ctime_ns,
        )

    with monkeypatch.context() as patch:
        patch.setattr(module.os, "fstat", changing_descriptor_metadata)
        with pytest.raises(StateRebuildRequiredError, match="changed during read"):
            source_digests(project, SOURCES)


def test_source_disappears_during_read_is_rejected(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kicad_mcp.project import incremental_state as module

    real_stat = module.Path.stat
    target = project / "main.kicad_pcb"
    inspections = 0

    def disappear_on_final_identity(path: Path, *args: object, **kwargs: object):
        nonlocal inspections
        if path == target and kwargs.get("follow_symlinks") is False:
            inspections += 1
            if inspections == 2:
                raise FileNotFoundError("simulated concurrent deletion")
        return real_stat(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(module.Path, "stat", disappear_on_final_identity)
        with pytest.raises(StateRebuildRequiredError, match="disappeared"):
            source_digests(project, SOURCES)
