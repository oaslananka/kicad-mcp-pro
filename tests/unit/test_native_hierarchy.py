"""Native export import must preserve instance identity and connectivity."""

from dataclasses import replace
from pathlib import Path

import pytest

from kicad_mcp.ir.circuit_ir import IRCircuit
from kicad_mcp.ir.engineering_graph import GraphEdgeKind, GraphEntityKind
from kicad_mcp.ir.engineering_graph_from_ir import graph_from_circuit, update_graph_from_circuit
from kicad_mcp.ir.native_netlist import parse_native_netlist
from kicad_mcp.project.evidence_current_state import canonical_graph_entity_sha256
from kicad_mcp.project.incremental_state import (
    NativeHierarchySnapshot,
    PersistentProjectState,
    StateRebuildRequiredError,
    capture_native_hierarchy,
)

ROOT = "10000000-0000-0000-0000-100000000001"
A = "10000000-0000-0000-0000-100000000002"
B = "10000000-0000-0000-0000-100000000003"
SYMBOL = "10000000-0000-0000-0000-100000000004"
XML = f"""<export version="E">
<design><sheet name="/" tstamps="/">
<title_block><source>main.kicad_sch</source></title_block></sheet>
<sheet name="/A/" tstamps="/{A}/">
<title_block><source>child.kicad_sch</source></title_block></sheet>
<sheet name="/B/" tstamps="/{B}/">
<title_block><source>child.kicad_sch</source></title_block></sheet>
</design><components>
<comp ref="R1"><value>10k</value><libsource lib="Device" part="R"/>
<sheetpath names="/A/" tstamps="/{A}/"/><tstamps>{SYMBOL}</tstamps></comp>
<comp ref="R2"><value>10k</value><libsource lib="Device" part="R"/>
<sheetpath names="/B/" tstamps="/{B}/"/><tstamps>{SYMBOL}</tstamps></comp>
</components><nets><net name="GND" class="Default">
<node ref="R1" pin="1" pintype="passive"/><node ref="R2" pin="1" pintype="passive"/>
</net></nets></export>"""


def parse(xml: str = XML) -> IRCircuit:
    return parse_native_netlist(xml.encode(), root_uuid=ROOT, root_name="main.kicad_sch")


def test_repeated_sheet_instances_preserve_native_links_and_net_edges() -> None:
    circuit = parse()
    graph = graph_from_circuit(circuit)
    assert len(circuit.components) == 2
    assert circuit.sheet_hierarchy == (f"/{ROOT}", f"/{ROOT}/{A}", f"/{ROOT}/{B}")
    components = graph.entities_of_kind(GraphEntityKind.COMPONENT)
    assert [entity.stable_key for entity in components] == ["R1", "R2"]
    assert [entity.native_links[-1].key for entity in components] == [
        f"/{ROOT}/{A}/{SYMBOL}",
        f"/{ROOT}/{B}/{SYMBOL}",
    ]
    assert sum(edge.kind == GraphEdgeKind.CONNECTS_TO for edge in graph.edges) == 2
    assert graph.to_document() == graph_from_circuit(parse()).to_document()


def test_native_attribute_update_preserves_provenance() -> None:
    before = parse()
    after = parse(XML.replace("<value>10k</value>", "<value>12k</value>", 1))
    graph = graph_from_circuit(before)
    result = update_graph_from_circuit(graph, before, after)
    assert result.work_units == 1
    assert graph.to_document() == graph_from_circuit(after).to_document()
    after.native_instances["R1"] = replace(after.native_instances["R1"], symbol_uuids=(B,))
    with pytest.raises(ValueError, match="rebuild"):
        update_graph_from_circuit(graph, before, after)


@pytest.mark.parametrize(
    "old,new",
    [
        ('version="E"', 'version="F"'),
        ('ref="R2"', 'ref="R1"'),
        ('<node ref="R2" pin="1"', '<node ref="absent" pin="1"'),
        ('<node ref="R2" pin="1"', '<node ref="R1" pin="1"'),
        (f'<sheetpath names="/B/" tstamps="/{B}/"/>', f'<sheetpath names="/A/" tstamps="/{A}/"/>'),
        (
            f'<sheetpath names="/B/" tstamps="/{B}/"/>',
            '<sheetpath names="/B/" tstamps="/invalid/"/>',
        ),
    ],
)
def test_native_export_rejects_unknown_or_conflicting_identity(old: str, new: str) -> None:
    xml = XML.replace(old, new, 1)
    with pytest.raises(ValueError):
        parse(xml)


