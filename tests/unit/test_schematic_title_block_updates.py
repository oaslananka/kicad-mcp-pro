"""Regressions for byte-stable KiCad schematic title-block updates."""

from __future__ import annotations

import pytest

from kicad_mcp.tools.schematic import _apply_title_block_updates, _new_title_block_text


@pytest.mark.parametrize(
    ("content", "updates", "expected_fragments"),
    [
        (
            '(kicad_sch\n\t(paper "A4")\n\t(sheet_instances)\n)',
            {"title": 'Sensor "A"', "comment2": "proto\\draft", "rev": "B"},
            ['(title "Sensor \\"A\\"")', '(rev "B")', '(comment 2 "proto\\\\draft")'],
        ),
        (
            "(kicad_sch\n\t(sheet_instances)\n)",
            {"comment1": "notes", "date": "2026-10-23"},
            ['(comment 1 "notes")', '(date "2026-10-23")'],
        ),
        (
            '(kicad_sch\n\t(title_block\n\t\t(title "Old")\n\t\t(comment 1 "Keep")\n\t)\n)',
            {"title": "New", "company": "Acme"},
            ['(title "New")', '(company "Acme")', '(comment 1 "Keep")'],
        ),
    ],
)
def test_title_block_updates_preserve_fields_and_escaping(
    content: str, updates: dict[str, str], expected_fragments: list[str]
) -> None:
    actual = _apply_title_block_updates(content, updates)
    for fragment in expected_fragments:
        assert fragment in actual
    assert actual.count("(title_block") == 1


def test_empty_updates_keep_legacy_missing_title_block_format() -> None:
    assert _new_title_block_text({}) == "\t(title_block\n\t)"
