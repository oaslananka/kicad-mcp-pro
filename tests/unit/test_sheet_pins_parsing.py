from __future__ import annotations

from typing import get_args

import pytest

from kicad_mcp.models.schematic import SheetEdge, SheetPinType
from kicad_mcp.schematic.sheet_pins import (
    EDGES,
    PIN_TYPES,
    SheetPinRecord,
    edge_for_rotation,
    parse_hierarchical_labels,
    parse_sheet_blocks,
    parse_skipped_sheet_blocks,
)

SHEET_BLOCK = """(kicad_sch
\t(sheet
\t\t(at 30.48 90.17)
\t\t(size 30.48 20.32)
\t\t(fill
\t\t\t(color 0 0 0 0)
\t\t)
\t\t(uuid "24299bd7-4c16-4845-810e-d9ee5fee95c1")
\t\t(property "Sheetname" "05_audio"
\t\t\t(at 30.48 89.4584 0)
\t\t\t(effects
\t\t\t\t(font
\t\t\t\t\t(size 1.27 1.27)
\t\t\t\t)
\t\t\t)
\t\t)
\t\t(property "Sheetfile" "main_05_audio.kicad_sch"
\t\t\t(at 30.48 111.0746 0)
\t\t)
\t\t(instances
\t\t\t(project "main"
\t\t\t\t(path "/96451635-9025-4257-b58e-c68f0fc02308"
\t\t\t\t\t(page "5")
\t\t\t\t)
\t\t\t)
\t\t)
\t)
\t(sheet_instances
\t\t(path "/" (page "1"))
\t)
)
"""


def test_parse_sheet_blocks_reads_geometry_and_identity() -> None:
    blocks = parse_sheet_blocks(SHEET_BLOCK)

    assert len(blocks) == 1
    block = blocks[0]
    assert block.name == "05_audio"
    assert block.filename == "main_05_audio.kicad_sch"
    assert block.origin == (30.48, 90.17)
    assert block.size == (30.48, 20.32)
    assert block.pins == ()


def test_parse_sheet_blocks_ignores_the_font_size_node() -> None:
    # (size 1.27 1.27) inside (effects (font ...)) must not win over the
    # sheet's own (size 30.48 20.32).
    block = parse_sheet_blocks(SHEET_BLOCK)[0]
    assert block.size == (30.48, 20.32)


def test_parse_sheet_blocks_ignores_sheet_instances() -> None:
    assert len(parse_sheet_blocks(SHEET_BLOCK)) == 1


def test_parse_sheet_blocks_spans_address_the_real_text() -> None:
    block = parse_sheet_blocks(SHEET_BLOCK)[0]

    assert SHEET_BLOCK[block.start : block.end].startswith("(sheet\n")
    assert SHEET_BLOCK[block.start : block.end].endswith(")")
    start, end = block.size_span
    assert SHEET_BLOCK[start:end] == "(size 30.48 20.32)"
    assert SHEET_BLOCK[block.instances_start :].startswith("(instances")


def test_parse_sheet_blocks_reads_existing_pins_with_uuids() -> None:
    text = SHEET_BLOCK.replace(
        "\t\t(instances\n",
        '\t\t(pin "I2S_BCLK" output\n'
        "\t\t\t(at 60.96 92.71 0)\n"
        "\t\t\t(effects\n"
        "\t\t\t\t(font\n"
        "\t\t\t\t\t(size 1.27 1.27)\n"
        "\t\t\t\t)\n"
        "\t\t\t\t(justify right)\n"
        "\t\t\t)\n"
        '\t\t\t(uuid "aaaaaaaa-1111-2222-3333-444444444444")\n'
        "\t\t)\n"
        "\t\t(instances\n",
        1,
    )

    block = parse_sheet_blocks(text)[0]

    assert block.pins == (
        SheetPinRecord(
            name="I2S_BCLK",
            pin_type="output",
            x_mm=60.96,
            y_mm=92.71,
            rotation=0,
            uuid="aaaaaaaa-1111-2222-3333-444444444444",
        ),
    )
    start, end = block.pin_spans[0]
    # The span covers whole lines, so deleting it leaves no orphan indentation.
    assert text[start:end].startswith('\t\t(pin "I2S_BCLK"')
    assert text[start:end].endswith("\t\t)\n")


def test_edge_for_rotation_maps_the_four_kicad_rotations() -> None:
    assert edge_for_rotation(0) == "right"
    assert edge_for_rotation(90) == "top"
    assert edge_for_rotation(180) == "left"
    assert edge_for_rotation(270) == "bottom"
    assert edge_for_rotation(45) is None


def test_parse_hierarchical_labels_keeps_file_order_and_shape() -> None:
    text = (
        '(hierarchical_label "I2S_BCLK"\n\t(shape output)\n\t(at 1 2 0)\n)\n'
        '(hierarchical_label "I2C1_SDA"\n\t(shape bidirectional)\n\t(at 3 4 0)\n)\n'
    )

    assert parse_hierarchical_labels(text) == (
        ("I2S_BCLK", "output"),
        ("I2C1_SDA", "bidirectional"),
    )


def test_parse_hierarchical_labels_defaults_a_missing_shape_to_input() -> None:
    text = '(hierarchical_label "NO_SHAPE"\n\t(at 1 2 0)\n)\n'

    assert parse_hierarchical_labels(text) == (("NO_SHAPE", "input"),)


