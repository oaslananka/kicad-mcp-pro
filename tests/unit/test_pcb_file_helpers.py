from __future__ import annotations

import pytest

from kicad_mcp.models.pcb import AutoPlaceBySchematicInput, StackupLayerSpec
from kicad_mcp.tools.pcb import (
    _append_to_footprint_block,
    _apply_stackup_to_board,
    _copper_layer_order,
    _impedance_context_for_layer,
    _inner_layer_graphic_block,
    _parse_netlist_text,
    _parse_stackup_specs_from_board_text,
    _replace_or_append_child_block,
    _strategy_board_positions,
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
