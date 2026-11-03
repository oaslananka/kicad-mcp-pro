"""Unit tests for context-aware routing style policy evaluation (#1581, T3).

Validates:
- Ordinary-board 90-degree corner preference is advisory (WARN), not electrical defect.
- Explicit style policy violation (strict_45) reports FAIL as a cosmetic style policy.
- Orthogonal routing allowed reports NOT_APPLICABLE.
- Distinguishes true corners from T-junctions, cross-junctions, arcs, and pad stubs.
- Ambiguous/corrupt geometry reports NOT_ASSESSED.
- Legacy pcb_route_corner_style_gate signature and behavior compatibility.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from kicad_mcp.models.review import (
    AssessmentStatus,
    ReviewContext,
)
from kicad_mcp.review.adapter import adapt_assessment_to_verdict
from kicad_mcp.review.routing_style import evaluate_routing_style
from kicad_mcp.tools import validation
from kicad_mcp.tools.validation import (
    _pcb_track_arcs_from_text,
    _pcb_track_segments_from_text,
    _route_90_degree_corners,
)


def test_ordinary_board_90_degree_corner_is_advisory_warn() -> None:
    pcb_text = """
(kicad_pcb
  (segment (start 10 10) (end 20 10) (width 0.2) (layer "F.Cu") (net "SIGNAL_A"))
  (segment (start 20 10) (end 20 20) (width 0.2) (layer "F.Cu") (net "SIGNAL_A"))
)
"""
    context = ReviewContext(project_name="StandardBoard")
    assessment = evaluate_routing_style(context, pcb_text)

    assert assessment.status == AssessmentStatus.WARN
    assert "advisory" in assessment.summary.lower()
    assert assessment.metadata["defect_category"] == "cosmetic_style"
    assert assessment.metadata["electrical_defect"] is False
    assert assessment.metadata["is_advisory"] is True
    assert len(assessment.findings) == 1

    finding = assessment.findings[0]
    assert finding.severity == "warning"
    assert "Advisory" in finding.description
    assert finding.metadata["defect_category"] == "cosmetic_style"
    assert finding.metadata["electrical_defect"] is False


def test_explicit_strict_45_policy_violation_fails_as_style_policy() -> None:
    pcb_text = """
(kicad_pcb
  (segment (start 10 10) (end 20 10) (width 0.2) (layer "F.Cu") (net "CLK"))
  (segment (start 20 10) (end 20 20) (width 0.2) (layer "F.Cu") (net "CLK"))
)
"""
    context = ReviewContext(
        project_name="StrictBoard",
        declared_routing_style="strict_45",
    )
    assessment = evaluate_routing_style(context, pcb_text)

    assert assessment.status == AssessmentStatus.FAIL
    assert "violating explicit project policy 'strict_45'" in assessment.summary
    assert assessment.metadata["defect_category"] == "cosmetic_style"
    assert assessment.metadata["electrical_defect"] is False
    assert assessment.metadata["is_advisory"] is False
    assert len(assessment.findings) == 1

    finding = assessment.findings[0]
    assert finding.severity == "error"
    assert "violates explicit policy 'strict_45'" in finding.description
    assert finding.metadata["defect_category"] == "cosmetic_style"
    assert finding.metadata["electrical_defect"] is False


def test_orthogonal_allowed_declares_not_applicable() -> None:
    pcb_text = """
(kicad_pcb
  (segment (start 10 10) (end 20 10) (width 0.2) (layer "F.Cu") (net "PWR"))
  (segment (start 20 10) (end 20 20) (width 0.2) (layer "F.Cu") (net "PWR"))
)
"""
    context = ReviewContext(
        project_name="BusBoard",
        declared_routing_style="orthogonal_allowed",
    )
    assessment = evaluate_routing_style(context, pcb_text)

    assert assessment.status == AssessmentStatus.NOT_APPLICABLE
    assert assessment.findings == []
    assert assessment.metadata["defect_category"] == "cosmetic_style"
    assert assessment.metadata["electrical_defect"] is False


def test_clean_board_satisfies_45_degree_style() -> None:
    pcb_text = """
(kicad_pcb
  (segment (start 10 10) (end 18 10) (width 0.2) (layer "F.Cu") (net "DIFF_P"))
  (segment (start 18 10) (end 20 12) (width 0.2) (layer "F.Cu") (net "DIFF_P"))
  (segment (start 20 12) (end 20 20) (width 0.2) (layer "F.Cu") (net "DIFF_P"))
)
"""
    context = ReviewContext(project_name="CleanBoard")
    assessment = evaluate_routing_style(context, pcb_text)

    assert assessment.status == AssessmentStatus.PASS
    assert assessment.findings == []
    assert assessment.metadata["corner_count"] == 0


def test_t_junction_is_not_flagged_as_route_corner() -> None:
    # A horizontal trunk from (10, 10) to (30, 10) tapped by a vertical branch to (20, 20)
    pcb_text = """
(kicad_pcb
  (segment (start 10 10) (end 20 10) (width 0.2) (layer "F.Cu") (net "GND"))
  (segment (start 20 10) (end 30 10) (width 0.2) (layer "F.Cu") (net "GND"))
  (segment (start 20 10) (end 20 20) (width 0.2) (layer "F.Cu") (net "GND"))
)
"""
    segments = _pcb_track_segments_from_text(pcb_text)
    corners = _route_90_degree_corners(segments)

    # 3 segments meeting at (20, 10) form a T-junction, not a 90° corner bend
    assert corners == []

    context = ReviewContext(project_name="TJunctionBoard")
    assessment = evaluate_routing_style(context, pcb_text)
    assert assessment.status == AssessmentStatus.PASS
    assert assessment.findings == []


def test_cross_junction_is_not_flagged_as_route_corner() -> None:
    # 4 segments meeting at (20, 20)
    pcb_text = """
