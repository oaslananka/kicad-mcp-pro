from __future__ import annotations

import re
from types import SimpleNamespace

import pytest
from kipy.proto.board.board_types_pb2 import BoardLayer

from kicad_mcp.models.pcb import AutoPlaceBySchematicInput, StackupLayerSpec
from kicad_mcp.tools.pcb import (
    _append_to_footprint_block,
    _apply_stackup_to_board,
    _copper_layer_order,
    _direct_child_spans,
    _impedance_context_for_layer,
    _inner_layer_graphic_block,
    _parse_netlist_text,
    _parse_stackup_specs_from_board_text,
    _quoted_character_state,
    _replace_or_append_child_block,
    _stackup_layer_from_kipy,
    _strategy_board_positions,
    _total_stackup_thickness_mm,
)


def _four_layer_stackup() -> list[StackupLayerSpec]:
    return [
        StackupLayerSpec(name="F.Cu", type="signal", thickness_mm=0.035, material="Copper"),
        StackupLayerSpec(
            name="dielectric_1",
            type="dielectric",
            thickness_mm=0.2,
            material="FR4",
            epsilon_r=4.2,
            loss_tangent=0.02,
        ),
        StackupLayerSpec(name="In1.Cu", type="signal", thickness_mm=0.035, material="Copper"),
        StackupLayerSpec(
            name="dielectric_2",
            type="dielectric",
            thickness_mm=0.3,
            material="FR4",
            epsilon_r=4.0,
        ),
        StackupLayerSpec(name="In2.Cu", type="signal", thickness_mm=0.035, material="Copper"),
        StackupLayerSpec(
            name="dielectric_3",
            type="dielectric",
            thickness_mm=0.2,
            material="FR4",
            epsilon_r=4.3,
        ),
        StackupLayerSpec(name="B.Cu", type="signal", thickness_mm=0.035, material="Copper"),
    ]


def test_stackup_parser_and_impedance_context_cover_outer_and_inner_layers() -> None:
    original = "(kicad_pcb\n)"
    updated = _apply_stackup_to_board(original, _four_layer_stackup())
    parsed = _parse_stackup_specs_from_board_text(updated)

    assert parsed is not None
    assert [layer.name for layer in parsed if layer.name.endswith("_Cu")] == [
        "F_Cu",
        "In1_Cu",
        "In2_Cu",
        "B_Cu",
    ]
    assert parsed[1].loss_tangent == pytest.approx(0.02)
    outer_type, outer_height, outer_er, outer_oz = _impedance_context_for_layer(parsed, "F.Cu")
    inner_type, inner_height, inner_er, _inner_oz = _impedance_context_for_layer(parsed, "In1.Cu")

    assert outer_type == "microstrip"
    assert outer_height == pytest.approx(0.2)
    assert outer_er == pytest.approx(4.2)
    assert outer_oz > 0.9
    assert inner_type == "stripline"
    assert inner_height == pytest.approx(0.25)
    assert inner_er == pytest.approx(4.1)
    assert _parse_stackup_specs_from_board_text("(kicad_pcb)") is None
    with pytest.raises(ValueError, match="was not found"):
        _impedance_context_for_layer(parsed, "In8.Cu")
    with pytest.raises(ValueError, match="not a copper"):
        _copper_layer_order("F.SilkS")


def _kicad10_two_layer_board(*, b_cu_id: int = 2, extra: str = "") -> str:
    """A board in the shape KiCad 10 itself saves (layer ids, general children, setup)."""
    return "\n".join(
        [
            "(kicad_pcb",
            "\t(version 20260206)",
            '\t(generator "pcbnew")',
            '\t(generator_version "10.0")',
            "\t(general",
            "\t\t(thickness 1.6)",
            "\t\t(legacy_teardrops no)",
            "\t)",
            '\t(paper "A4")',
            "\t(layers",
            '\t\t(0 "F.Cu" signal)',
            f'\t\t({b_cu_id} "B.Cu" signal)',
            '\t\t(5 "F.SilkS" user "F.Silkscreen")',
            '\t\t(1 "F.Mask" user)',
            '\t\t(25 "Edge.Cuts" user)',
            "\t)",
            "\t(setup",
            "\t\t(pad_to_mask_clearance 0)",
            "\t)",
            extra,
            ")",
            "",
        ]
    )


def _layer_table_entries(board: str) -> list[str]:
    start = board.index("\t(layers")
    table = board[start : board.index("\n\t)", start)]
    return [line.strip() for line in table.splitlines()[1:]]


