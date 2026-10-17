"""KiCad 10 PCB schematic-to-footprint metadata and angle regressions (#1318, #1319)."""

from __future__ import annotations

from pathlib import Path

from kicad_mcp.tools.board_file import _iter_blocks
from kicad_mcp.tools.pcb import _render_board_footprint_block


def test_schematic_sync_preserves_full_library_id_properties_and_child_angles(
    tmp_path: Path, monkeypatch
) -> None:
    fixture = tmp_path / "SOIC.kicad_mod"
    fixture.write_text(
        """(footprint "SOIC"
            (layer "F.Cu")
            (property "Reference" "REF**" (at 0 -2 0) (layer "F.SilkS"))
            (property "Value" "SOIC" (at 0 2 0) (layer "F.Fab"))
            (property "Datasheet" "" (at 0 0 0) (layer "F.Fab"))
            (pad "1" smd rect (at -1 0) (size 1 2) (layers "F.Cu"))
            (pad "2" smd rect (at 1 0 30) (size 1 2) (layers "F.Cu"))
            (fp_text user "USER" (at 0 3 0) (layer "F.SilkS"))
            (model "Package_SO.3dshapes/SOIC.step")
        )""",
        encoding="utf-8",
    )
    monkeypatch.setattr("kicad_mcp.tools.pcb._footprint_file", lambda *_: fixture)

    block = _render_board_footprint_block(
        "Package_SO:SOIC",
        reference="U1",
        value="Amplifier",
        x_mm=30,
        y_mm=40,
        rotation=90,
        pad_nets={"1": "VCC", "2": "GND"},
        properties={
            "Datasheet": "~",
            "Description": "Operational amplifier",
            "LCSC": "C123456",
        },
    )

    assert block.startswith('(footprint "Package_SO:SOIC"')
    assert "(at 30.0000 40.0000 90)" in block
    assert '(property "Datasheet" ""' in block
    assert '(property "Description" "Operational amplifier"' in block
    assert '(property "LCSC" "C123456"' in block
    assert '(property "Reference" "U1" (at 0 -2 90)' in block
    assert '(property "Value" "Amplifier" (at 0 2 90)' in block
    assert '(fp_text user "USER" (at 0 3 90)' in block
    pads = list(_iter_blocks(block, "pad"))
    assert len(pads) == 2
    assert "(at -1 0 90)" in pads[0]
    assert "(at 1 0 120)" in pads[1]
    assert '(net "VCC")' in pads[0]
    assert '(net "GND")' in pads[1]
    assert '(model "Package_SO.3dshapes/SOIC.step")' in block


def test_schematic_datasheet_url_is_not_normalized(tmp_path: Path, monkeypatch) -> None:
    fixture = tmp_path / "R.kicad_mod"
    fixture.write_text(
        '(footprint "R" (layer "F.Cu") (property "Datasheet" "" (at 0 0 0) (layer "F.Fab")))',
        encoding="utf-8",
    )
    monkeypatch.setattr("kicad_mcp.tools.pcb._footprint_file", lambda *_: fixture)
    block = _render_board_footprint_block(
        "Resistor_SMD:R",
        reference="R1",
        value="10k",
        x_mm=5,
        y_mm=8,
        rotation=0,
        pad_nets={},
        properties={
            "Datasheet": "https://example.com/resistor.pdf",
            "Custom": "~",
        },
    )
    assert '(property "Datasheet" "https://example.com/resistor.pdf"' in block
    assert '(property "Custom" "~"' in block


def test_zero_degree_sync_does_not_modify_library_child_angles(tmp_path: Path, monkeypatch) -> None:
    fixture = tmp_path / "R.kicad_mod"
    fixture.write_text(
        '(footprint "R" (layer "F.Cu")'
        ' (pad "1" smd rect (at -1 0) (size 1 2) (layers "F.Cu"))'
        ' (pad "2" smd rect (at 1 0 45) (size 1 2) (layers "F.Cu")))',
        encoding="utf-8",
    )
    monkeypatch.setattr("kicad_mcp.tools.pcb._footprint_file", lambda *_: fixture)
    block = _render_board_footprint_block(
        "Resistor_SMD:R",
        reference="R1",
        value="10k",
        x_mm=5,
        y_mm=8,
        rotation=0,
        pad_nets={},
    )
    assert "(at -1 0)" in block
    assert "(at 1 0 45)" in block
