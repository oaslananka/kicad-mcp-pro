"""Unit tests for the headless schematic visual-QA engine (issue #153)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from kicad_mcp.models.visual_qa import (
    detect_label_collisions,
    detect_offsheet,
    detect_offsheet_boxes,
    detect_symbol_overlap,
    detect_text_overlap,
    parse_labels,
    parse_paper_extent,
    parse_placed_symbols,
    parse_symbols,
    run_visual_qa,
)

CLEAN_SCH = """
(kicad_sch (version 20240101) (paper "A4")
  (title_block (title "Demo Board") (rev "A") (date "2026-01-01") (company "Acme"))
  (label "NET_A" (at 50 40 0))
  (label "NET_B" (at 150 100 0))
  (symbol (lib_id "Device:R") (at 100 50 0)
    (property "Reference" "R1" (at 102 49 0))
    (property "Footprint" "Resistor_SMD:R_0402_1005Metric" (at 100 50 0))
  )
)
"""

DEFECT_SCH = """
(kicad_sch (version 20240101) (paper "A4")
  (label "OVERLAP_1" (at 80 60 0))
  (label "OVERLAP_2" (at 80.3 60 0))
  (symbol (lib_id "Device:R") (at 5000 9000 0)
    (property "Reference" "R9" (at 5002 8999 0))
  )
)
"""


def test_parse_paper_extent_default_and_portrait() -> None:
    assert parse_paper_extent('(paper "A4")') == (297.0, 210.0)
    assert parse_paper_extent('(paper "A4" portrait)') == (210.0, 297.0)
    assert parse_paper_extent('(paper "User" 200 150)') == (200.0, 150.0)
    assert parse_paper_extent("(no paper here)") == (297.0, 210.0)


def test_parse_labels_and_symbols() -> None:
    labels = parse_labels(CLEAN_SCH)
    assert {label.text for label in labels} == {"NET_A", "NET_B"}
    symbols = parse_symbols(CLEAN_SCH)
    assert len(symbols) == 1
    assert symbols[0].reference == "R1"
    assert symbols[0].lib_id == "Device:R"


def test_parse_labels_finds_shaped_global_and_hierarchical_labels() -> None:
    """Real global/hierarchical labels always carry a (shape ...) token
    between the name and (at ...); before this fix the regexes required (at
    ...) immediately after the name, so every shaped label (i.e. virtually
    all of them) was silently invisible to overlap/offsheet detection."""
    sch = """
    (kicad_sch (version 20240101) (paper "A4")
      (global_label "VCC" (shape output) (at 10 10 0)
        (effects (font (size 1.524 1.524))))
      (hierarchical_label "SIG" (shape bidirectional) (at 20 20 0)
        (effects (font (size 1.524 1.524))))
    )
    """
    labels = {label.text: label for label in parse_labels(sch)}
    assert labels["VCC"].kind == "global"
    assert labels["SIG"].kind == "hierarchical"


def test_parse_labels_reads_real_justify_override() -> None:
    """Issue #373: a label's rendered box must reflect its actual (justify
    ...) token, not an assumed center, or overlap detection would be wrong
    for the directional hierarchical/global labels that carry one."""
    sch = """
    (kicad_sch (version 20240101) (paper "A4")
      (hierarchical_label "VOUT_5V" (shape output) (at 20.32 20.32 0)
        (effects (font (size 1.524 1.524)) (justify left)))
      (global_label "GND" (shape input) (at 40 40 0)
        (effects (font (size 1.524 1.524))))
    )
    """
    labels = {label.text: label for label in parse_labels(sch)}
    assert labels["VOUT_5V"].justify == frozenset({"left"})
    assert labels["GND"].justify == frozenset()

    # Left-justified text grows to the right of its anchor; a centered label
    # of the same text would straddle the anchor on both sides instead.
    left_box = labels["VOUT_5V"].box()
    assert left_box.x_min == pytest.approx(20.32)
    assert left_box.x_max > left_box.x_min


def test_detect_label_collisions_flags_overlap() -> None:
    findings = detect_label_collisions(parse_labels(DEFECT_SCH))
    assert len(findings) == 1
    assert findings[0].code == "label_overlap"


def test_detect_offsheet_flags_far_symbol() -> None:
    findings = detect_offsheet(parse_symbols(DEFECT_SCH), parse_labels(DEFECT_SCH), (297.0, 210.0))
    codes = {finding.code for finding in findings}
    assert "offsheet_symbol" in codes


def test_clean_schematic_passes() -> None:
    report = run_visual_qa(CLEAN_SCH)
    assert report["status"] == "PASS"
    assert report["symbol_count"] == 1
    assert report["label_count"] == 2


def test_defect_schematic_warns() -> None:
    report = run_visual_qa(DEFECT_SCH)
    assert report["status"] == "WARN"
    codes = {finding["code"] for finding in report["findings"]}
    assert {"label_overlap", "offsheet_symbol", "title_block_missing"} <= codes


# A schematic with a real cached lib symbol, two symbols whose bodies/text
# overlap, and a label dropped on a symbol's value — the defects a pin-anchor
# check cannot see.
OVERLAP_SCH = """
(kicad_sch (version 20240101) (paper "A4")
  (title_block (title "Overlap Board") (rev "A") (date "2026-01-01") (company "Acme"))
  (lib_symbols
    (symbol "Device:R"
      (symbol "R_0_1"
        (rectangle (start -1.016 -2.54) (end 1.016 2.54) (stroke (width 0.254)))
      )
      (symbol "R_1_1"
        (pin passive line (at 0 3.81 270) (length 1.27) (name "~") (number "1"))
        (pin passive line (at 0 -3.81 90) (length 1.27) (name "~") (number "2"))
      )
    )
  )
  (symbol (lib_id "Device:R") (at 100 100 0)
    (property "Reference" "R1" (at 102 98 0))
    (property "Value" "10k" (at 102 102 0))
  )
  (symbol (lib_id "Device:R") (at 101 100 0)
    (property "Reference" "R2" (at 103 98 0))
    (property "Value" "10k" (at 103 102 0))
  )
)
"""


def test_parse_placed_symbols_reads_body_and_visible_fields() -> None:
    placed = parse_placed_symbols(OVERLAP_SCH)
    assert {p.reference for p in placed} == {"R1", "R2"}
    r1 = next(p for p in placed if p.reference == "R1")
    # Body comes from the cached rectangle/pins, so it has real height.
    assert r1.body.height > 5.0
    # Reference + Value are visible; Footprint/Datasheet are not present here.
    assert {f.text for f in r1.fields} == {"R1", "10k"}


def test_detect_symbol_overlap_flags_touching_bodies() -> None:
    placed = parse_placed_symbols(OVERLAP_SCH)
    findings = detect_symbol_overlap(placed)
    assert any(f.code == "symbol_overlap" for f in findings)


def test_detect_text_overlap_flags_cross_symbol_text() -> None:
    placed = parse_placed_symbols(OVERLAP_SCH)
    findings = detect_text_overlap(placed, parse_labels(OVERLAP_SCH))
    assert any(f.code == "text_overlap" for f in findings)


def test_text_overlap_ignores_same_symbol_fields() -> None:
    # R1's own Reference and Value are stacked deliberately; a single symbol's
    # own fields must never be reported against each other.
    single = """
