from __future__ import annotations

import pytest

from kicad_mcp.schematic.sheet_pins import (
    PIN_TYPES,
    parse_hierarchical_labels,
    parse_sheet_blocks,
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

    assert block.pins == (("I2S_BCLK", "output", "aaaaaaaa-1111-2222-3333-444444444444"),)
    start, end = block.pin_spans[0]
    # The span covers whole lines, so deleting it leaves no orphan indentation.
    assert text[start:end].startswith('\t\t(pin "I2S_BCLK"')
    assert text[start:end].endswith("\t\t)\n")


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


@pytest.mark.parametrize("text", ["", "(kicad_sch\n)\n"])
def test_parse_sheet_blocks_tolerates_documents_without_sheets(text: str) -> None:
    assert parse_sheet_blocks(text) == ()
