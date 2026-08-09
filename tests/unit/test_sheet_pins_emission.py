from __future__ import annotations

from dataclasses import replace

import pytest

from kicad_mcp.schematic.sheet_pins import (
    SheetPinPlacement,
    SheetPinPlan,
    apply_plan,
    insert_pin,
    parse_sheet_blocks,
    plan_sheet_pins,
    sheet_pin_block,
)


def _stamp(plan: SheetPinPlan) -> SheetPinPlan:
    """Fill empty UUIDs the way the service does, so emission can be tested."""
    placements = tuple(
        placement if placement.uuid else replace(placement, uuid=f"uuid-{index}")
        for index, placement in enumerate(plan.placements)
    )
    return replace(plan, placements=placements)


ROOT = """(kicad_sch
\t(title_block
\t\t(title "main")
\t\t(comment 1 "keep me")
\t)
\t(sheet
\t\t(at 80.01 30.48)
\t\t(size 30.48 20.32)
\t\t(uuid "24299bd7-4c16-4845-810e-d9ee5fee95c1")
\t\t(property "Sheetname" "02_mcu"
\t\t\t(at 80.01 29.77 0)
\t\t)
\t\t(property "Sheetfile" "main_02_mcu.kicad_sch"
\t\t\t(at 80.01 51.38 0)
\t\t)
\t\t(instances
\t\t\t(project "main"
\t\t\t\t(path "/9645" (page "2"))
\t\t\t)
\t\t)
\t)
)
"""

GRID = 1.27


def _placement(**overrides: object) -> SheetPinPlacement:
    base = {
        "name": "I2S_BCLK",
        "pin_type": "output",
        "edge": "right",
        "x_mm": 110.49,
        "y_mm": 33.02,
        "rotation": 0,
        "justify": "right",
        "uuid": "aaaaaaaa-1111-2222-3333-444444444444",
        "action": "add",
    }
    base.update(overrides)
    return SheetPinPlacement(**base)  # type: ignore[arg-type]


def test_sheet_pin_block_matches_the_kicad_layout() -> None:
    assert sheet_pin_block(_placement()) == (
        '\t\t(pin "I2S_BCLK" output\n'
        "\t\t\t(at 110.49 33.02 0)\n"
        "\t\t\t(effects\n"
        "\t\t\t\t(font\n"
        "\t\t\t\t\t(size 1.27 1.27)\n"
        "\t\t\t\t)\n"
        "\t\t\t\t(justify right)\n"
        "\t\t\t)\n"
        '\t\t\t(uuid "aaaaaaaa-1111-2222-3333-444444444444")\n'
        "\t\t)\n"
    )


def test_sheet_pin_block_escapes_quotes_in_the_name() -> None:
    assert '(pin "A\\"B" output' in sheet_pin_block(_placement(name='A"B'))


def test_sheet_pin_block_trims_trailing_zeros() -> None:
    assert "(at 110.49 33 0)" in sheet_pin_block(_placement(y_mm=33.0))


def test_apply_plan_inserts_pins_before_the_instances_node() -> None:
    sheet = parse_sheet_blocks(ROOT)[0]
    plan = _stamp(plan_sheet_pins((("VIN", "input"),), sheet, grid_mm=GRID))

    updated = apply_plan(ROOT, sheet, plan)

    assert updated.index('(pin "VIN"') < updated.index("(instances")
    assert '(comment 1 "keep me")' in updated


def test_apply_plan_rewrites_the_sheet_size() -> None:
    sheet = parse_sheet_blocks(ROOT)[0]
    labels = tuple((f"IN{index:02d}", "input") for index in range(17))
    plan = plan_sheet_pins(labels, sheet, grid_mm=GRID)
    stamped = _stamp(plan)

    updated = apply_plan(ROOT, sheet, stamped)

    assert "(size 30.48 45.72)" in updated
    assert "(size 1.27 1.27)" in updated  # font sizes untouched


def test_apply_plan_replaces_rather_than_duplicates_existing_pins() -> None:
    sheet = parse_sheet_blocks(ROOT)[0]
    first = apply_plan(
        ROOT, sheet, _stamp(plan_sheet_pins((("VIN", "input"),), sheet, grid_mm=GRID))
    )

    reparsed = parse_sheet_blocks(first)[0]
    second = apply_plan(
        first, reparsed, _stamp(plan_sheet_pins((("VIN", "input"),), reparsed, grid_mm=GRID))
    )

    assert second.count('(pin "VIN"') == 1


def test_apply_plan_is_idempotent_on_the_second_run() -> None:
    sheet = parse_sheet_blocks(ROOT)[0]
    first = apply_plan(
        ROOT, sheet, _stamp(plan_sheet_pins((("VIN", "input"),), sheet, grid_mm=GRID))
    )

    reparsed = parse_sheet_blocks(first)[0]
    plan = plan_sheet_pins((("VIN", "input"),), reparsed, grid_mm=GRID)
    assert all(placement.uuid for placement in plan.placements)
    second = apply_plan(first, reparsed, plan)

    assert second == first


def test_apply_plan_refuses_a_sheet_without_an_instances_anchor() -> None:
    text = ROOT.replace("(instances", "(nothing")
    sheet = parse_sheet_blocks(text)[0]
    plan = plan_sheet_pins((("VIN", "input"),), sheet, grid_mm=GRID)

    with pytest.raises(ValueError, match="instances"):
        apply_plan(text, sheet, _stamp(plan))


def test_insert_pin_adds_one_pin_and_leaves_the_size_alone() -> None:
    sheet = parse_sheet_blocks(ROOT)[0]

    updated = insert_pin(ROOT, sheet, _placement(name="MANUAL"))

    assert '(pin "MANUAL"' in updated
    assert "(size 30.48 20.32)" in updated


def test_insert_pin_rejects_a_duplicate_name() -> None:
    sheet = parse_sheet_blocks(ROOT)[0]
    once = insert_pin(ROOT, sheet, _placement(name="MANUAL"))
    reparsed = parse_sheet_blocks(once)[0]

    with pytest.raises(ValueError, match="MANUAL"):
        insert_pin(once, reparsed, _placement(name="MANUAL"))