def test_parse_hierarchical_labels_ignores_other_label_kinds() -> None:
    text = '(label "LOCAL" (at 1 2 0))\n(global_label "GLOBAL" (shape input) (at 3 4 0))\n'

    assert parse_hierarchical_labels(text) == ()


def test_parse_hierarchical_labels_unescapes_quoted_names() -> None:
    text = '(hierarchical_label "A\\"B"\n\t(shape input)\n)\n'

    assert parse_hierarchical_labels(text) == (('A"B', "input"),)


def test_pin_types_are_the_kicad_vocabulary() -> None:
    assert PIN_TYPES == ("input", "output", "bidirectional", "tri_state", "passive")


def test_the_validated_literals_match_the_runtime_tuples() -> None:
    """The same vocabulary is declared twice -- keep the two copies identical.

    ``models.schematic`` validates the tool arguments against a ``Literal`` and
    ``sheet_pins`` checks them again at runtime against a tuple. Nothing else
    ties the two together, so a value added to one and not the other would be
    accepted at the boundary and rejected inside, or the reverse.
    """
    assert get_args(SheetPinType) == PIN_TYPES
    assert get_args(SheetEdge) == EDGES


@pytest.mark.parametrize("text", ["", "(kicad_sch\n)\n"])
def test_parse_sheet_blocks_tolerates_documents_without_sheets(text: str) -> None:
    assert parse_sheet_blocks(text) == ()


def test_parse_sheet_blocks_ignores_a_parenthesis_inside_a_property_string() -> None:
    # A stray ")" inside the quoted Sheetname value must not be mistaken for
    # the real closing parenthesis of the (property ...) node: the scanner is
    # string-aware, so it should keep tracking depth correctly and still find
    # the sheet's true boundaries and its sibling Sheetfile property.
    text = SHEET_BLOCK.replace('"05_audio"', '"05_audio)"', 1)

    blocks = parse_sheet_blocks(text)

    assert len(blocks) == 1
    block = blocks[0]
    assert block.name == "05_audio)"
    assert block.filename == "main_05_audio.kicad_sch"
    assert text[block.start : block.end].startswith("(sheet\n")
    assert text[block.start : block.end].endswith(")")
    start, end = block.size_span
    assert text[start:end] == "(size 30.48 20.32)"


def test_parse_sheet_blocks_skips_an_unbalanced_block_without_raising() -> None:
    # A truncated document: a second (sheet ...) block never closes. The
    # parser must skip it via its ValueError/continue path rather than raise,
    # while still returning the earlier, well-formed block.
    truncated = (
        SHEET_BLOCK + "\t(sheet\n"
        "\t\t(at 60.96 90.17)\n"
        "\t\t(size 30.48 20.32)\n"
        '\t\t(property "Sheetname" "06_truncated"\n'
        "\t\t\t(at 60.96 89.4584 0)\n"
    )

    blocks = parse_sheet_blocks(truncated)

    assert len(blocks) == 1
    assert blocks[0].name == "05_audio"


def test_parse_sheet_blocks_skips_a_block_whose_number_has_two_decimal_points() -> None:
    # "80.0.1" is not a number. Matching it as one lets float() raise straight
    # out of parse_sheet_blocks, escaping every tool entry point and breaking
    # the function's documented contract that an unusable block is skipped.
    text = SHEET_BLOCK.replace("(at 30.48 90.17)", "(at 80.0.1 90.17)", 1)

    assert parse_sheet_blocks(text) == ()

    skipped = parse_skipped_sheet_blocks(text)
    assert len(skipped) == 1
    assert skipped[0].name == "05_audio"
    assert "position" in skipped[0].reason


def test_parse_sheet_blocks_skips_a_pin_position_with_two_decimal_points() -> None:
    # Same defect one level down: a malformed (at ...) inside a (pin ...) node
    # must degrade to the zero fallback, not raise.
    text = SHEET_BLOCK.replace(
        "\t\t(instances\n",
        '\t\t(pin "BROKEN" input\n\t\t\t(at 1.2.3 4.0 0)\n\t\t\t(uuid "u")\n\t\t)\n'
        "\t\t(instances\n",
        1,
    )

    blocks = parse_sheet_blocks(text)

    assert len(blocks) == 1
    assert blocks[0].pins == (
        SheetPinRecord(name="BROKEN", pin_type="input", x_mm=0.0, y_mm=0.0, rotation=0, uuid="u"),
    )


def test_parse_skipped_sheet_blocks_names_a_sheet_without_a_size() -> None:
    text = SHEET_BLOCK.replace("\t\t(size 30.48 20.32)\n", "", 1)

    assert parse_sheet_blocks(text) == ()

    skipped = parse_skipped_sheet_blocks(text)
    assert len(skipped) == 1
    assert skipped[0].name == "05_audio"
    assert "size" in skipped[0].reason


def test_parse_skipped_sheet_blocks_reports_an_unnamed_block() -> None:
    text = SHEET_BLOCK.replace('"Sheetname"', '"Sheetnam"', 1)

    skipped = parse_skipped_sheet_blocks(text)

    assert len(skipped) == 1
    assert skipped[0].name == ""
    assert "Sheetname" in skipped[0].reason


def test_parse_skipped_sheet_blocks_is_empty_for_a_healthy_document() -> None:
    assert parse_skipped_sheet_blocks(SHEET_BLOCK) == ()
