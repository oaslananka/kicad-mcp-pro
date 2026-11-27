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


def _rule_area_points(block: str) -> list[tuple[float, float]]:
    import re

    zone = next(iter(_iter_blocks(block, "zone")))
    return [(float(x), float(y)) for x, y in re.findall(r"\(xy\s+(-?[\d.]+)\s+(-?[\d.]+)\)", zone)]


@pytest.mark.parametrize(
    ("rotation", "expected"),
    [
        (0, [(36, 22.25), (84, 22.25), (84, 43.44), (36, 43.44)]),
        (90, [(32.25, 74), (32.25, 26), (53.44, 26), (53.44, 74)]),
        (180, [(84, 77.75), (36, 77.75), (36, 56.56), (84, 56.56)]),
    ],
)
def test_library_rule_area_is_placed_in_board_coordinates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    rotation: int,
    expected: list[tuple[float, float]],
) -> None:
    fixture = tmp_path / "RF.kicad_mod"
    fixture.write_text(
        """(footprint "RF"
            (layer "F.Cu")
            (property "Reference" "REF**" (at 0 0))
            (property "Value" "RF" (at 0 0))
            (zone (layers "F.Cu" "B.Cu")
                (uuid "22222222-2222-4222-8222-222222222222")
                (name "antenna (xy 999 999)")
                (keepout (tracks not_allowed) (vias not_allowed)
                    (pads not_allowed) (copperpour not_allowed) (footprints not_allowed))
                (polygon (pts (xy -24 -27.75) (xy 24 -27.75)
                    (xy 24 -6.56) (xy -24 -6.56))))
            (pad "1" smd custom (at 1 2) (size 1 1) (layers "F.Cu")
                (primitives (gr_poly (pts (xy 0 0) (xy 1 0) (xy 0 1)) (width 0))))
            (fp_line (start 0 0) (end 1 1) (layer "F.SilkS")))""",
        encoding="utf-8",
    )
    monkeypatch.setattr(pcb, "_footprint_file", lambda *_: fixture)
    block = _render_board_footprint_block(
        "RF_Module:RF",
        reference="U3",
        value="RF",
        x_mm=60,
        y_mm=50,
        rotation=rotation,
        pad_nets={"1": "GND"},
    )
    # The quoted name is not a coordinate node.
    points = _rule_area_points(block)
    assert points[0] == (999, 999)
    assert points[1:] == expected
    assert '(name "antenna (xy 999 999)")' in block
    assert '(uuid "22222222-2222-4222-8222-222222222222")' in block
    assert "(keepout (tracks not_allowed) (vias not_allowed)" in block
    assert "(primitives (gr_poly (pts (xy 0 0) (xy 1 0) (xy 0 1)) (width 0)))" in block
    assert '(fp_line (start 0 0) (end 1 1) (layer "F.SilkS"))' in block
    assert '(net "GND")' in block


def test_existing_rule_area_follows_file_placement_and_round_trip() -> None:
    block = """(footprint "RF"
        (layer "F.Cu")
        (uuid "11111111-1111-4111-8111-111111111111")
        (at 60 50 0)
        (zone (layers "F.Cu" "B.Cu") (keepout (tracks not_allowed))
            (polygon (pts (xy 36 22.25) (xy 84 22.25) (xy 84 43.44) (xy 36 43.44))))
        (pad "1" smd rect (at 1 2) (size 1 1) (layers "F.Cu")))"""
    moved = pcb._replace_root_at(block, x_mm=61, y_mm=50, rotation=90)
    assert _rule_area_points(moved) == [(33.25, 74), (33.25, 26), (54.44, 26), (54.44, 74)]
    returned = pcb._replace_root_at(moved, x_mm=60, y_mm=50, rotation=0)
    assert _rule_area_points(returned) == _rule_area_points(block)
    assert '(uuid "11111111-1111-4111-8111-111111111111")' in returned
    assert "(keepout (tracks not_allowed))" in returned


