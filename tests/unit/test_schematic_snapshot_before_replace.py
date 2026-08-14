from __future__ import annotations

from pathlib import Path

from kicad_mcp.tools.schematic import (
    _count_schematic_nodes,
    _snapshot_sheet_before_replace,
)

_POPULATED_SHEET = """(kicad_sch
\t(version 20250316)
\t(paper "A4")
\t(lib_symbols
\t\t(symbol "Device:R")
\t)
\t(symbol
\t\t(lib_id "Device:R")
\t\t(property "Reference" "R1")
\t)
\t(symbol
\t\t(lib_id "Device:R")
\t\t(property "Reference" "R2")
\t)
\t(global_label "NET_A")
\t(label "NET_B")
)
"""

_EMPTY_SHEET = '(kicad_sch\n\t(paper "A4")\n)\n'


def test_count_schematic_nodes_ignores_library_definitions() -> None:
    symbols, labels = _count_schematic_nodes(_POPULATED_SHEET)
    # Two placed symbols; the lib_symbols "Device:R" definition is not counted.
    assert symbols == 2
    assert labels == 2


def test_snapshot_backs_up_nonempty_sheet(tmp_path: Path) -> None:
    sch = tmp_path / "demo.kicad_sch"
    sch.write_text(_POPULATED_SHEET, encoding="utf-8")

    symbols, labels, backup = _snapshot_sheet_before_replace(sch)

    assert (symbols, labels) == (2, 2)
    assert backup is not None
    assert backup.parent == tmp_path
    assert backup.name.startswith("demo.kicad_sch.")
    assert backup.name.endswith(".bak")
    assert backup.read_text(encoding="utf-8") == _POPULATED_SHEET


def test_snapshot_skips_backup_for_empty_sheet(tmp_path: Path) -> None:
    sch = tmp_path / "demo.kicad_sch"
    sch.write_text(_EMPTY_SHEET, encoding="utf-8")

    symbols, labels, backup = _snapshot_sheet_before_replace(sch)

    assert (symbols, labels) == (0, 0)
    assert backup is None
    assert list(tmp_path.glob("*.bak")) == []


def test_snapshot_handles_missing_file(tmp_path: Path) -> None:
    sch = tmp_path / "missing.kicad_sch"

    assert _snapshot_sheet_before_replace(sch) == (0, 0, None)
