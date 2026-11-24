"""Unit tests for symbol text-field auto-placement."""

from __future__ import annotations

from pathlib import Path

import pytest

from kicad_mcp.utils.field_placer import (
    FieldSpec,
    autoplace_fields,
    field_extent,
    pin_sides,
)
from kicad_mcp.utils.geometry import Box

# A vertical 2-pin part (resistor): body 2x5 mm, pins exit top and bottom.
VERTICAL_BODY = Box(-1.0, -2.5, 1.0, 2.5)
VERTICAL_PINS = [(0.0, -3.8), (0.0, 3.8)]


def test_pin_sides_detects_vertical_part() -> None:
    assert pin_sides(VERTICAL_BODY, VERTICAL_PINS) == frozenset({"top", "bottom"})


def test_pin_sides_detects_horizontal_part() -> None:
    body = Box(-2.5, -1.0, 2.5, 1.0)
    pins = [(-3.8, 0.0), (3.8, 0.0)]
    assert pin_sides(body, pins) == frozenset({"left", "right"})


def test_fields_avoid_pin_sides() -> None:
    specs = [FieldSpec("Reference", "R1"), FieldSpec("Value", "10k")]
    placements = autoplace_fields(VERTICAL_BODY, VERTICAL_PINS, [], specs)
    # Pins exit top/bottom, so text must go to a horizontal side (left/right).
    for placement in placements:
        assert placement.x >= VERTICAL_BODY.x_max or placement.x <= VERTICAL_BODY.x_min


def test_placed_fields_do_not_overlap_body() -> None:
    specs = [FieldSpec("Reference", "R1"), FieldSpec("Value", "100nF")]
    placements = autoplace_fields(VERTICAL_BODY, VERTICAL_PINS, [VERTICAL_BODY], specs)
    for spec, placement in zip(specs, placements, strict=True):
        box = placement.text_field(spec.text, spec.font_mm).box()
        assert box.intersection_area(VERTICAL_BODY) == 0.0


def test_fields_move_off_a_blocked_side() -> None:
    # Block the right side with a big obstacle; placer should choose another side.
    specs = [FieldSpec("Reference", "R1"), FieldSpec("Value", "10k")]
    right_obstacle = Box(1.0, -10.0, 30.0, 10.0)
    placements = autoplace_fields(VERTICAL_BODY, VERTICAL_PINS, [right_obstacle], specs)
    # The right side is the default preference but is now blocked, so the chosen
    # placements must not sit inside the obstacle.
    for spec, placement in zip(specs, placements, strict=True):
        box = placement.text_field(spec.text, spec.font_mm).box()
        assert box.intersection_area(right_obstacle) == 0.0


def test_empty_field_keeps_one_to_one_mapping() -> None:
    specs = [FieldSpec("Reference", "R1"), FieldSpec("Value", "")]
    placements = autoplace_fields(VERTICAL_BODY, VERTICAL_PINS, [], specs)
    assert len(placements) == 2
    assert placements[1].name == "Value"
    # The empty field is anchored at the body centre and never displaces text.
    assert placements[1].x == VERTICAL_BODY.center[0]


def test_stacked_fields_are_separated() -> None:
    specs = [FieldSpec("Reference", "R1"), FieldSpec("Value", "10k")]
    placements = autoplace_fields(VERTICAL_BODY, VERTICAL_PINS, [], specs)
    assert placements[0].y != placements[1].y


def test_field_extent_merges_visible_fields() -> None:
    specs = [FieldSpec("Reference", "R1"), FieldSpec("Value", "10k")]
    placements = autoplace_fields(VERTICAL_BODY, VERTICAL_PINS, [], specs)
    extent = field_extent(specs, placements)
    assert extent is not None
    assert extent.width > 0.0
    assert extent.height > 0.0


def test_field_extent_none_when_all_empty() -> None:
    specs = [FieldSpec("Reference", ""), FieldSpec("Value", "")]
    placements = autoplace_fields(VERTICAL_BODY, VERTICAL_PINS, [], specs)
    assert field_extent(specs, placements) is None


def test_deterministic_output() -> None:
    specs = [FieldSpec("Reference", "U1"), FieldSpec("Value", "STM32")]
    first = autoplace_fields(VERTICAL_BODY, VERTICAL_PINS, [], specs)
    second = autoplace_fields(VERTICAL_BODY, VERTICAL_PINS, [], specs)
    assert first == second