def test_native_export_rejects_xml_entities() -> None:
    with pytest.raises(ValueError):
        parse('<!DOCTYPE export [<!ENTITY a SYSTEM "file:///not-read">]>' + XML)


SOURCES = ("main.kicad_sch", "child.kicad_sch")
COMPAT = "kicad-10:xml-E:graph-v1"


@pytest.fixture
def native_project(tmp_path: Path) -> Path:
    sheets = "".join(
        f'(sheet (at 20 30) (size 20 20) (uuid "{uid}") '
        f'(property "Sheetname" "{name}") (property "Sheetfile" "child.kicad_sch"))'
        for uid, name in ((A, "A"), (B, "B"))
    )
    (tmp_path / SOURCES[0]).write_text(
        f'(kicad_sch (version 20250114) (uuid "{ROOT}") {sheets})', encoding="utf-8"
    )
    (tmp_path / SOURCES[1]).write_text(
        f'(kicad_sch (version 20250114) (uuid "{B}") '
        f'(symbol (lib_id "Device:R") (uuid "{SYMBOL}") (property "Value" "10k")))',
        encoding="utf-8",
    )
    return tmp_path


def _capture(root: Path, xml: str = XML) -> NativeHierarchySnapshot:
    def cli(*args: str) -> tuple[int, str, str]:
        copied = Path(args[-1])
        assert copied.parent != root
        assert copied.name == SOURCES[0]
        assert copied.read_bytes() == (root / SOURCES[0]).read_bytes()
        Path(args[-2]).write_text(xml, encoding="utf-8")
        return 0, "", ""

    return capture_native_hierarchy(root, SOURCES[0], SOURCES, run_cli=cli)


def _reopen(root: Path, snapshot: NativeHierarchySnapshot) -> PersistentProjectState:
    return PersistentProjectState.load_verified(
        root,
        root / ".kicad-mcp-cache" / "native.json",
        project_key=ROOT,
        native_sources=SOURCES,
        compatibility_key=COMPAT,
        native_snapshot=snapshot,
    )


def test_native_state_reopen_and_bounded_attribute_edit(native_project: Path) -> None:
    root = native_project
    before = _capture(root)
    state = PersistentProjectState.rebuild_native(before, compatibility_key=COMPAT)
    cache = root / ".kicad-mcp-cache" / "native.json"
    state.save_atomic(cache)
    assert _reopen(root, before).graph.to_document() == state.graph.to_document()
    with pytest.raises(StateRebuildRequiredError):
        PersistentProjectState.load_verified(
            root, cache, project_key=ROOT, native_sources=SOURCES, compatibility_key=COMPAT
        )
    token = state.prepare_native_edit()
    child = root / SOURCES[1]
    child.write_text(child.read_text().replace("10k", "12k"), encoding="utf-8")
    with pytest.raises(StateRebuildRequiredError):
        state.verify_sources()
    # A reused sheet's value change applies to both instances.
    after = _capture(root, XML.replace("10k", "12k"))
    entry = state.apply_hierarchy_edit(token, before, after)
    assert entry.work_units == 2
    assert state.graph.to_document() == graph_from_circuit(after.circuit).to_document()
    state.save_atomic(cache)
    assert _reopen(root, after).graph.to_document() == state.graph.to_document()
    with pytest.raises(StateRebuildRequiredError):
        _reopen(root, before)
    (root / "new.kicad_sch").write_text("(kicad_sch)", encoding="utf-8")
    with pytest.raises(StateRebuildRequiredError):
        state.verify_sources()