def test_apply_stackup_adds_inner_copper_layers_to_the_kicad10_layer_table() -> None:
    updated = _apply_stackup_to_board(_kicad10_two_layer_board(), _four_layer_stackup())

    entries = _layer_table_entries(updated)
    assert entries[:4] == [
        '(0 "F.Cu" signal)',
        '(4 "In1.Cu" signal)',
        '(6 "In2.Cu" signal)',
        '(2 "B.Cu" signal)',
    ]
    assert '(5 "F.SilkS" user "F.Silkscreen")' in entries
    # KiCad's own stackup syntax: quoted names, no positional index, copper typed "copper".
    assert re.search(r'\(layer "In1\.Cu"\s*\(type "copper"\)', updated)
    assert '(layer "dielectric 2"' in updated
    assert "(layer dielectric" not in updated
    assert '(layer "F.Cu" 0' not in updated
    # Other (general ...) children survive the thickness update.
    assert "(legacy_teardrops no)" in updated
    assert "(thickness 0.8400)" in updated
    assert "(pad_to_mask_clearance 0)" in updated


def test_apply_stackup_uses_legacy_inner_layer_ids_on_kicad8_boards() -> None:
    updated = _apply_stackup_to_board(_kicad10_two_layer_board(b_cu_id=31), _four_layer_stackup())

    assert _layer_table_entries(updated)[:4] == [
        '(0 "F.Cu" signal)',
        '(1 "In1.Cu" signal)',
        '(2 "In2.Cu" signal)',
        '(31 "B.Cu" signal)',
    ]


def test_apply_stackup_adds_missing_solder_mask_entries_to_the_layer_table() -> None:
    minimal = _kicad10_two_layer_board().replace('\t\t(1 "F.Mask" user)\n', "")
    layers = [
        StackupLayerSpec(name="F.Mask", thickness_mm=0.01),
        *_four_layer_stackup(),
        StackupLayerSpec(name="B.Mask", thickness_mm=0.01),
    ]

    updated = _apply_stackup_to_board(minimal, layers)

    entries = _layer_table_entries(updated)
    assert '(1 "F.Mask" user)' in entries
    assert '(3 "B.Mask" user)' in entries
    assert re.search(
        r'\(layer "F\.Mask"\s*\(type "Top Solder Mask"\)\s*\(thickness 0\.0100\)', updated
    )
    assert "(thickness 0.8600)" in updated


def _two_layer_stackup() -> list[StackupLayerSpec]:
    stackup = _four_layer_stackup()
    return [stackup[0], stackup[1], stackup[-1]]


def test_apply_stackup_removes_unused_inner_layers_and_refuses_used_ones() -> None:
    four_layer = _apply_stackup_to_board(_kicad10_two_layer_board(), _four_layer_stackup())

    back_to_two = _apply_stackup_to_board(four_layer, _two_layer_stackup())
    assert '"In1.Cu"' not in back_to_two
    assert '"In2.Cu"' not in back_to_two
    assert _layer_table_entries(back_to_two)[:2] == ['(0 "F.Cu" signal)', '(2 "B.Cu" signal)']

    with_track = four_layer.replace(
        "\n)\n",
        '\n\t(segment (start 0 0) (end 1 0) (width 0.2) (layer "In2.Cu") (net 0))\n)\n',
    )
    two_layer = _two_layer_stackup()
    with pytest.raises(ValueError, match=r"still carry board items: In2\.Cu"):
        _apply_stackup_to_board(with_track, two_layer)


def test_apply_stackup_rejects_copper_layers_out_of_kicad_order() -> None:
    stackup = _four_layer_stackup()
    skipped_in1 = [stackup[0], stackup[1], stackup[4], stackup[5], stackup[6]]

    base_board = _kicad10_two_layer_board()
    with pytest.raises(ValueError, match=r"F\.Cu, In1\.Cu, B\.Cu \(got: F\.Cu, In2\.Cu, B\.Cu\)"):
        _apply_stackup_to_board(base_board, skipped_in1)


def test_apply_stackup_treats_dielectrics_without_material_as_fr4_cores() -> None:
    layers = [
        StackupLayerSpec(name="F.Cu", thickness_mm=0.035),
        StackupLayerSpec(name="dielectric_1", thickness_mm=1.5),  # material defaults to "Copper"
        StackupLayerSpec(name="B.Cu", thickness_mm=0.035),
    ]

    updated = _apply_stackup_to_board(_kicad10_two_layer_board(), layers)

    assert re.search(r'\(layer "dielectric 1"\s*\(type "core"\)', updated)
    assert '(material "FR4")' in updated
    assert '"In1.Cu"' not in updated


