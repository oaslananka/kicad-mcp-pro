from __future__ import annotations

from kicad_mcp.schematic.sheet_pins import (
    SheetBlock,
    placement_on_edge,
    plan_sheet_pins,
)

GRID = 1.27


def _sheet(
    *,
    pins: tuple[tuple[str, str, str], ...] = (),
    origin: tuple[float, float] = (80.01, 30.48),
    size: tuple[float, float] = (30.48, 20.32),
) -> SheetBlock:
    return SheetBlock(
        name="02_mcu",
        filename="main_02_mcu.kicad_sch",
        origin=origin,
        size=size,
        pins=pins,
        start=0,
        end=1,
        size_span=(0, 1),
        pin_spans=tuple((0, 1) for _ in pins),
        instances_start=0,
    )


def test_inputs_go_left_and_everything_else_goes_right() -> None:
    labels = (
        ("I2C1_SDA", "bidirectional"),
        ("USB_DP", "input"),
        ("I2S_BCLK", "output"),
        ("SENSE", "passive"),
        ("HIZ", "tri_state"),
    )

    plan = plan_sheet_pins(labels, _sheet(), grid_mm=GRID)

    by_name = {p.name: p for p in plan.placements}
    assert by_name["USB_DP"].edge == "left"
    assert {by_name[n].edge for n in ("I2C1_SDA", "I2S_BCLK", "SENSE", "HIZ")} == {"right"}


def test_each_edge_is_alphabetical_and_pitched() -> None:
    labels = (("CHARLIE", "input"), ("alpha", "input"), ("Bravo", "input"))

    plan = plan_sheet_pins(labels, _sheet(), grid_mm=GRID)

    left = [p for p in plan.placements if p.edge == "left"]
    assert [p.name for p in left] == ["alpha", "Bravo", "CHARLIE"]
    assert [p.y_mm for p in left] == [33.02, 35.56, 38.1]


def test_left_pins_sit_on_the_left_border_and_face_inward() -> None:
    plan = plan_sheet_pins((("IN", "input"), ("OUT", "output")), _sheet(), grid_mm=GRID)

    left = next(p for p in plan.placements if p.edge == "left")
    right = next(p for p in plan.placements if p.edge == "right")
    assert (left.x_mm, left.rotation, left.justify) == (80.01, 180, "left")
    assert (right.x_mm, right.rotation, right.justify) == (110.49, 0, "right")


def test_height_grows_to_the_busier_edge_and_never_shrinks() -> None:
    labels = tuple((f"IN{index:02d}", "input") for index in range(17))

    plan = plan_sheet_pins(labels, _sheet(), grid_mm=GRID)

    # 17 pins: 2 * 2.54 margin + 16 * 2.54 pitch = 45.72
    assert plan.size == (30.48, 45.72)


def test_width_grows_only_when_the_two_text_columns_would_collide() -> None:
    labels = (("A_VERY_LONG_INPUT_NAME_HERE", "input"), ("A_VERY_LONG_OUTPUT_NAME", "output"))

    plan = plan_sheet_pins(labels, _sheet(), grid_mm=GRID)

    assert plan.size[0] > 30.48
    assert plan.size[0] % GRID == 0.0


def test_size_is_untouched_when_everything_already_fits() -> None:
    plan = plan_sheet_pins((("IN", "input"),), _sheet(), grid_mm=GRID)

    assert plan.size == (30.48, 20.32)


def test_positions_are_snapped_to_the_schematic_grid() -> None:
    labels = (("IN", "input"),)

    plan = plan_sheet_pins(labels, _sheet(origin=(80.01, 30.0)), grid_mm=GRID)

    placement = plan.placements[0]
    assert round(placement.y_mm / GRID, 6) == round(placement.y_mm / GRID)


def test_existing_pin_with_the_same_type_is_kept_with_its_uuid() -> None:
    sheet = _sheet(pins=(("IN", "input", "aaaa-bbbb"),))

    plan = plan_sheet_pins((("IN", "input"),), sheet, grid_mm=GRID)

    assert plan.placements[0].action == "keep"
    assert plan.placements[0].uuid == "aaaa-bbbb"


