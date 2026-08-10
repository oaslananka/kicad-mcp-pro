from __future__ import annotations

from kicad_mcp.schematic.sheet_pins import SheetBlock, SheetPinRecord
from kicad_mcp.schematic.sheet_wiring import (
    StubPlacement,
    _find_label_collisions,  # internal: verifying exact overlap magnitude directly
    plan_sheet_wiring,
)

GRID = 1.27


def _pin(name: str, x: float, y: float, rotation: int) -> SheetPinRecord:
    return SheetPinRecord(
        name=name, pin_type="input", x_mm=x, y_mm=y, rotation=rotation, uuid=f"u-{name}"
    )


def _sheet(name: str, x: float, y: float, pins: tuple[SheetPinRecord, ...]) -> SheetBlock:
    return SheetBlock(
        name=name,
        filename=f"{name}.kicad_sch",
        origin=(x, y),
        size=(30.48, 20.32),
        pins=pins,
        start=0,
        end=1,
        size_span=(0, 1),
        at_span=(0, 1),
        pin_spans=tuple((0, 1) for _ in pins),
        pin_at_spans=tuple((0, 1) for _ in pins),
        instances_start=0,
    )


def _two_sheets() -> tuple[SheetBlock, SheetBlock]:
    left = _sheet("left", 0.0, 0.0, (_pin("NET", 30.48, 2.54, 0),))
    right = _sheet("right", 60.96, 0.0, (_pin("NET", 60.96, 2.54, 180),))
    return left, right


def test_a_right_edge_pin_stubs_rightwards_with_outward_justification() -> None:
    left, right = _two_sheets()

    plan = plan_sheet_wiring((left, right), wired_points=(), grid_mm=GRID)

    placement = next(p for p in plan.placements if p.x1_mm == 30.48)
    assert (placement.x2_mm, placement.y2_mm) == (33.02, 2.54)
    assert (placement.label_x_mm, placement.label_y_mm) == (33.02, 2.54)
    assert (placement.label_rotation, placement.label_justify) == (0, "left")
    assert placement.action == "add"


def test_a_left_edge_pin_stubs_leftwards() -> None:
    left, right = _two_sheets()

    plan = plan_sheet_wiring((left, right), wired_points=(), grid_mm=GRID)

    placement = next(p for p in plan.placements if p.x1_mm == 60.96)
    assert (placement.x2_mm, placement.y2_mm) == (58.42, 2.54)
    assert (placement.label_rotation, placement.label_justify) == (0, "right")


def test_top_and_bottom_pins_stub_vertically() -> None:
    sheet = _sheet("s", 0.0, 0.0, (_pin("UP", 10.16, 0.0, 90), _pin("DOWN", 12.7, 20.32, 270)))

    plan = plan_sheet_wiring((sheet,), wired_points=(), grid_mm=GRID)

    up = next(p for p in plan.placements if p.name == "UP")
    down = next(p for p in plan.placements if p.name == "DOWN")
    assert (up.x2_mm, up.y2_mm) == (10.16, -2.54)
    assert (down.x2_mm, down.y2_mm) == (12.7, 22.86)
    assert up.label_rotation == down.label_rotation == 90


def test_a_pin_that_already_has_a_wire_is_kept_not_duplicated() -> None:
    left, right = _two_sheets()

    plan = plan_sheet_wiring((left, right), wired_points=((30.48, 2.54),), grid_mm=GRID)

    kept = next(p for p in plan.placements if p.x1_mm == 30.48)
    assert kept.action == "keep"
    assert sum(1 for p in plan.placements if p.action == "add") == 1


def test_a_name_on_only_one_sheet_is_reported_as_an_orphan() -> None:
    left = _sheet("left", 0.0, 0.0, (_pin("LONELY", 30.48, 2.54, 0),))

    plan = plan_sheet_wiring((left,), wired_points=(), grid_mm=GRID)

    assert plan.orphans == ("LONELY",)
    assert plan.placements[0].action == "add"


def test_labels_that_would_overlap_are_reported_with_the_missing_room() -> None:
    left = _sheet("left", 0.0, 0.0, (_pin("SPI2_MOSI", 30.48, 2.54, 0),))
    right = _sheet("right", 40.64, 0.0, (_pin("SPI2_MOSI", 40.64, 2.54, 180),))

    plan = plan_sheet_wiring((left, right), wired_points=(), grid_mm=GRID)

    assert plan.collisions
    assert "SPI2_MOSI" in plan.collisions[0]
    assert any("sch_spread_sheets" in note for note in plan.notes)


def test_labels_at_different_heights_do_not_collide() -> None:
    left = _sheet("left", 0.0, 0.0, (_pin("SPI2_MOSI", 30.48, 2.54, 0),))
    right = _sheet("right", 40.64, 0.0, (_pin("SPI2_MOSI", 40.64, 12.7, 180),))

    plan = plan_sheet_wiring((left, right), wired_points=(), grid_mm=GRID)

    assert plan.collisions == ()


def test_every_overlapping_pair_is_reported_not_just_adjacent_ones() -> None:
    """A chain of three mutually overlapping labels needs all three pairs
    reported (A-B, B-C, and A-C). A left-to-right sweep that tracks only the
    single widest span seen so far moves its "reach" on to B once B's span
    exceeds A's, and never compares A against C again -- exhaustive pairwise
    comparison is what this test would catch a regression back to.
    """
    name = "SUPERLONGNAME1"  # 14 chars; width comfortably covers all three gaps
    a = _sheet("a", 0.0, 0.0, (_pin(name, 0.0, 2.54, 0),))
    b = _sheet("b", 0.0, 0.0, (_pin(name, 2.54, 2.54, 0),))
    c = _sheet("c", 0.0, 0.0, (_pin(name, 5.08, 2.54, 0),))

    plan = plan_sheet_wiring((a, b, c), wired_points=(), grid_mm=GRID)

    assert len(plan.collisions) == 3


