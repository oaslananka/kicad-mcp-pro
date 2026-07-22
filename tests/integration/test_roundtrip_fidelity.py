"""Round-trip fidelity for ``.kicad_sch`` writes (work order P2-T1/P2-T2, K5/K6).

Proves the round-trip-safe edit primitive never silently corrupts a schematic: it
either preserves every structural node or refuses the write and restores the original.
Also characterizes the kicad-sch-api 0.5.x ``global_label`` drop the guard exists for —
if that characterization test starts failing, the library fixed the bug and the guard
docs should be revisited.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from kicad_mcp.errors import SchematicWriteUnsafeError
from kicad_mcp.utils.schematic_roundtrip import (
    dropped_nodes,
    fidelity_fingerprint,
    load,
    roundtrip_edit,
)

_MINIMAL = (
    "(kicad_sch\n"
    "\t(version 20250316)\n"
    '\t(generator "test")\n'
    '\t(uuid "11111111-2222-3333-4444-555555555555")\n'
    '\t(paper "A4")\n'
    "\t(lib_symbols)\n"
    '\t(label "LOCAL1" (at 30 30 0) (uuid "10000000-0000-0000-0000-000000000001"))\n'
    '\t(hierarchical_label "HIER1" (shape input) (at 70 70 0)'
    ' (uuid "30000000-0000-0000-0000-000000000003"))\n'
    '\t(no_connect (at 90 90) (uuid "40000000-0000-0000-0000-000000000004"))\n'
    '\t(sheet_instances (path "/" (page "1")))\n'
    "\t(embedded_fonts no)\n"
    ")\n"
)
_WITH_GLOBAL = _MINIMAL.replace(
    "\t(no_connect",
    '\t(global_label "GLOBAL1" (shape input) (at 50 50 0)'
    ' (uuid "20000000-0000-0000-0000-000000000002"))\n\t(no_connect',
)

FIXTURES = Path(__file__).resolve().parents[2] / "packages" / "kicad-fixtures" / "fixtures"


def _write(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "t.kicad_sch"
    path.write_text(content, encoding="utf-8")
    return path


def test_dropped_nodes_detects_count_decrease() -> None:
    before = '(kicad_sch (global_label "A") (label "B"))'
    after = '(kicad_sch (label "B"))'
    assert dropped_nodes(before, after).get("global_label") == (1, 0)
    assert "label" not in dropped_nodes(before, after)


def test_roundtrip_preserves_local_and_hierarchical_labels(tmp_path: Path) -> None:
    path = _write(tmp_path, _MINIMAL)
    before = fidelity_fingerprint(path.read_text(encoding="utf-8"))
    with roundtrip_edit(path):
        pass  # no-op edit
    after = fidelity_fingerprint(path.read_text(encoding="utf-8"))
    assert after["counts"]["label"] == before["counts"]["label"]
    assert after["counts"]["hierarchical_label"] == before["counts"]["hierarchical_label"]
    assert after["counts"]["no_connect"] == before["counts"]["no_connect"]
    assert after["uuids"] >= before["uuids"]


def test_guard_refuses_to_drop_global_label_and_restores(tmp_path: Path) -> None:
    path = _write(tmp_path, _WITH_GLOBAL)
    original = path.read_text(encoding="utf-8")
    with pytest.raises(SchematicWriteUnsafeError) as exc_info:
        with roundtrip_edit(path):
            pass  # no-op; the serializer itself would drop the global label
    assert "global_label" in str(exc_info.value)
    assert exc_info.value.code == "SCHEMATIC_WRITE_UNSAFE"
    # The schematic is never left corrupted.
    assert path.read_text(encoding="utf-8") == original
    assert "GLOBAL1" in path.read_text(encoding="utf-8")


def test_characterizes_kicad_sch_api_global_label_drop(tmp_path: Path) -> None:
    """Direct evidence of the kicad-sch-api 0.5.x limitation the guard exists for.

    If this fails, the library now preserves global_label on save — update the guard
    docstrings and consider relaxing the guard.
    """
    path = _write(tmp_path, _WITH_GLOBAL)
    sch = load(path)
    sch.save()
    out = path.read_text(encoding="utf-8")
    assert "GLOBAL1" not in out, "kicad-sch-api appears to preserve global_label now"
    assert "LOCAL1" in out
    assert "HIER1" in out


def test_guard_protects_real_multi_sheet_fixture(tmp_path: Path) -> None:
    fixture = FIXTURES / "multi-sheet-schematic" / "multi-sheet-schematic.kicad_sch"
    if not fixture.exists():
        pytest.skip(f"fixture missing: {fixture}")
    work_dir = tmp_path / fixture.parent.name
    work_dir.mkdir()
    for source in fixture.parent.rglob("*"):
        destination = work_dir / source.relative_to(fixture.parent)
        if source.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
    work = work_dir / fixture.name
    original = work.read_text(encoding="utf-8")

    # This fixture contains a global_label, so a kicad-sch-api round trip would drop it;
    # the guard must refuse and restore rather than corrupt the file.
    with pytest.raises(SchematicWriteUnsafeError):
        with roundtrip_edit(work):
            pass
    assert work.read_text(encoding="utf-8") == original