def test_compact_footprint_root_pose_is_not_confused_with_pad_pose() -> None:
    block = (
        '(footprint "RF" (layer "F.Cu") (at 60 50) '
        "(zone (keepout (tracks not_allowed)) (polygon (pts (xy 59 49) "
        '(xy 61 49) (xy 61 51)))) (pad "1" smd rect (at 1 2)))'
    )
    moved = pcb._replace_root_at(block, x_mm=70, y_mm=80, rotation=0)
    assert _rule_area_points(moved) == [(69, 79), (71, 79), (71, 81)]
    assert moved.count("(at ") == 2
    assert '(pad "1" smd rect (at 1 2))' in moved


def test_file_placement_rotates_absolute_pad_and_text_angles_by_delta() -> None:
    block = (
        '(footprint "RF" (layer "F.Cu") (at 60 50 30) '
        '(property "Reference" "U3" (at 0 -2 30)) '
        '(pad "1" smd rect (at 1 2 60) (size 1 2)) '
        '(fp_text user "test (pad fake (at 7 8 9))" (at 0 3 30)))'
    )
    moved = pcb._replace_root_at(block, x_mm=61, y_mm=50, rotation=90)
    assert '(property "Reference" "U3" (at 0 -2 90))' in moved
    assert '(pad "1" smd rect (at 1 2 120)' in moved
    assert '(fp_text user "test (pad fake (at 7 8 9))" (at 0 3 90))' in moved


def test_footprint_zone_transform_handles_arcs_and_multiple_polygons() -> None:
    block = (
        '(footprint "RF" (at 10 20) (zone (keepout (tracks not_allowed)) '
        "(polygon (pts (xy 11 20) (arc (start 12 20) (mid 13 21) (end 12 22)))) "
        "(polygon (pts (xy 9 19) (xy 8 19) (xy 8 18)))) "
        "(zone (keepout (vias not_allowed)) (polygon (pts (xy 10 21)))) )"
    )
    moved = pcb._replace_root_at(block, x_mm=30, y_mm=40, rotation=90)
    assert "(xy 30.000000 39.000000)" in moved
    assert "(arc (start 30.000000 38.000000) (mid 31.000000 37.000000) " in moved
    assert "(end 32.000000 38.000000))" in moved
    assert "(xy 29.000000 41.000000)" in moved
    assert "(xy 31.000000 40.000000)" in moved


def test_unplaced_footprint_with_zone_refuses_unknown_world_pose() -> None:
    block = '(footprint "RF" (layer "F.Cu") (zone (polygon (pts (xy 0 0)))))'
    with pytest.raises(ValueError, match="no root placement"):
        pcb._replace_root_at(block, x_mm=60, y_mm=50, rotation=0)


@pytest.mark.parametrize(
    ("polygon", "message"),
    [
        ("(polygon (pts (xy invalid 2)))", "Unsupported coordinate"),
        ("(polygon (pts (arc (center 1 2))))", "Unsupported arc"),
        ("(polygon (pts (curve (xy 1 2))))", "Unsupported footprint zone polygon node"),
        ("(polygon)", "Missing footprint zone polygon points"),
    ],
)
def test_file_placement_rejects_unrecognized_zone_geometry(polygon: str, message: str) -> None:
    block = f'(footprint "RF" (at 10 20) (zone {polygon}))'
    with pytest.raises(ValueError, match=message):
        pcb._replace_root_at(block, x_mm=30, y_mm=40, rotation=90)


def test_file_placement_refuses_invalid_root_and_child_poses() -> None:
    with pytest.raises(ValueError, match="Unsupported footprint root placement"):
        pcb._replace_root_at('(footprint "RF" (at invalid 20))', x_mm=30, y_mm=40, rotation=90)
    with pytest.raises(ValueError, match="Unsupported footprint child placement"):
        pcb._replace_root_at(
            '(footprint "RF" (at 10 20) (pad "1" smd rect (at invalid 2)))',
            x_mm=30,
            y_mm=40,
            rotation=90,
        )


def test_unplaced_footprint_without_zone_can_receive_root_pose() -> None:
    block = '(footprint "RF"\n  (layer "F.Cu")\n  (pad "1" smd rect (at 1 2))\n)'
    placed = pcb._replace_root_at(block, x_mm=30, y_mm=40, rotation=0)
    assert "(at 30.0000 40.0000 0)" in placed
    assert '(pad "1" smd rect (at 1 2))' in placed
