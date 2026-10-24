"""Verify unit selection and first-alias-wins ordering for KiCad symbol aliases."""

from __future__ import annotations

from pathlib import Path

import pytest

from kicad_mcp.tools import schematic


@pytest.mark.parametrize("unit", [1, 2])
def test_pin_aliases_include_common_pins_and_exclude_other_units(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, unit: int
) -> None:
    fixture = """(kicad_symbol_lib
    (symbol "Multi"
      (symbol "Multi_0_1"
        (pin passive line (at 0 0 0) (number "99") (name "COMMON")))
      (symbol "Multi_1_1"
        (pin passive line (at -2.54 0 0) (number "1") (name "UNIT1")))
      (symbol "Multi_2_1"
        (pin passive line (at 2.54 0 180) (number "2") (name "UNIT2")))))"""
    f = tmp_path / "Device.kicad_sym"
    f.write_text(fixture, encoding="utf-8")
    monkeypatch.setattr(schematic, "_symbol_library_file", lambda _lib: f)
    aliases = schematic.get_pin_alias_positions("Device", "Multi", 50, 50, unit=unit)
    assert "99" in aliases
    assert "COMMON" in aliases
    assert f"UNIT{unit}" in aliases
    assert f"UNIT{3 - unit}" not in aliases