def test_autoplace_applies_directional_justify_to_native_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Real KiCad fields must retain the placer's text anchor, not only its position."""
    from kicad_mcp.tools import schematic

    content = """
(kicad_sch
  (symbol (lib_id "Device:R") (at 50 50 0) (unit 1)
    (property "Reference" "R1"
      (at 52.27 49.111 0)
      (effects (font (size 1.27 1.27))))
    (property "Value" "100nF"
      (at 52.27 50.889 0)
      (effects (font (size 1.27 1.27)))))
)
"""
    body = Box(49.0, 47.5, 51.0, 52.5)
    pins = [(50.0, 46.2), (50.0, 53.8)]
    monkeypatch.setattr(schematic, "_symbol_body_and_pins", lambda _parsed: (body, pins))
    updated, changed = schematic._autoplace_visible_fields_for_ref(
        content, "R1", {"R1": body}, {"R1": (body, pins)}
    )

    assert changed
    assert updated.count("(justify left)") == 2
    assert '(symbol (lib_id "Device:R") (at 50 50 0) (unit 1)' in updated


def test_clear_side_preferred_to_unwired_but_obstructed_side() -> None:
    body = Box(-1, -1, 1, 1)
    obstacles = [Box(1, -10, 30, 10), Box(-20, -20, 20, -1), Box(-30, -10, -1, 10)]
    placements = autoplace_fields(body, [(0, 2)], obstacles, [FieldSpec("Value", "100nF")])
    assert placements[0].y > body.y_max


def test_rotated_locked_and_hidden_native_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    from kicad_mcp.tools import schematic

    content = """
(kicad_sch
  (symbol (lib_id "Device:R") (at 50 50 90) (unit 1)
    (property "Reference" "R1" (at 50 50 0)
      (do_not_autoplace yes) (effects (font (size 1.27 1.27))))
    (property "Value" "100nF" (at 50 50 0)
      (effects (font (size 1.27 1.27)) (hide yes))))
  (symbol (lib_id "Device:R") (at 80 80 90) (unit 1)
    (property "Reference" "R2" (at 80 80 0) (effects (font (size 1.27 1.27))))
    (property "Value" "10k" (at 80 80 0) (effects (font (size 1.27 1.27)))))
)
"""
    body = Box(49, 47.5, 51, 52.5)
    pins = [(50, 46.2), (50, 53.8)]
    body2 = Box(79, 77.5, 81, 82.5)
    pins2 = [(80, 76.2), (80, 83.8)]
    monkeypatch.setattr(schematic, "_symbol_body_and_pins", lambda _: (body, pins))
    bodies = {"R1": body, "R2": body2}
    pinmap = {"R1": (body, pins), "R2": (body2, pins2)}
    unchanged, changed = schematic._autoplace_visible_fields_for_ref(content, "R1", bodies, pinmap)
    assert not changed and unchanged == content
    updated, changed = schematic._autoplace_visible_fields_for_ref(content, "R2", bodies, pinmap)
    assert changed
    block = schematic._find_placed_symbol_block(updated, "R2")[0]
    import re

    assert len(re.findall(r"\(at [-\d.]+ [-\d.]+ 90\)", block)) == 3
    assert block.count("(justify right)") == 2


def test_field_only_transaction_preserves_wires_and_noop_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kicad_mcp.tools import schematic

    path = tmp_path / "native.kicad_sch"
    original = (
        b"(kicad_sch\r\n"
        b" (wire (pts (xy 12 10) (xy 10 10)) (stroke (width 0.2) (type default)))\r\n"
        b' (text "old" (at 20 20 0)))\r\n'
    )
    path.write_bytes(original)
    monkeypatch.setattr(schematic, "_record_schematic_visual_diff", lambda *args: None)
    monkeypatch.setattr(schematic, "clear_ttl_cache", lambda: None)
    schematic._transactional_write_fields(path, lambda current: current)
    assert path.read_bytes() == original
    schematic._transactional_write_fields(path, lambda current: current.replace('"old"', '"new"'))
    assert path.read_bytes() == original.replace(b'"old"', b'"new"')


