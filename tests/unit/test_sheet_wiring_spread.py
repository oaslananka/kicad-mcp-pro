from __future__ import annotations

from kicad_mcp.schematic.sheet_pins import SheetBlock, SheetPinRecord
from kicad_mcp.schematic.sheet_wiring import (
    PAPER_WIDTHS_MM,
    group_columns,
    plan_spread,
)

GRID = 1.27


def _pin(name: str, x: float, y: float, rotation: int) -> SheetPinRecord:
    return SheetPinRecord(
        name=name, pin_type="input", x_mm=x, y_mm=y, rotation=rotation, uuid=f"u-{name}"
    )


def _sheet(
    name: str,
    x: float,
    y: float,
    w: float = 30.48,
    h: float = 20.32,
    pins: tuple[SheetPinRecord, ...] = (),
) -> SheetBlock:
    return SheetBlock(
        name=name,
        filename=f"{name}.kicad_sch",
        origin=(x, y),
        size=(w, h),
        pins=pins,
        start=0,
        end=1,
        size_span=(0, 1),
        at_span=(0, 1),
        pin_spans=tuple((0, 1) for _ in pins),
        pin_at_spans=tuple((0, 1) for _ in pins),
        instances_start=0,
    )


def test_sheets_with_overlapping_x_spans_form_one_column() -> None:
    sheets = (
        _sheet("a", 30.48, 30.48),
        _sheet("b", 30.48, 90.17),
        _sheet("c", 80.01, 30.48),
    )

    columns = group_columns(sheets)

    assert [sorted(c.sheet_names) for c in columns] == [["a", "b"], ["c"]]


def test_a_gap_that_already_fits_produces_no_shift() -> None:
    left = _sheet("left", 0.0, 0.0, pins=(_pin("A", 30.48, 2.54, 0),))
    right = _sheet("right", 80.01, 0.0, pins=(_pin("A", 80.01, 2.54, 180),))

    plan = plan_spread((left, right), attached={}, grid_mm=GRID, margin_mm=0.0)

    assert plan.shifts == ()
    assert plan.overflow_mm == 0.0


def test_a_tight_gap_shifts_the_right_column_by_a_whole_grid_step() -> None:
    # 9-char names both sides: 2*2.54 stub + 2*6.858 text = 18.796 needed.
    left = _sheet("left", 0.0, 0.0, pins=(_pin("SPI2_MOSI", 30.48, 2.54, 0),))
    right = _sheet("right", 48.26, 0.0, pins=(_pin("SPI2_MOSI", 48.26, 2.54, 180),))

    plan = plan_spread((left, right), attached={}, grid_mm=GRID, margin_mm=2.54)

    assert [s.sheet_names for s in plan.shifts] == [("right",)]
    shift = plan.shifts[0].dx_mm
    assert shift > 0
    assert round(shift / GRID, 6) == round(shift / GRID)
    assert (48.26 + shift) - 30.48 >= 2 * 2.54 + 2 * 6.858 + 2.54


def test_the_requirement_comes_from_the_facing_names_not_the_longest() -> None:
    # The long name is on the LEFT edge of the left sheet, so it faces nothing.
    left = _sheet(
        "left",
        0.0,
        0.0,
        pins=(_pin("A_VERY_LONG_NAME", 0.0, 2.54, 180), _pin("X", 30.48, 2.54, 0)),
    )
    right = _sheet("right", 60.96, 0.0, pins=(_pin("Y", 60.96, 2.54, 180),))

    plan = plan_spread((left, right), attached={}, grid_mm=GRID, margin_mm=2.54)

    assert plan.shifts == ()


def test_shifts_accumulate_across_three_columns() -> None:
    a = _sheet("a", 0.0, 0.0, pins=(_pin("SPI2_MOSI", 30.48, 2.54, 0),))
    b = _sheet(
        "b",
        48.26,
        0.0,
        pins=(_pin("SPI2_MOSI", 48.26, 2.54, 180), _pin("SPI2_MISO", 78.74, 2.54, 0)),
    )
    c = _sheet("c", 96.52, 0.0, pins=(_pin("SPI2_MISO", 96.52, 2.54, 180),))

    plan = plan_spread((a, b, c), attached={}, grid_mm=GRID, margin_mm=2.54)

    by_name = {s.sheet_names: s.dx_mm for s in plan.shifts}
    assert by_name[("b",)] > 0
    assert by_name[("c",)] > by_name[("b",)]


def test_a_sheet_with_an_attached_wire_blocks_the_whole_plan() -> None:
    left = _sheet("left", 0.0, 0.0, pins=(_pin("SPI2_MOSI", 30.48, 2.54, 0),))
    right = _sheet("right", 48.26, 0.0, pins=(_pin("SPI2_MOSI", 48.26, 2.54, 180),))

    plan = plan_spread(
        (left, right), attached={"right": ("SPI2_MOSI",)}, grid_mm=GRID, margin_mm=2.54
    )

    assert plan.shifts == ()
    assert "right" in plan.blocked


def test_a_shift_past_the_page_edge_is_reported_not_applied() -> None:
    # w=200.0 was the brief's original value, but it does not overflow an A4
    # page: right_edge = 48.26 + 200.0 + 3.81 (the required shift) = 252.07 mm,
    # which is under the 287.0 mm usable width (297.0 - PAGE_MARGIN_MM). 250.0
    # is the smallest round width that does overflow: right_edge = 302.07 mm.
    left = _sheet("left", 0.0, 0.0, pins=(_pin("SPI2_MOSI", 30.48, 2.54, 0),))
    right = _sheet("right", 48.26, 0.0, w=250.0, pins=(_pin("SPI2_MOSI", 48.26, 2.54, 180),))

    plan = plan_spread(
        (left, right),
        attached={},
        grid_mm=GRID,
        margin_mm=2.54,
        page_width_mm=PAPER_WIDTHS_MM["A4"],
    )

    assert plan.shifts == ()
    assert plan.overflow_mm > 0


def test_an_unknown_paper_size_skips_the_check_and_says_so() -> None:
    left = _sheet("left", 0.0, 0.0, pins=(_pin("SPI2_MOSI", 30.48, 2.54, 0),))
    right = _sheet("right", 48.26, 0.0, pins=(_pin("SPI2_MOSI", 48.26, 2.54, 180),))

    plan = plan_spread((left, right), attached={}, grid_mm=GRID, margin_mm=2.54, page_width_mm=None)

    assert plan.shifts != ()
    assert any("page" in note.casefold() for note in plan.notes)


def test_an_explicit_min_gap_overrides_the_derivation() -> None:
    left = _sheet("left", 0.0, 0.0, pins=(_pin("A", 30.48, 2.54, 0),))
    right = _sheet("right", 60.96, 0.0, pins=(_pin("A", 60.96, 2.54, 180),))

    plan = plan_spread((left, right), attached={}, grid_mm=GRID, margin_mm=0.0, min_gap_mm=50.0)

    assert plan.shifts[0].dx_mm >= 50.0 - (60.96 - 30.48)


def test_the_heuristic_is_disclosed_whenever_it_drove_a_shift() -> None:
    left = _sheet("left", 0.0, 0.0, pins=(_pin("SPI2_MOSI", 30.48, 2.54, 0),))
    right = _sheet("right", 48.26, 0.0, pins=(_pin("SPI2_MOSI", 48.26, 2.54, 180),))

    plan = plan_spread((left, right), attached={}, grid_mm=GRID, margin_mm=2.54)

    assert any("heuristic" in note.casefold() for note in plan.notes)
