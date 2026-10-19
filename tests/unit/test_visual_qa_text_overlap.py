"""Regression tests for cross-owner text-overlap warnings."""

from kicad_mcp.models.visual_qa import _text_overlap_finding
from kicad_mcp.utils.geometry import Box


def test_text_overlap_ignores_separated_or_grazing_boxes() -> None:
    original = Box(0.0, 0.0, 2.0, 2.0)

    assert _text_overlap_finding("R1", original, "R2", Box(3.0, 0.0, 5.0, 2.0)) is None
    assert _text_overlap_finding("R1", original, "R2", Box(1.6, 1.6, 3.0, 3.0)) is None


def test_text_overlap_reports_same_geometry_and_reference() -> None:
    finding = _text_overlap_finding(
        "R1:Value",
        Box(0.0, 0.0, 3.0, 3.0),
        "label:GND",
        Box(1.0, 1.0, 4.0, 4.0),
    )

    assert finding is not None
    assert finding.level == "WARN"
    assert finding.code == "text_overlap"
    assert finding.ref == "R1:Value"
    assert finding.x == 1.5
    assert finding.y == 1.5
    assert "overlaps 'label:GND' (~4.0 mm²)" in finding.message
