from __future__ import annotations

from kicad_mcp.schematic.sheet_pins import SheetBlock, SheetPinRecord
from kicad_mcp.schematic.sheet_wiring import plan_sheet_wiring

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


def test_positions_are_snapped_to_the_grid() -> None:
    sheet = _sheet("s", 0.0, 0.3, (_pin("N", 30.48, 3.0, 0),))

    plan = plan_sheet_wiring((sheet,), wired_points=(), grid_mm=GRID)

    placement = plan.placements[0]
    for value in (placement.x2_mm, placement.y2_mm):
        assert round(value / GRID, 6) == round(value / GRID)


def test_the_plan_is_stable_across_runs() -> None:
    left, right = _two_sheets()
    first = plan_sheet_wiring((left, right), wired_points=(), grid_mm=GRID)

    points = tuple((p.x1_mm, p.y1_mm) for p in first.placements)
    second = plan_sheet_wiring((left, right), wired_points=points, grid_mm=GRID)

    assert {p.action for p in second.placements} == {"keep"}