def test_apply_stackup_keeps_the_existing_copper_finish() -> None:
    finished = _kicad10_two_layer_board().replace(
        "\t\t(pad_to_mask_clearance 0)",
        '\t\t(stackup\n\t\t\t(layer "F.Cu" (type "copper") (thickness 0.035))\n'
        '\t\t\t(copper_finish "ENIG")\n\t\t\t(dielectric_constraints no)\n\t\t)\n'
        "\t\t(pad_to_mask_clearance 0)",
    )

    updated = _apply_stackup_to_board(finished, _four_layer_stackup())

    assert '(copper_finish "ENIG")' in updated
    assert '(copper_finish "None")' not in updated
    assert updated.count("(stackup") == 1


# Stackup exactly as KiCad 10.0.7 saves a 4-layer, 0.8 mm board.
_KICAD_SAVED_STACKUP = """(kicad_pcb
\t(version 20260206)
\t(setup
\t\t(stackup
\t\t\t(layer "F.SilkS"
\t\t\t\t(type "Top Silk Screen")
\t\t\t)
\t\t\t(layer "F.Mask"
\t\t\t\t(type "Top Solder Mask")
\t\t\t\t(thickness 0.01)
\t\t\t)
\t\t\t(layer "F.Cu"
\t\t\t\t(type "copper")
\t\t\t\t(thickness 0.035)
\t\t\t)
\t\t\t(layer "dielectric 1"
\t\t\t\t(type "prepreg")
\t\t\t\t(thickness 0.1)
\t\t\t\t(material "FR4")
\t\t\t\t(epsilon_r 4.4)
\t\t\t\t(loss_tangent 0.02)
\t\t\t)
\t\t\t(layer "In1.Cu"
\t\t\t\t(type "copper")
\t\t\t\t(thickness 0.0152)
\t\t\t)
\t\t\t(layer "dielectric 2"
\t\t\t\t(type "core")
\t\t\t\t(thickness 0.4796)
\t\t\t\t(material "FR4")
\t\t\t\t(epsilon_r 4.6)
\t\t\t\t(loss_tangent 0.02)
\t\t\t)
\t\t\t(layer "In2.Cu"
\t\t\t\t(type "copper")
\t\t\t\t(thickness 0.0152)
\t\t\t)
\t\t\t(layer "dielectric 3"
\t\t\t\t(type "prepreg")
\t\t\t\t(thickness 0.1)
\t\t\t\t(material "FR4")
\t\t\t\t(epsilon_r 4.4)
\t\t\t\t(loss_tangent 0.02)
\t\t\t)
\t\t\t(layer "B.Cu"
\t\t\t\t(type "copper")
\t\t\t\t(thickness 0.035)
\t\t\t)
\t\t\t(layer "B.Mask"
\t\t\t\t(type "Bottom Solder Mask")
\t\t\t\t(thickness 0.01)
\t\t\t)
\t\t\t(layer "B.SilkS"
\t\t\t\t(type "Bottom Silk Screen")
\t\t\t)
\t\t\t(copper_finish "None")
\t\t\t(dielectric_constraints no)
\t\t)
\t)
)
"""


def test_stackup_parser_reads_kicads_own_syntax_and_ignores_solder_mask_for_impedance() -> None:
    parsed = _parse_stackup_specs_from_board_text(_KICAD_SAVED_STACKUP)

    assert parsed is not None
    assert [layer.name for layer in parsed] == [
        "F_Mask",
        "F_Cu",
        "dielectric_1",
        "In1_Cu",
        "dielectric_2",
        "In2_Cu",
        "dielectric_3",
        "B_Cu",
        "B_Mask",
    ]
    assert parsed[1].material == "Copper"
    assert _total_stackup_thickness_mm(parsed) == pytest.approx(0.8)
    # The microstrip under F.Cu is the 0.1 mm prepreg, not the 0.01 mm solder mask above it.
    trace_type, height, er, _oz = _impedance_context_for_layer(parsed, "F.Cu")
    assert (trace_type, height, er) == ("microstrip", pytest.approx(0.1), pytest.approx(4.4))


def test_stackup_parser_still_reads_the_positional_syntax_older_releases_wrote() -> None:
    legacy = (
        "(kicad_pcb\n\t(version 20260206)\n\t(setup\n\t\t(stackup\n"
        '\t\t\t(layer "F.Cu" 0 (type "signal") (thickness 0.0350) (material "Copper"))\n'
        '\t\t\t(layer dielectric 1 (type "core") (thickness 1.5000) (material "FR4"))\n'
        '\t\t\t(layer "B.Cu" 2 (type "signal") (thickness 0.0350) (material "Copper"))\n'
        "\t\t)\n\t)\n)\n"
    )

    parsed = _parse_stackup_specs_from_board_text(legacy)

    assert parsed is not None
    assert [layer.name for layer in parsed] == ["F_Cu", "dielectric_1", "B_Cu"]