def test_native_topology_change_requires_clean_rebuild(native_project: Path) -> None:
    before = _capture(native_project)
    state = PersistentProjectState.rebuild_native(before, compatibility_key=COMPAT)
    token = state.prepare_native_edit()
    child = native_project / SOURCES[1]
    child.write_text(child.read_text() + "\n", encoding="utf-8")
    after = _capture(native_project, XML.replace('name="GND"', 'name="SIGNAL"'))
    original = state.graph.to_document()
    with pytest.raises(StateRebuildRequiredError, match="rebuild"):
        state.apply_hierarchy_edit(token, before, after)
    assert state.graph.to_document() == original
    rebuilt = PersistentProjectState.rebuild_native(after, compatibility_key=COMPAT)
    assert rebuilt.graph.to_document() == graph_from_circuit(after.circuit).to_document()


@pytest.mark.parametrize(
    "filename", ["../child.kicad_sch", "/child.kicad_sch", "missing.kicad_sch"]
)
def test_capture_rejects_untracked_or_escaped_sheet_before_export(
    native_project: Path,
    filename: str,
) -> None:
    root = native_project / SOURCES[0]
    root.write_text(root.read_text().replace("child.kicad_sch", filename), encoding="utf-8")

    def unexpected_cli(*_args: str) -> tuple[int, str, str]:
        pytest.fail("unsafe source must not reach the native CLI")

    with pytest.raises(ValueError):
        capture_native_hierarchy(native_project, SOURCES[0], SOURCES, run_cli=unexpected_cli)


def test_capture_rejects_unverified_symbol_stamp(native_project: Path) -> None:
    xml = XML.replace(SYMBOL, ROOT)
    with pytest.raises(ValueError, match="not on its declared source sheet"):
        _capture(native_project, xml)


def test_capture_rejects_unknown_source_version(native_project: Path) -> None:
    child = native_project / SOURCES[1]
    child.write_text(child.read_text().replace("20250114", "20990101"), encoding="utf-8")
    with pytest.raises(ValueError, match="unsupported native schematic version"):
        _capture(native_project)


def test_capture_rejects_missing_native_sheet_instance(native_project: Path) -> None:
    xml = XML.replace(
        f'<sheet name="/B/" tstamps="/{B}/">\n'
        "<title_block><source>child.kicad_sch</source></title_block></sheet>",
        "",
    )
    with pytest.raises(ValueError, match="does not cover"):
        _capture(native_project, xml)


def test_native_state_rejects_self_consistent_forged_cache(native_project: Path) -> None:
    snapshot = _capture(native_project)
    state = PersistentProjectState.rebuild_native(snapshot, compatibility_key=COMPAT)
    path = native_project / ".kicad-mcp-cache" / "native.json"
    state.save_atomic(path)
    component = state.graph.entities_of_kind(GraphEntityKind.COMPONENT)[0]
    # Even recomputing cached entity hashes cannot make a false native link authoritative.
    forged = replace(component, native_links=component.native_links[:-1])
    state.graph.entities[component.entity_id] = forged
    state.entity_hashes[component.entity_id] = canonical_graph_entity_sha256(forged)
    state.save_atomic(path)
    with pytest.raises(StateRebuildRequiredError):
        _reopen(native_project, snapshot)


def test_capture_rejects_concurrent_source_change(native_project: Path) -> None:
    def cli(*args: str) -> tuple[int, str, str]:
        Path(args[-2]).write_text(XML, encoding="utf-8")
        child = native_project / SOURCES[1]
        child.write_text(child.read_text() + "\n", encoding="utf-8")
        return 0, "", ""

    with pytest.raises(StateRebuildRequiredError, match="source changed during native export"):
        capture_native_hierarchy(native_project, SOURCES[0], SOURCES, run_cli=cli)


def test_capture_rejects_symlinked_sheet(native_project: Path) -> None:
    child = native_project / SOURCES[1]
    outside = native_project.parent / "external.kicad_sch"
    outside.write_bytes(child.read_bytes())
    child.unlink()
    try:
        child.symlink_to(outside)
    except OSError:
        pytest.skip("symlink unavailable on this host")
    with pytest.raises(StateRebuildRequiredError, match="symlinked"):
        _capture(native_project)


def test_capture_rejects_cycle(native_project: Path) -> None:
    root = native_project / SOURCES[0]
    root.write_text(root.read_text().replace("child.kicad_sch", "main.kicad_sch"), encoding="utf-8")
    with pytest.raises(ValueError, match="cyclic"):
        _capture(native_project)
