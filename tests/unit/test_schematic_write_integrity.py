"""Schematic write-integrity guards (issue #193).

The transactional writer validates more than balanced parentheses: it refuses
output with duplicate element UUIDs, the classic silent-corruption signature of a
regex/string mutation that cloned a block instead of minting a fresh UUID.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kicad_mcp.errors import SchematicWriteUnsafeError
from kicad_mcp.tools.schematic import (
    _duplicate_uuids,
    _validate_schematic_text,
    transactional_write,
)

_CLEAN = (
    '(kicad_sch (uuid "00000000-0000-0000-0000-000000000001")'
    ' (label "A" (at 0 0 0) (uuid "00000000-0000-0000-0000-000000000002"))'
    ' (label "B" (at 0 5 0) (uuid "00000000-0000-0000-0000-000000000003")))'
)
_DUPLICATE = (
    '(kicad_sch (uuid "00000000-0000-0000-0000-000000000001")'
    ' (label "A" (at 0 0 0) (uuid "00000000-0000-0000-0000-000000000002"))'
    ' (label "B" (at 0 5 0) (uuid "00000000-0000-0000-0000-000000000002")))'
)


def test_duplicate_uuids_detects_clones() -> None:
    assert _duplicate_uuids(_CLEAN) == set()
    assert _duplicate_uuids(_DUPLICATE) == {"00000000-0000-0000-0000-000000000002"}


def test_validate_accepts_clean_schematic() -> None:
    _validate_schematic_text(_CLEAN)  # must not raise


def test_validate_refuses_duplicate_uuids() -> None:
    with pytest.raises(ValueError, match="duplicate element UUIDs"):
        _validate_schematic_text(_DUPLICATE)


def test_validate_still_refuses_unbalanced_parens() -> None:
    with pytest.raises(ValueError, match="unbalanced parentheses"):
        _validate_schematic_text('(kicad_sch (uuid "x")')


_REFERENCE_PROP = (
    '    (property "Reference" "#PWR01" (at 10 12 0) '
    "(effects (font (size 1.27 1.27)) (hide yes)))\n"
)
_VALUE_PROP = '    (property "Value" "GND" (at 10 14 0) (effects (font (size 1.27 1.27))))\n'
_LOCAL_LABEL = (
    '  (label "LOCAL" (at 20 20 0) (effects (font (size 1.524 1.524))) '
    '(uuid "cccccccc-cccc-cccc-cccc-cccccccccccc"))\n'
)
_GLOBAL_LABEL = (
    '  (global_label "GLOBAL" (shape input) (at 30 30 0) '
    "(effects (font (size 1.524 1.524))) "
    '(uuid "dddddddd-dddd-dddd-dddd-dddddddddddd"))\n'
)
_HIER_LABEL = (
    '  (hierarchical_label "HIER" (shape output) (at 40 40 0) '
    "(effects (font (size 1.524 1.524))) "
    '(uuid "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"))\n'
)
_SHEETNAME_PROP = (
    '    (property "Sheetname" "child" (at 70 69.293 0) (effects (font (size 1.27 1.27))))\n'
)
_SHEETFILE_PROP = (
    '    (property "Sheetfile" "child.kicad_sch" (at 70 91.353 0) '
    "(effects (font (size 1.27 1.27))))\n"
)

_FRAGILE_SCHEMATIC = "".join(
    [
        "(kicad_sch\n",
        "  (version 20250316)\n",
        '  (generator "test")\n',
        '  (uuid "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")\n',
        '  (paper "A4")\n',
        "  (lib_symbols)\n",
        "  (symbol\n",
        '    (lib_id "power:GND")\n',
        "    (at 10 10 0)\n",
        "    (unit 1)\n",
        "    (exclude_from_sim no)\n",
        "    (in_bom yes)\n",
        "    (on_board yes)\n",
        "    (dnp no)\n",
        '    (uuid "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")\n',
        _REFERENCE_PROP,
        _VALUE_PROP,
        "  )\n",
        _LOCAL_LABEL,
        _GLOBAL_LABEL,
        _HIER_LABEL,
        "  (bus\n",
        "    (pts (xy 50 50) (xy 60 50))\n",
        "    (stroke (width 0) (type solid))\n",
        '    (uuid "ffffffff-ffff-ffff-ffff-ffffffffffff")\n',
        "  )\n",
        "  (bus_entry\n",
        "    (at 55 50)\n",
        "    (size 2.54 -2.54)\n",
        "    (stroke (width 0) (type solid))\n",
        '    (uuid "11111111-2222-3333-4444-555555555555")\n',
        "  )\n",
        "  (sheet\n",
        "    (at 70 70)\n",
        "    (size 25 20)\n",
        "    (fields_autoplaced yes)\n",
        "    (stroke (width 0.1524) (type solid))\n",
        "    (fill (color 0 0 0 0.0000))\n",
        '    (uuid "22222222-3333-4444-5555-666666666666")\n',
        _SHEETNAME_PROP,
        _SHEETFILE_PROP,
        "  )\n",
        '  (sheet_instances (path "/" (page "1")))\n',
        "  (embedded_fonts no)\n",
        ")\n",
    ]
)


def _write_schematic(tmp_path: Path) -> Path:
    path = tmp_path / "fragile.kicad_sch"
    path.write_text(_FRAGILE_SCHEMATIC, encoding="utf-8")
    return path


def test_transactional_write_preserves_fragile_constructs_on_additive_edit(tmp_path: Path) -> None:
    path = _write_schematic(tmp_path)
    original = path.read_text(encoding="utf-8")

    def add_wire(text: str) -> str:
        block = (
            "  (wire\n"
            "    (pts (xy 1 1) (xy 2 2))\n"
            "    (stroke (width 0) (type solid))\n"
            '    (uuid "33333333-4444-5555-6666-777777777777")\n'
            "  )\n"
        )
        return text.replace("  (sheet_instances", block + "  (sheet_instances", 1)

    transactional_write(add_wire, path)
    updated = path.read_text(encoding="utf-8")
    for marker in ("GLOBAL", "HIER", "power:GND", "(bus", "(bus_entry", "Sheetname"):
        assert marker in updated
    assert updated.count("(wire") == original.count("(wire") + 1


def test_transactional_write_refuses_unintentional_structural_loss_and_preserves_original(
    tmp_path: Path,
) -> None:
    path = _write_schematic(tmp_path)
    original = path.read_text(encoding="utf-8")

    def accidentally_drop_global_label(text: str) -> str:
        return text.replace(_GLOBAL_LABEL, "", 1)

    with pytest.raises(SchematicWriteUnsafeError, match="global_label"):
        transactional_write(accidentally_drop_global_label, path)

    assert path.read_text(encoding="utf-8") == original


def test_transactional_write_requires_explicit_opt_in_for_destructive_edits(tmp_path: Path) -> None:
    path = _write_schematic(tmp_path)

    def delete_local_label(text: str) -> str:
        return text.replace(_LOCAL_LABEL, "", 1)

    with pytest.raises(SchematicWriteUnsafeError, match="label"):
        transactional_write(delete_local_label, path)

    transactional_write(delete_local_label, path, allow_node_loss=True)
    assert "LOCAL" not in path.read_text(encoding="utf-8")
