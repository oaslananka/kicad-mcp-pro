"""KiCad 10 PCB schematic-to-footprint metadata and angle regressions (#1318, #1319)."""

from __future__ import annotations

from pathlib import Path

import pytest

from kicad_mcp.tools import pcb
from kicad_mcp.tools.board_file import _iter_blocks
from kicad_mcp.tools.pcb import (
    _placed_schematic_properties_for_sync,
    _render_board_footprint_block,
)


@pytest.mark.parametrize(
    ("version", "expected_placeholder"),
    [
        (20250316, ""),
        (20250317, ""),
        (20250318, "~"),
        (20260306, "~"),
    ],
)
def test_schematic_sync_placeholder_semantics_follow_schematic_version(
    tmp_path: Path, version: int, expected_placeholder: str
) -> None:
    schematic = tmp_path / "part.kicad_sch"
    schematic.write_text(
        f"""(kicad_sch
            (version {version})
            (generator "pytest")
            (symbol (lib_id "Device:R")
                (property "Reference" "R1")
                (property "Value" "10k")
                (property "Datasheet" "~")
                (property "Description" "~")
                (property "LCSC" "~")
                (property "Link" "https://example.test/a.pdf")
            )
        )""",
        encoding="utf-8",
    )

    properties = _placed_schematic_properties_for_sync(schematic)["R1"]
    for field in ("Datasheet", "Description", "LCSC"):
        assert properties[field] == expected_placeholder
    assert properties["Link"] == "https://example.test/a.pdf"


def test_versioned_fields_are_independent_per_sheet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kicad_mcp.tools import pcb

    files = []
    records = {}
    for index, version in enumerate((20250316, 20260306), 1):
        path = tmp_path / f"sheet{index}.kicad_sch"
        reference = f"R{index}"
        path.write_text(
            f'(kicad_sch (version {version}) (symbol (lib_id "Device:R") '
            f'(property "Reference" "{reference}") (property "Datasheet" "~")'
            f'(property "LCSC" "~")))',
            encoding="utf-8",
        )
        files.append(path)
        records[path] = {
            "symbols": [
                dict(
                    reference=reference,
                    value="10k",
                    footprint="Resistor_SMD:R_0805",
                    x=0,
                    y=0,
                    rotation=0,
                )
            ]
        }
    monkeypatch.setattr(pcb, "_schematic_files_for_pcb_sync", lambda: files)
    monkeypatch.setattr(pcb, "parse_schematic_file", lambda path: records[path])
    components, issues = pcb._collect_schematic_components()
    assert not issues
    fields = {c["reference"]: c["properties"] for c in components}
    assert fields["R1"]["Datasheet"] == fields["R1"]["LCSC"] == ""
    assert fields["R2"]["Datasheet"] == fields["R2"]["LCSC"] == "~"


def test_schematic_sync_uses_each_hierarchical_sheet_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root_sheet = tmp_path / "root.kicad_sch"
    child_sheet = tmp_path / "child.kicad_sch"
    for sheet, version, reference in (
        (root_sheet, 20250316, "R1"),
        (child_sheet, 20260306, "R2"),
    ):
        sheet.write_text(
            f"""(kicad_sch (version {version})
                (symbol (lib_id "Device:R")
                    (property "Reference" "{reference}")
                    (property "Datasheet" "~")
                    (property "LCSC" "~")
                )
            )""",
            encoding="utf-8",
        )

    monkeypatch.setattr(pcb, "_schematic_files_for_pcb_sync", lambda: [root_sheet, child_sheet])
    monkeypatch.setattr(
        pcb,
        "parse_schematic_file",
        lambda file: {
            "symbols": [
                {
                    "reference": "R1" if file == root_sheet else "R2",
                    "value": "10k",
                    "footprint": "Resistor_SMD:R_0603_1608Metric",
                    "x": 1.0,
                    "y": 2.0,
                    "rotation": 0,
                }
            ]
        },
    )

    components, issues = pcb._collect_schematic_components()
    assert not issues
    by_reference = {part["reference"]: part["properties"] for part in components}
    assert by_reference["R1"]["Datasheet"] == ""
    assert by_reference["R1"]["LCSC"] == ""
    assert by_reference["R2"]["Datasheet"] == "~"
    assert by_reference["R2"]["LCSC"] == "~"


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
    assert '(property "Datasheet" "~"' in block
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