(kicad_sch (paper "A4")
  (symbol (lib_id "Device:R") (at 100 100 0)
    (property "Reference" "R1" (at 100 100 0))
    (property "Value" "10k" (at 100 100 0))
  )
)
"""
    findings = detect_text_overlap(parse_placed_symbols(single), [])
    assert findings == []


def test_hidden_and_footprint_fields_excluded_from_text() -> None:
    sch = """
(kicad_sch (paper "A4")
  (symbol (lib_id "Device:R") (at 100 100 0)
    (property "Reference" "R1" (at 102 100 0))
    (property "Footprint" "Resistor_SMD:R_0402_1005Metric" (at 100 100 0))
    (property "Datasheet" "https://example.com/very/long/datasheet/url" (at 100 100 0))
    (property "MPN" "RC0402" (at 100 100 0) (effects (font (size 1.27 1.27)) (hide yes)))
  )
)
"""
    placed = parse_placed_symbols(sch)
    assert {f.text for f in placed[0].fields} == {"R1"}


def test_detect_offsheet_boxes_uses_extent_not_anchor() -> None:
    # Anchor is on-sheet, but a long visible value pushes the extent off the
    # right edge of a narrow User sheet.
    sch = """
(kicad_sch (paper "User" 30 30)
  (symbol (lib_id "Device:R") (at 28 15 0)
    (property "Reference" "R1" (at 28 14 0))
    (property "Value" "A_VERY_LONG_VALUE_STRING_THAT_OVERFLOWS" (at 40 15 0))
  )
)
"""
    placed = parse_placed_symbols(sch)
    findings = detect_offsheet_boxes(placed, [], (30.0, 30.0))
    assert any(f.code == "offsheet_symbol" for f in findings)


def test_overlap_schematic_run_warns() -> None:
    report = run_visual_qa(OVERLAP_SCH)
    assert report["status"] == "WARN"
    codes = {finding["code"] for finding in report["findings"]}
    assert {"symbol_overlap", "text_overlap"} & codes


@pytest.mark.anyio
async def test_sch_visual_qa_tool(tmp_path: Path) -> None:
    from kicad_mcp.server import create_server
    from tests.conftest import call_tool_text

    (tmp_path / "test.kicad_pro").write_text("{}", encoding="utf-8")
    (tmp_path / "test.kicad_pcb").write_text("", encoding="utf-8")
    (tmp_path / "test.kicad_sch").write_text(DEFECT_SCH, encoding="utf-8")

    server = create_server()
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(tmp_path)})
    raw = await call_tool_text(server, "sch_visual_qa", {})
    payload = json.loads(raw)
    assert payload["status"] == "WARN"
    assert payload["sheets"]
    codes = {f["code"] for sheet in payload["sheets"] for f in sheet["findings"]}
    assert "label_overlap" in codes