def test_the_reported_overlap_is_the_true_intersection_not_the_full_span_diff() -> None:
    """A wide label that fully swallows a narrower one must report the
    narrow one's own width as the overlap, not the wide label's whole span.
    """
    text_height_mm = 100 / 6  # width = 10 * len(name) at this height, for round numbers below
    wide = StubPlacement(
        name="A" * 10,
        sheet_name="wide",
        x1_mm=0.0,
        y1_mm=0.0,
        x2_mm=0.0,
        y2_mm=0.0,
        label_x_mm=0.0,
        label_y_mm=2.54,
        label_rotation=0,
        label_justify="left",
        action="add",
    )
    narrow = StubPlacement(
        name="B",
        sheet_name="narrow",
        x1_mm=0.0,
        y1_mm=0.0,
        x2_mm=0.0,
        y2_mm=0.0,
        label_x_mm=10.0,
        label_y_mm=2.54,
        label_rotation=0,
        label_justify="left",
        action="add",
    )

    collisions, compared = _find_label_collisions((wide, narrow), text_height_mm)

    assert compared is True
    assert len(collisions) == 1
    assert "10.00 mm" in collisions[0]  # the narrow label's whole width, not the 90 mm span diff


def test_the_wire_start_is_the_pins_exact_position_even_off_grid() -> None:
    """KiCad connects only on exact coordinate equality: if x1/y1 were snapped
    instead of copied raw from the pin, the wire's start would sit next to the
    pin rather than on it, and the wire would touch nothing.
    """
    sheet = _sheet("s", 0.0, 0.0, (_pin("N", 30.48, 3.0, 0),))  # y=3.0 is off the 1.27 grid

    plan = plan_sheet_wiring((sheet,), wired_points=(), grid_mm=GRID)

    placement = plan.placements[0]
    assert (placement.x1_mm, placement.y1_mm) == (30.48, 3.0)


def test_only_the_stub_axis_of_the_far_end_is_snapped_to_grid() -> None:
    """The far end's coordinate along the stub's own direction is forced onto
    grid; the perpendicular coordinate is copied straight from the pin, even
    when that leaves it off-grid, so the stub stays a straight line out of the
    pin instead of jogging sideways to land on a grid point.
    """
    sheet = _sheet("s", 0.0, 0.0, (_pin("N", 30.48, 3.0, 0),))  # right edge: x is the stub axis

    plan = plan_sheet_wiring((sheet,), wired_points=(), grid_mm=GRID)

    placement = plan.placements[0]
    assert round(placement.x2_mm / GRID, 6) == round(placement.x2_mm / GRID)
    assert placement.y2_mm == 3.0


def test_an_off_grid_pin_gets_a_note_pointing_at_sch_align_to_grid() -> None:
    sheet = _sheet("s", 0.0, 0.0, (_pin("OFFGRID", 30.48, 3.0, 0),))

    plan = plan_sheet_wiring((sheet,), wired_points=(), grid_mm=GRID)

    assert any("OFFGRID" in note and "sch_align_to_grid" in note for note in plan.notes)


def test_an_existing_wire_at_an_off_grid_pins_exact_position_is_kept() -> None:
    sheet = _sheet("s", 0.0, 0.0, (_pin("N", 30.48, 3.0, 0),))

    plan = plan_sheet_wiring((sheet,), wired_points=((30.48, 3.0),), grid_mm=GRID)

    assert plan.placements[0].action == "keep"


def test_the_heuristic_note_appears_when_two_labels_share_a_row() -> None:
    left = _sheet("left", 0.0, 0.0, (_pin("SPI2_MOSI", 30.48, 2.54, 0),))
    right = _sheet("right", 40.64, 0.0, (_pin("SPI2_MOSI", 40.64, 2.54, 180),))

    plan = plan_sheet_wiring((left, right), wired_points=(), grid_mm=GRID)

    assert any("estimated text width" in note for note in plan.notes)


def test_the_heuristic_note_is_absent_for_a_singleton_row() -> None:
    left = _sheet("left", 0.0, 0.0, (_pin("LONELY", 30.48, 2.54, 0),))

    plan = plan_sheet_wiring((left,), wired_points=(), grid_mm=GRID)

    assert not any("estimated text width" in note for note in plan.notes)


def test_the_heuristic_note_is_absent_with_no_placements_at_all() -> None:
    plan = plan_sheet_wiring((), wired_points=(), grid_mm=GRID)

    assert not any("estimated text width" in note for note in plan.notes)


def test_a_vertical_label_note_appears_when_a_pin_is_on_the_top_or_bottom_edge() -> None:
    sheet = _sheet("s", 0.0, 0.0, (_pin("UP", 10.16, 0.0, 90),))

    plan = plan_sheet_wiring((sheet,), wired_points=(), grid_mm=GRID)

    assert any("Vertical labels" in note for note in plan.notes)


def test_no_vertical_label_note_when_every_pin_is_left_or_right() -> None:
    left, right = _two_sheets()

    plan = plan_sheet_wiring((left, right), wired_points=(), grid_mm=GRID)

    assert not any("Vertical labels" in note for note in plan.notes)


def test_the_plan_is_stable_across_runs() -> None:
    left, right = _two_sheets()
    first = plan_sheet_wiring((left, right), wired_points=(), grid_mm=GRID)

    points = tuple((p.x1_mm, p.y1_mm) for p in first.placements)
    second = plan_sheet_wiring((left, right), wired_points=points, grid_mm=GRID)

    assert {p.action for p in second.placements} == {"keep"}
