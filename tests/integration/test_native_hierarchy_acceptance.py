"""Real KiCad native read-back and bounded graph-state acceptance (#1141)."""

from __future__ import annotations

import json
import os
import shutil
import statistics
import subprocess  # nosec B404
import sys
import time
from collections.abc import Callable
from pathlib import Path

import pytest
from defusedxml import ElementTree as SafeET

from kicad_mcp.config import get_config
from kicad_mcp.ir.engineering_graph import EngineeringGraph, GraphEdgeKind, GraphEntityKind
from kicad_mcp.pcb.footprint_index import FileFootprintIndex
from kicad_mcp.project.incremental_state import (
    EditToken,
    NativeHierarchySnapshot,
    PersistentProjectState,
    StateRebuildRequiredError,
    capture_native_hierarchy,
    capture_native_pcb,
)
from kicad_mcp.schematic.sheet_pins import _block_end, _children, _uuid_value
from kicad_mcp.tools.export_support import _run_cli
from scripts.benchmark_kicad_large_demo import (
    DEFAULT_DEMO_ROOT,
    MANIFEST_PATH,
    SYSTEM_PYTHON,
    _trusted_system_python,
    nearest_rank_p95,
    sha256_file,
    validate_demo_files,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/fixtures/native_hierarchy"
R17_STAMP = "158cb263-f02b-49cd-a384-b1930fe4cc8d"
REPEATS = 3


@pytest.fixture
def native_version(monkeypatch: pytest.MonkeyPatch) -> str:
    executable = shutil.which("kicad-cli")
    if executable is None:
        pytest.skip("native KiCad CLI unavailable")
    monkeypatch.setattr(get_config(), "kicad_cli", Path(executable))
    code, stdout, _ = _run_cli("version", timeout=15)
    assert code == 0
    version = stdout.strip()
    if not version.startswith("10."):
        pytest.skip("acceptance uses KiCad 10")
    return version


def _capture(
    root: Path, root_name: str, sources: tuple[str, ...]
) -> tuple[NativeHierarchySnapshot, bytes, float]:
    outputs: list[bytes] = []

    def cli(*args: str) -> tuple[int, str, str]:
        result = _run_cli(*args, timeout=60)
        if result[0] == 0:
            outputs.append(Path(args[-2]).read_bytes())
        return result

    started = time.perf_counter()
    snapshot = capture_native_hierarchy(root, root_name, sources, run_cli=cli)
    assert len(outputs) == 1
    return snapshot, outputs[0], (time.perf_counter() - started) * 1000


def _assert_native_parity(xml: bytes, graph: EngineeringGraph) -> int:
    """Compare raw native export with persisted graph, not the adapter's IR."""
    native = SafeET.fromstring(xml, forbid_dtd=True)
    components = {
        item.stable_key: item for item in graph.entities_of_kind(GraphEntityKind.COMPONENT)
    }
    assert set(components) == {comp.get("ref") for comp in native.findall("components/comp")}
    for comp in native.findall("components/comp"):
        ref = comp.get("ref")
        assert ref is not None
        sheet = comp.find("sheetpath")
        assert sheet is not None
        relative = (sheet.get("tstamps") or "").rstrip("/")
        path = f"/{graph.project_key}{relative}"
        links = {
            link.key for link in components[ref].native_links if link.kind == "symbol_instance"
        }
        assert links == {f"{path}/{stamp}" for stamp in (comp.findtext("tstamps") or "").split()}
        assert components[ref].attributes["native_sheet_name"] == sheet.get("names")
    expected = {
        (net.get("name"), node.get("ref"), node.get("pin"))
        for net in native.findall("nets/net")
        for node in net.findall("node")
    }
    actual = {
        (
            graph.entities[edge.target_id].attributes["name"],
            *graph.entities[edge.source_id].stable_key.rsplit(":", 1),
        )
        for edge in graph.edges
        if edge.kind == GraphEdgeKind.CONNECTS_TO
    }
    assert len(graph.entities_of_kind(GraphEntityKind.NET)) == len(native.findall("nets/net"))
    assert actual == expected
    return len(actual)


def _change_block(path: Path, tag: str, stamp: str, edit: Callable[[str], str]) -> None:
    text = path.read_text(encoding="utf-8")
    start = text.index("(kicad_sch")
    end = _block_end(text, start)
    matches = []
    for kind, begin, finish in _children(text, start, end):
        if kind == tag and any(
            child_tag == "uuid" and _uuid_value(text, child_begin, child_end) == stamp
            for child_tag, child_begin, child_end in _children(text, begin, finish)
        ):
            matches.append((begin, finish))
    assert len(matches) == 1
    begin, finish = matches[0]
    path.write_text(text[:begin] + edit(text[begin:finish]) + text[finish:], encoding="utf-8")


def _replace_value(block: str, old: str, new: str) -> str:
    expected = f'(property "Value" "{old}"'
    assert block.count(expected) == 1
    return block.replace(expected, f'(property "Value" "{new}"', 1)


def _save_reopen(
    state: PersistentProjectState, snapshot: NativeHierarchySnapshot
) -> PersistentProjectState:
    path = state.root / ".kicad-mcp-cache" / "native.json"
    state.save_atomic(path)
    original = path.read_bytes()
    state.save_atomic(path)
    assert path.read_bytes() == original
    loaded = PersistentProjectState.load_verified(
        state.root,
        path,
        project_key=state.project_key,
        native_sources=tuple(state.source_hashes),
        compatibility_key=state.compatibility_key,
        native_snapshot=snapshot,
    )
    assert loaded.graph.to_document() == state.graph.to_document()
    return loaded


@pytest.mark.slow
def test_real_repeated_sheet_instances(tmp_path: Path, native_version: str) -> None:
    sources = ("main.kicad_sch", "child.kicad_sch")
    for name in sources:
        shutil.copyfile(FIXTURE / name, tmp_path / name)
    # Test the installed KiCad's current on-disk format, not only old fixtures.
    code, _, _ = _run_cli("sch", "upgrade", "--force", str(tmp_path / sources[0]), timeout=60)
    assert code == 0
    assert "(version 20260306)" in (tmp_path / sources[0]).read_text(encoding="utf-8")
    compat = f"{native_version}:native-xml-E:graph-v1"
    before, xml, _ = _capture(tmp_path, sources[0], sources)
    state = PersistentProjectState.rebuild_native(before, compatibility_key=compat)
    assert set(before.circuit.components) == {"R1", "R2"}
    assert _assert_native_parity(xml, state.graph) == 4
    assert before.circuit.nets["GND"].connections == frozenset({("R1", "2"), ("R2", "2")})
    assert before.circuit.nets["VCC"].connections == frozenset({("R1", "1"), ("R2", "1")})
    token = state.prepare_native_edit()
    _change_block(
        tmp_path / sources[1],
        "symbol",
        "10000000-0000-0000-0000-100000000004",
        lambda block: _replace_value(block, "10k", "12k"),
    )
    after, after_xml, _ = _capture(tmp_path, sources[0], sources)
    assert state.apply_hierarchy_edit(token, before, after).work_units == 2
    assert (
        state.graph.to_document()
        == PersistentProjectState.rebuild_native(
            after, compatibility_key=compat
        ).graph.to_document()
    )
    assert _assert_native_parity(after_xml, state.graph) == 4
    state = _save_reopen(state, after)
    token = state.prepare_native_edit()
    _change_block(
        tmp_path / sources[0], "sheet", "10000000-0000-0000-0000-100000000003", lambda _: ""
    )
    changed, changed_xml, _ = _capture(tmp_path, sources[0], sources)
    original = state.graph.to_document()
    with pytest.raises(StateRebuildRequiredError, match="rebuild"):
        state.apply_hierarchy_edit(token, after, changed)
    assert state.graph.to_document() == original
    rebuilt = PersistentProjectState.rebuild_native(changed, compatibility_key=compat)
    assert set(changed.circuit.components) == {"R1"}
    assert _assert_native_parity(changed_xml, rebuilt.graph) == 2
    _save_reopen(rebuilt, changed)


def _measure(
    baseline_states: list[PersistentProjectState],
    before: NativeHierarchySnapshot,
    after: NativeHierarchySnapshot,
    tokens: list[EditToken],
) -> tuple[list[float], list[float]]:
    clean_ms: list[float] = []
    incremental_ms: list[float] = []
    for state, token in zip(baseline_states, tokens, strict=True):
        start = time.perf_counter()
        clean = PersistentProjectState.rebuild_native(
            after, compatibility_key=state.compatibility_key
        )
        clean_ms.append((time.perf_counter() - start) * 1000)
        start = time.perf_counter()
        entry = state.apply_hierarchy_edit(token, before, after)
        incremental_ms.append((time.perf_counter() - start) * 1000)
        assert entry.work_units == 1
        assert state.graph.to_document() == clean.graph.to_document()
    return clean_ms, incremental_ms


def _summary(values: list[float]) -> dict[str, float | list[float]]:
    return {
        "samples": [round(value, 3) for value in values],
        "p50": round(statistics.median(values), 3),
        "p95_nearest_rank": round(nearest_rank_p95(values), 3),
    }


@pytest.mark.slow
@pytest.mark.skipif(
    os.environ.get("KICAD_MCP_NATIVE_HIERARCHY_DEMO") != "1" or sys.platform != "linux",
    reason="opt-in pinned Linux native demo acceptance",
)
def test_pinned_large_native_hierarchy(tmp_path: Path, native_version: str) -> None:
    import resource

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    originals = validate_demo_files(DEFAULT_DEMO_ROOT, manifest)
    sources = tuple(source.name for source in originals if source.name != "LICENSE")
    for source in originals:
        shutil.copyfile(source, tmp_path / source.name)
    root_name = manifest["pcb"].replace(".kicad_pcb", ".kicad_sch")
    compat = f"{native_version}:native-xml-E:graph-v1"
    before, before_xml, before_ms = _capture(tmp_path, root_name, sources)
    states = [
        PersistentProjectState.rebuild_native(before, compatibility_key=compat)
        for _ in range(REPEATS)
    ]
    tokens = [state.prepare_native_edit() for state in states]
    assert len(before.circuit.components) == 1123
    assert len(before.circuit.nets) == 1355
    assert len(before.circuit.sheet_hierarchy) == 15
    assert _assert_native_parity(before_xml, states[0].graph) == 4712
    assert len(states[0].graph.entities) == 7191
    assert len(states[0].graph.edges) == 11902
    _change_block(
        tmp_path / "power.kicad_sch",
        "symbol",
        R17_STAMP,
        lambda block: _replace_value(block, "R_2k2_0402", "R_1141_DIAGNOSTIC"),
    )
    after, after_xml, after_ms = _capture(tmp_path, root_name, sources)
    assert after.circuit.components["R17"].value == "R_1141_DIAGNOSTIC"
    with pytest.raises(StateRebuildRequiredError):
        states[0].verify_sources()
    clean, incremental = _measure(states, before, after, tokens)
    state = _save_reopen(states[0], after)
    assert _assert_native_parity(after_xml, state.graph) == 4712
    token = state.prepare_native_edit()
    _change_block(tmp_path / "power.kicad_sch", "symbol", R17_STAMP, lambda _: "")
    removed, removed_xml, removed_ms = _capture(tmp_path, root_name, sources)
    assert len(removed.circuit.components) == 1122
    original_graph = state.graph.to_document()
    with pytest.raises(StateRebuildRequiredError, match="rebuild"):
        state.apply_hierarchy_edit(token, after, removed)
    assert state.graph.to_document() == original_graph
    rebuilt = PersistentProjectState.rebuild_native(removed, compatibility_key=compat)
    assert _assert_native_parity(removed_xml, rebuilt.graph) == 4710
    _save_reopen(rebuilt, removed)
    assert all(sha256_file(path) == manifest["files"][path.name] for path in originals)
    print(
        "NATIVE_HIERARCHY_EVIDENCE:"
        + json.dumps(
            {
                "kicad_version": native_version,
                "input_manifest_sha256": sha256_file(MANIFEST_PATH),
                "pinned_files": len(originals),
                "tracked_native_files": len(sources),
                "components": 1123,
                "nets": 1355,
                "sheet_instances": 15,
                "pin_net_matches": 4712,
                "graph_entities": 7191,
                "graph_edges": 11902,
                "after_removal_components": 1122,
                "after_removal_pin_net_matches": 4710,
                "attribute_work_units": 1,
                "source_capture_ms": {
                    "before": round(before_ms, 3),
                    "after": round(after_ms, 3),
                    "structural": round(removed_ms, 3),
                },
                "state_clean_rebuild_ms": _summary(clean),
                "state_incremental_update_ms": _summary(incremental),
                "process_peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                "child_process_peak_rss_kib": resource.getrusage(
                    resource.RUSAGE_CHILDREN
                ).ru_maxrss,
                "repeats": REPEATS,
                "original_hashes_unchanged": True,
            },
            sort_keys=True,
        ),
        flush=True,
    )