def test_kipy_stackup_layers_without_thickness_are_skipped() -> None:
    silk = SimpleNamespace(layer=BoardLayer.BL_F_SilkS, thickness=0, material_name="")
    mask = SimpleNamespace(layer=BoardLayer.BL_F_Mask, thickness=10_000, material_name="")

    assert _stackup_layer_from_kipy(0, silk) is None
    mask_spec = _stackup_layer_from_kipy(1, mask)
    assert mask_spec is not None
    assert mask_spec.thickness_mm == pytest.approx(0.01)


def test_pcb_child_block_replacement_and_inner_graphic_rendering() -> None:
    parent = "(setup\n\t(pad_to_mask_clearance 0)\n)"
    replaced = _replace_or_append_child_block(
        parent,
        "pad_to_mask_clearance",
        "(pad_to_mask_clearance 0.05)",
    )
    appended = _replace_or_append_child_block("(setup\n)", "stackup", "(stackup\n)")
    footprint = '(footprint "R"\n\t(property "Reference" "R1")\n)'
    with_child = _append_to_footprint_block(footprint, "\t(fp_line (start 0 0) (end 1 0))")
    rect = _inner_layer_graphic_block("rect", "In1_Cu", 0.0, 0.0, 1.0, 1.0, "", 0.1)
    text = _inner_layer_graphic_block("text", "In2_Cu", 2.0, 3.0, 0.0, 0.0, "RF", 0.1)

    assert "(pad_to_mask_clearance 0.05)" in replaced
    assert "(stackup" in appended
    assert "fp_line" in with_child
    assert "fp_rect" in rect
    assert 'layer "In1.Cu"' in rect
    assert 'fp_text user "RF"' in text
    with pytest.raises(ValueError, match="shape_type"):
        _inner_layer_graphic_block("arc", "In1_Cu", 0.0, 0.0, 1.0, 1.0, "", 0.1)
    with pytest.raises(ValueError, match="Could not update"):
        _append_to_footprint_block("not a block", "\t(fp_line)")


def test_netlist_parser_and_non_cluster_placement_strategies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    netlist = """
    (export
      (nets
        (net (code "1") (name "USB_DP")
          (node (ref "J1") (pin "A6"))
          (node (ref "U1") (pin "12")))
        (net (code "2") (name "GND")
          (node (ref "J1") (pin "A1")))))
    """
    components = [
        {"reference": "U2", "footprint": "Resistor_SMD:R_0805"},
        {"reference": "U1", "footprint": "Resistor_SMD:R_0805"},
        {"reference": "J1", "footprint": "Connector_Generic:Conn_01x02"},
    ]
    linear_payload = AutoPlaceBySchematicInput(
        strategy="linear",
        origin_x_mm=10.0,
        origin_y_mm=20.0,
        grid_mm=1.0,
    )
    star_payload = AutoPlaceBySchematicInput(
        strategy="star",
        origin_x_mm=50.0,
        origin_y_mm=40.0,
        grid_mm=1.0,
    )
    monkeypatch.setattr(
        "kicad_mcp.tools.pcb._footprint_size_from_assignment",
        lambda _assignment: (2.0, 1.0),
    )

    linear = _strategy_board_positions(components, linear_payload, [])
    star = _strategy_board_positions(components, star_payload, [])

    assert _parse_netlist_text(netlist)[("J1", "A6")] == "USB_DP"
    assert list(linear) == ["J1", "U1", "U2"]
    assert linear["J1"][0] <= linear["U1"][0] <= linear["U2"][0]
    assert star["J1"] == (50.0, 40.0)
    assert star["U1"] != star["U2"]


@pytest.mark.parametrize(
    ("char", "in_string", "escaped", "expected"),
    [
        ('"', False, False, (True, False)),
        ("(", False, False, (False, False)),
        ('"', True, True, (True, False)),
        ("\\", True, False, (True, True)),
        ('"', True, False, (False, False)),
        ("(", True, False, (True, False)),
    ],
)
def test_stackup_quoted_character_state_handles_escaped_quotes_and_parentheses(
    char: str, in_string: bool, escaped: bool, expected: tuple[bool, bool]
) -> None:
    assert _quoted_character_state(char, in_string, escaped) == expected


def test_stackup_direct_child_spans_ignore_quoted_parentheses_and_escaped_quotes() -> None:
    parent = '(root "literal ( not a child \\"quoted\\" )" (first 1) (second 2))'
    spans = _direct_child_spans(parent)
    assert [name for name, _, _ in spans] == ["first", "second"]
    assert [parent[start:end] for _, start, end in spans] == ["(first 1)", "(second 2)"]
