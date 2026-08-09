from __future__ import annotations

from dataclasses import replace

import pytest

from kicad_mcp.schematic.sheet_pins import (
    SheetPinPlacement,
    SheetPinPlan,
    SheetPinRecord,
    _splice,  # internal invariant (non-overlapping edit spans), tested directly below
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

ROOT_WITH_PIN_AFTER_INSTANCES = """(kicad_sch
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
\t\t(pin "VIN" input
\t\t\t(at 80.01 33.02 180)
\t\t\t(effects
\t\t\t\t(font
\t\t\t\t\t(size 1.27 1.27)
\t\t\t\t)
\t\t\t\t(justify left)
\t\t\t)
\t\t\t(uuid "bbbbbbbb-1111-2222-3333-444444444444")
\t\t)
\t)
)
"""
"""A hand-edited variant of ROOT: KiCad never writes a sheet's pins after its
``(instances ...)`` node, but nothing stops a human from doing so. This is the
single highest-risk path for ``apply_plan``'s splice arithmetic."""

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

    # This is the write path's entire reason to exist: everything outside the
    # sheet block must survive byte-for-byte, unlike a kicad_sch_api round trip
    # (which silently drops title_block comments). A substring check on one
    # comment is not enough to pin that down -- assert the full prefix and
    # suffix around the sheet block are untouched. The suffix's offset in
    # ``updated`` shifts by however much the sheet block grew or shrank, so
    # compare by length from the end rather than by ``sheet.end``.
    assert updated[: sheet.start] == ROOT[: sheet.start]
    tail = ROOT[sheet.end :]
    assert updated[len(updated) - len(tail) :] == tail


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


def test_apply_plan_relocates_a_pin_that_sits_after_instances() -> None:
    """KiCad never writes a sheet's pins after ``(instances ...)``, but a hand
    edit could. ``apply_plan`` must delete the misplaced pin from its original
    position and re-emit it in the canonical spot before ``(instances ...)``,
    healing the layout instead of duplicating the pin, losing it, or -- worse
    -- corrupting the surrounding text because the deletion and insertion spans
    were assumed disjoint without checking.
    """
    sheet = parse_sheet_blocks(ROOT_WITH_PIN_AFTER_INSTANCES)[0]
    assert sheet.pins == (
        SheetPinRecord(
            name="VIN",
            pin_type="input",
            x_mm=80.01,
            y_mm=33.02,
            rotation=180,
            uuid="bbbbbbbb-1111-2222-3333-444444444444",
        ),
    )
    assert sheet.instances_start is not None
    # This is the adversarial layout itself: the existing pin's span starts
    # strictly after the instances anchor, the opposite of what KiCad writes.
    assert sheet.pin_spans[0][0] > sheet.instances_start

    plan = plan_sheet_pins((("VIN", "input"),), sheet, grid_mm=GRID)

    updated = apply_plan(ROOT_WITH_PIN_AFTER_INSTANCES, sheet, plan)

    assert updated.count('(pin "VIN"') == 1
    assert updated.index('(pin "VIN"') < updated.index("(instances")

    reparsed = parse_sheet_blocks(updated)[0]
    assert reparsed.pins == (
        SheetPinRecord(
            name="VIN",
            pin_type="input",
            x_mm=80.01,
            y_mm=33.02,
            rotation=180,
            uuid="bbbbbbbb-1111-2222-3333-444444444444",
        ),
    )
    assert reparsed.instances_start is not None
    assert reparsed.pin_spans[0][0] < reparsed.instances_start


def test_splice_refuses_overlapping_edits() -> None:
    """``_splice`` replays edits in descending order of ``start``, which is
    only correct if the spans are pairwise non-overlapping. This is the
    precondition itself, exercised directly with fabricated overlapping spans
    rather than relying on finding a real KiCad file shaped like this.
    """
    sheet = parse_sheet_blocks(ROOT)[0]

    with pytest.raises(ValueError, match="02_mcu"):
        _splice(
            ROOT,
            sheet,
            [(sheet.start + 5, sheet.start + 15, "a"), (sheet.start + 10, sheet.start + 20, "b")],
        )