_NATIVE_FOOTPRINT_WORKER = """
import json, sys, pcbnew
board = pcbnew.LoadBoard(sys.argv[1])
assert board is not None
rows = sorted(
    (str(item.m_Uuid.AsString()), item.GetReference(), item.GetValue(),
     int(item.GetPosition().x), int(item.GetPosition().y),
     board.GetLayerName(item.GetLayer()))
    for item in board.GetFootprints()
)
print("NATIVE_FOOTPRINT_ROWS:" + json.dumps(rows))
"""


def _native_footprint_rows(board: Path) -> list:
    executable = _trusted_system_python(Path(SYSTEM_PYTHON))
    result = subprocess.run(  # nosec B603
        [str(executable), "-c", _NATIVE_FOOTPRINT_WORKER, str(board)],
        cwd=board.parent,
        capture_output=True,
        text=True,
        check=True,
        timeout=45,
    )
    rows = [
        line.removeprefix("NATIVE_FOOTPRINT_ROWS:")
        for line in result.stdout.splitlines()
        if line.startswith("NATIVE_FOOTPRINT_ROWS:")
    ]
    assert len(rows) == 1
    return json.loads(rows[0])


def _assert_pcb_graph_parity(graph: EngineeringGraph, rows: list) -> None:
    actual = sorted(
        [
            entity.native_links[0].uuid,
            entity.attributes["reference"],
            entity.attributes["value"],
            round(entity.attributes["x_mm"] * 1_000_000),
            round(entity.attributes["y_mm"] * 1_000_000),
            entity.attributes["layer"],
        ]
        for entity in graph.entities_of_kind(GraphEntityKind.PCB_FOOTPRINT)
    )
    assert actual == rows


