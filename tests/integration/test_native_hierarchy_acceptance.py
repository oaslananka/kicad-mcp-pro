"""Real KiCad native read-back and bounded graph-state acceptance (#1141)."""

from __future__ import annotations

import json
import os
import shutil
import statistics
import sys
import time
from collections.abc import Callable
from pathlib import Path

import pytest
from defusedxml import ElementTree as SafeET

from kicad_mcp.config import get_config
from kicad_mcp.ir.engineering_graph import EngineeringGraph, GraphEdgeKind, GraphEntityKind
from kicad_mcp.project.incremental_state import (
    EditToken,
    NativeHierarchySnapshot,
    PersistentProjectState,
    StateRebuildRequiredError,
    capture_native_hierarchy,
)
from kicad_mcp.schematic.sheet_pins import _block_end, _children, _uuid_value
from kicad_mcp.tools.export_support import _run_cli
from scripts.benchmark_kicad_large_demo import (
    DEFAULT_DEMO_ROOT,
    MANIFEST_PATH,
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
    assert len(before.circuit.components) == 1123 and len(before.circuit.nets) == 1355
    assert len(before.circuit.sheet_hierarchy) == 15
    assert _assert_native_parity(before_xml, states[0].graph) == 4712
    assert len(states[0].graph.entities) == 7191 and len(states[0].graph.edges) == 11902
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
