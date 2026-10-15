"""Unit tests for symbol text-field auto-placement."""

from __future__ import annotations

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