@pytest.mark.slow
@pytest.mark.skipif(
    os.environ.get("KICAD_MCP_NATIVE_PCB_DEMO") != "1" or sys.platform != "linux",
    reason="opt-in pinned Linux physical PCB state acceptance",
)
def test_pinned_large_native_pcb_placement(tmp_path: Path, native_version: str) -> None:
    """Controlled saved-file translation with independent native reload, not a GUI edit."""
    import resource

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    originals = validate_demo_files(DEFAULT_DEMO_ROOT, manifest)
    sources = tuple(source.name for source in originals if source.name != "LICENSE")
    for source in originals:
        shutil.copyfile(source, tmp_path / source.name)
    board_name = manifest["pcb"]
    board = tmp_path / board_name
    root_name = board_name.replace(".kicad_pcb", ".kicad_sch")
    compat = f"{native_version}:native-xml-E:physical-graph-v2"
    hierarchy, _, _ = _capture(tmp_path, root_name, sources)
    index = FileFootprintIndex()
    start = time.perf_counter()
    before = capture_native_pcb(tmp_path, board_name, sources, index=index)
    state = PersistentProjectState.rebuild_native(
        hierarchy, compatibility_key=compat, pcb_snapshot=before
    )
    cold_ms = (time.perf_counter() - start) * 1000
    rows = _native_footprint_rows(board)
    assert len(rows) == 1125
    _assert_pcb_graph_parity(state.graph, rows)
    assert before.decoded_footprints == 1125
    observations = []
    # The pinned file manifest makes this literal diagnostic replacement exact.
    # Alternate the same native UUID so each cycle changes exactly one root X/Y.
    stamp = "3c47f456-5689-4cef-9b95-3444d1fac1a7"
    previous_x = 182.0
    for x in (182.1, 182.2, 182.3):
        start = time.perf_counter()
        warm = capture_native_pcb(tmp_path, board_name, sources, index=index)
        warm_ms = (time.perf_counter() - start) * 1000
        assert warm.decoded_footprints == 0
        assert dict(warm.source_hashes) == state.source_hashes
        token = state.prepare_native_edit()
        old = f'(uuid "{stamp}")\n\t\t(at {previous_x:g} 57.5 -90)'
        new = old.replace(f"(at {previous_x:g} ", f"(at {x:g} ")
        text = board.read_bytes()
        assert text.count(old.encode()) == 1
        board.write_bytes(text.replace(old.encode(), new.encode(), 1))
        del text
        start = time.perf_counter()
        after = capture_native_pcb(tmp_path, board_name, sources, index=index)
        entry = state.apply_pcb_placement(token, after, native_uuid=stamp, x_mm=x, y_mm=57.5)
        incremental_ms = (time.perf_counter() - start) * 1000
        assert entry.work_units == after.decoded_footprints == 1
        updated_rows = _native_footprint_rows(board)
        _assert_pcb_graph_parity(state.graph, updated_rows)
        assert sum(a != b for a, b in zip(rows, updated_rows, strict=True)) == 1
        fresh_hierarchy, _, hierarchy_ms = _capture(tmp_path, root_name, sources)
        start = time.perf_counter()
        clean_pcb = capture_native_pcb(tmp_path, board_name, sources)
        clean = PersistentProjectState.rebuild_native(
            fresh_hierarchy, compatibility_key=compat, pcb_snapshot=clean_pcb
        )
        clean_ms = (time.perf_counter() - start) * 1000
        assert clean_pcb.decoded_footprints == 1125
        assert clean.graph.to_document() == state.graph.to_document()
        assert clean.entity_hashes == state.entity_hashes
        path = tmp_path / ".kicad-mcp-cache" / "physical.json"
        state.save_atomic(path)
        start = time.perf_counter()
        reopened = PersistentProjectState.load_verified(
            tmp_path,
            path,
            project_key=state.project_key,
            native_sources=sources,
            compatibility_key=compat,
            native_snapshot=fresh_hierarchy,
            pcb_snapshot=clean_pcb,
        )
        reopen_ms = (time.perf_counter() - start) * 1000
        assert reopened.to_document() == state.to_document()
        observations.append(
            {
                "warm_capture_ms": warm_ms,
                "incremental_capture_update_ms": incremental_ms,
                "clean_capture_build_ms": clean_ms,
                "reopen_ms_excluding_capture": reopen_ms,
                "fresh_hierarchy_capture_ms": hierarchy_ms,
            }
        )
        state = reopened
        rows = updated_rows
        previous_x = x
    assert all(sha256_file(path) == manifest["files"][path.name] for path in originals)
    revision = subprocess.run(  # nosec B603
        ["/usr/bin/git", "rev-parse", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    ).stdout.strip()
    print(
        "NATIVE_PCB_STATE_EVIDENCE:"
        + json.dumps(
            {
                "kicad_version": native_version,
                "input_manifest_sha256": sha256_file(MANIFEST_PATH),
                "footprints": len(rows),
                "repository_sha": revision,
                "pcb_sha256": manifest["files"][board_name],
                "original_source_count": len(originals),
                "updated_graph_entities_per_cycle": [1] * len(observations),
                "decoded_footprints_cold_warm_changed_clean": [1125, 0, 1, 1125],
                "cold_capture_build_ms": round(cold_ms, 3),
                "phase_metrics": {
                    key: _summary([item[key] for item in observations]) for key in observations[0]
                },
                "process_peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                "original_hashes_unchanged": True,
                "observation_count": len(observations),
            },
            sort_keys=True,
        ),
        flush=True,
    )