def test_existing_pin_with_a_different_type_is_retyped_to_match_the_child() -> None:
    sheet = _sheet(pins=(("IN", "input", "aaaa-bbbb"),))

    plan = plan_sheet_pins((("IN", "output"),), sheet, grid_mm=GRID)

    placement = plan.placements[0]
    assert (placement.action, placement.pin_type, placement.edge) == ("retype", "output", "right")
    assert placement.uuid == "aaaa-bbbb"


def test_a_new_pin_carries_an_empty_uuid_for_the_caller_to_fill() -> None:
    plan = plan_sheet_pins((("IN", "input"),), _sheet(), grid_mm=GRID)

    assert plan.placements[0].action == "add"
    assert plan.placements[0].uuid == ""


def test_a_pin_without_a_matching_label_is_reported_but_never_dropped() -> None:
    sheet = _sheet(pins=(("STALE", "output", "cccc"),))

    plan = plan_sheet_pins((("IN", "input"),), sheet, grid_mm=GRID)

    assert plan.orphans == ("STALE",)
    assert {p.name for p in plan.placements} == {"IN", "STALE"}


def test_a_name_with_two_shapes_takes_the_first_and_reports_the_conflict() -> None:
    labels = (("BUS", "input"), ("BUS", "output"))

    plan = plan_sheet_pins(labels, _sheet(), grid_mm=GRID)

    assert plan.conflicts == ("BUS",)
    assert plan.placements[0].pin_type == "input"


def test_an_unknown_shape_falls_back_to_input() -> None:
    plan = plan_sheet_pins((("ODD", "nonsense"),), _sheet(), grid_mm=GRID)

    assert plan.placements[0].pin_type == "input"


def test_without_growth_the_overflowing_names_are_reported() -> None:
    labels = tuple((f"IN{index:02d}", "input") for index in range(20))

    plan = plan_sheet_pins(labels, _sheet(), grid_mm=GRID, grow_sheet=False)

    # 20.32 tall, 2.54 margins, 2.54 pitch -> capacity 7
    assert len(plan.overflow) == 13
    assert plan.size == (30.48, 20.32)


def test_an_off_grid_origin_is_reported_because_x_cannot_be_fixed() -> None:
    plan = plan_sheet_pins((("IN", "input"),), _sheet(origin=(80.0, 30.48)), grid_mm=GRID)

    assert any("grid" in note for note in plan.notes)


def test_the_plan_is_stable_across_runs() -> None:
    labels = (("B", "input"), ("A", "output"))
    first = plan_sheet_pins(labels, _sheet(), grid_mm=GRID)
    sheet = _sheet(
        pins=tuple((p.name, p.pin_type, "uuid-" + p.name) for p in first.placements),
        size=first.size,
    )

    second = plan_sheet_pins(labels, sheet, grid_mm=GRID)

    assert [(p.name, p.edge, p.x_mm, p.y_mm) for p in second.placements] == [
        (p.name, p.edge, p.x_mm, p.y_mm) for p in first.placements
    ]
    assert {p.action for p in second.placements} == {"keep"}


def test_placement_on_edge_mirrors_the_library_edge_semantics() -> None:
    sheet = _sheet()

    right = placement_on_edge(sheet, "R", "input", "right", 5.08, "u1")
    bottom = placement_on_edge(sheet, "B", "input", "bottom", 5.08, "u2")
    left = placement_on_edge(sheet, "L", "input", "left", 5.08, "u3")
    top = placement_on_edge(sheet, "T", "input", "top", 5.08, "u4")

    assert (right.x_mm, right.y_mm, right.rotation, right.justify) == (110.49, 35.56, 0, "right")
    assert (bottom.x_mm, bottom.y_mm, bottom.rotation, bottom.justify) == (85.09, 50.8, 270, "left")
    assert (left.x_mm, left.y_mm, left.rotation, left.justify) == (80.01, 45.72, 180, "left")
    assert (top.x_mm, top.y_mm, top.rotation, top.justify) == (85.09, 30.48, 90, "right")