def test_autoplace_uses_cached_body_and_real_wire_obstacles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kicad_mcp.models.visual_qa import parse_placed_symbols
    from kicad_mcp.tools import schematic

    content = """
(kicad_sch (paper "A4")
  (lib_symbols
    (symbol "Test:IC" (symbol "IC_0_1" (rectangle (start -5 -5) (end 5 5)))))
  (symbol (lib_id "Test:IC") (at 50 50 0) (unit 1)
    (property "Reference" "U1" (at 50 50 0) (effects (font (size 1.27 1.27))))
    (property "Value" "LongValue" (at 50 50 0) (effects (font (size 1.27 1.27)))))
  (wire (pts (xy 56 49.111) (xy 80 49.111)) (stroke (width 0) (type default)))
  (wire (pts (xy 56 50.889) (xy 80 50.889)) (stroke (width 0) (type default)))
)
"""
    path = tmp_path / "demo.kicad_sch"
    path.write_text(content, encoding="utf-8")
    monkeypatch.setattr(
        schematic,
        "parse_schematic_file",
        lambda _: {
            "symbols": [
                {
                    "reference": "U1",
                    "value": "LongValue",
                    "x": 50,
                    "y": 50,
                    "rotation": 0,
                    "lib_id": "Test:IC",
                }
            ]
        },
    )
    monkeypatch.setattr(schematic, "_symbol_body_and_pins", lambda _: (Box(49, 49, 51, 51), []))
    mutate, _, updated = schematic._build_autoplace_fields_mutator(path)
    result = mutate(content)
    assert updated == ["U1"]
    symbol = parse_placed_symbols(result)[0]
    assert all(not f.box().overlaps(symbol.body) for f in symbol.fields)
    assert all(not f.box().overlaps(Box(56, 48.8, 80, 51.2)) for f in symbol.fields)
    path.write_text(result, encoding="utf-8")
    repeat, _, repeated = schematic._build_autoplace_fields_mutator(path)
    assert repeat(result) == result
    assert repeated == []


def test_property_position_preserves_other_nodes_when_effects_precede_at() -> None:
    from kicad_mcp.tools import schematic

    block = (
        '(symbol (lib_id "Test:IC") (at 50 50 0) (property "Value" "IC" '
        "(effects (font (size 1.27 1.27))) (at 50 50 0) (do_not_autoplace no)))"
    )
    expected = (
        '(symbol (lib_id "Test:IC") (at 50 50 0) (property "Value" "IC" '
        "(effects (font (size 1.27 1.27)) (justify left)) (at 60 60 0) (do_not_autoplace no)))"
    )
    assert (
        schematic._set_property_position(block, "Value", 60, 60, 0, justify=frozenset({"left"}))
        == expected
    )


def test_autoplace_refuses_to_move_into_blocked_geometry(monkeypatch: pytest.MonkeyPatch) -> None:
    from kicad_mcp.tools import schematic

    content = """
(kicad_sch
  (symbol (lib_id "Device:R") (at 50 50 0)
    (property "Reference" "R1" (at 50 50 0) (effects (font (size 1.27 1.27))))
    (property "Value" "10k" (at 50 50 0) (effects (font (size 1.27 1.27)))))
)
"""
    body = Box(49, 47.5, 51, 52.5)
    pins = [(50.0, 46.2), (50.0, 53.8)]
    monkeypatch.setattr(schematic, "_symbol_body_and_pins", lambda _: (body, pins))
    assert schematic._autoplace_visible_fields_for_ref(
        content, "R1", {"R1": body}, {"R1": (body, pins)}, extra_obstacles=[Box(25, 25, 75, 75)]
    ) == (content, False)


def test_stale_field_placement_refuses_transaction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kicad_mcp.errors import SchematicWriteUnsafeError
    from kicad_mcp.tools import schematic

    content = '(kicad_sch (paper "A4"))'
    path = tmp_path / "board.kicad_sch"
    path.write_text(content, encoding="utf-8")
    monkeypatch.setattr(schematic, "parse_schematic_file", lambda _: {"symbols": []})
    mutator, _, _ = schematic._build_autoplace_fields_mutator(path)
    changed = content.replace("A4", "A3")
    path.write_text(changed, encoding="utf-8")
    with pytest.raises(SchematicWriteUnsafeError, match="changed while field placement"):
        schematic._transactional_write_fields(path, mutator)
    assert path.read_text(encoding="utf-8") == changed