(kicad_pcb
  (segment (start 10 20) (end 20 20) (width 0.2) (layer "F.Cu") (net "GND"))
  (segment (start 20 20) (end 30 20) (width 0.2) (layer "F.Cu") (net "GND"))
  (segment (start 20 10) (end 20 20) (width 0.2) (layer "F.Cu") (net "GND"))
  (segment (start 20 20) (end 20 30) (width 0.2) (layer "F.Cu") (net "GND"))
)
"""
    segments = _pcb_track_segments_from_text(pcb_text)
    corners = _route_90_degree_corners(segments)
    assert corners == []


def test_arc_transition_is_not_flagged_as_route_corner() -> None:
    # Straight segment connects to an arc track at (20, 10)
    pcb_text = """
(kicad_pcb
  (segment (start 10 10) (end 20 10) (width 0.2) (layer "F.Cu") (net "RF_TRACE"))
  (arc (start 20 10) (mid 22 11) (end 25 15) (width 0.2) (layer "F.Cu") (net "RF_TRACE"))
)
"""
    segments = _pcb_track_segments_from_text(pcb_text)
    arcs = _pcb_track_arcs_from_text(pcb_text)
    assert len(arcs) == 1

    corners = _route_90_degree_corners(segments, arcs=arcs)
    assert corners == []


def test_pad_entry_stub_shorter_than_min_segment_is_ignored() -> None:
    # A short stub (0.1 mm < default 0.25 mm)
    pcb_text = """
(kicad_pcb
  (segment (start 10 10) (end 20 10) (width 0.2) (layer "F.Cu") (net "PAD_STUB"))
  (segment (start 20 10) (end 20 10.1) (width 0.2) (layer "F.Cu") (net "PAD_STUB"))
)
"""
    segments = _pcb_track_segments_from_text(pcb_text)
    corners = _route_90_degree_corners(segments, min_segment_length_mm=0.25)
    assert corners == []


def test_ambiguous_or_unsupported_geometry_yields_not_assessed() -> None:
    # Segment block containing unparseable NaN coordinate
    corrupt_pcb = """
(kicad_pcb
  (segment (start 10 10) (end NaN 10) (width 0.2) (layer "F.Cu") (net "NET1"))
  (segment (start 10 10) (end 10 20) (width 0.2) (layer "F.Cu") (net "NET1"))
)
"""
    context = ReviewContext(project_name="CorruptBoard")
    assessment = evaluate_routing_style(context, corrupt_pcb)

    assert assessment.status == AssessmentStatus.NOT_ASSESSED
    assert "geometry_resolution" in assessment.missing_inputs
    assert assessment.metadata["unsupported_geometry"] is True
    assert assessment.metadata["defect_category"] == "cosmetic_style"


def test_missing_pcb_text_yields_blocked() -> None:
    context = ReviewContext(project_name="EmptyBoard")
    assessment = evaluate_routing_style(context, None)

    assert assessment.status == AssessmentStatus.BLOCKED
    assert "pcb_text" in assessment.missing_inputs


def test_legacy_pcb_route_corner_style_gate_compatibility(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pcb_content = """
(kicad_pcb
  (segment (start 10 10) (end 20 10) (width 0.2) (layer "F.Cu") (net "DATA"))
  (segment (start 20 10) (end 20 20) (width 0.2) (layer "F.Cu") (net "DATA"))
)
"""
    with tempfile.TemporaryDirectory() as tmpdir:
        pcb_path = Path(tmpdir) / "test.kicad_pcb"
        pcb_path.write_text(pcb_content, encoding="utf-8")

        mock_cfg = MagicMock()
        mock_cfg.pcb_file = pcb_path
        monkeypatch.setattr(validation, "get_config", lambda: mock_cfg)

        outcome = validation._evaluate_route_corner_style_gate(max_90_degree_corners=0)
        assert outcome.status == "FAIL"
        assert "violate the cosmetic 45°/rounded-corner style policy" in outcome.summary

        report = validation._gate_report(outcome)
        assert report.verdict == "FAIL"
        assert report.metadata["defect_category"] == "cosmetic_style"
        assert report.metadata["electrical_defect"] is False

        assert len(report.findings) >= 1
        finding = report.findings[0]
        assert finding.metadata["defect_category"] == "cosmetic_style"
        assert finding.metadata["electrical_defect"] is False


def test_adapted_verdict_preserves_style_metadata() -> None:
    context = ReviewContext(
        project_name="StrictBoard",
        declared_routing_style="strict_45",
    )
    pcb_text = """
(kicad_pcb
  (segment (start 10 10) (end 20 10) (width 0.2) (layer "F.Cu") (net "SIG"))
  (segment (start 20 10) (end 20 20) (width 0.2) (layer "F.Cu") (net "SIG"))
)
"""
    assessment = evaluate_routing_style(context, pcb_text)
    verdict = adapt_assessment_to_verdict(assessment)

    assert verdict.verdict == "FAIL"
    assert verdict.metadata["review_status"] == "FAIL"
    assert verdict.findings[0].metadata["defect_category"] == "cosmetic_style"
    assert verdict.findings[0].metadata["electrical_defect"] is False
