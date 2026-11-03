"""Unit tests for external analysis evidence import and validation (#1585, T8)."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from kicad_mcp.models.review import (
    AssessmentStatus,
    EvaluationMethod,
    ReviewContext,
)
from kicad_mcp.project.evidence_freshness import EvidenceRecordKind
from kicad_mcp.review.external_evidence import (
    ExternalAnalysisReport,
    evaluate_external_evidence,
    load_external_analysis_report,
    report_to_evidence_record,
)

SAMPLE_SHA_1 = "a" * 64
SAMPLE_SHA_2 = "b" * 64


def test_load_report_path_safety_and_size_limit() -> None:
    """Proves path traversal security and file size limit enforcement."""
    with tempfile.TemporaryDirectory() as tmpdir:
        base_dir = Path(tmpdir)
        safe_file = base_dir / "valid_report.json"
        safe_data = {
            "schema_version": 1,
            "report_id": "SPICE_RUN_001",
            "tool_name": "ngspice",
            "tool_version": "42",
            "analysis_type": "spice",
            "method": "analytical",
            "project_key": "power_converter",
            "source_sha256": SAMPLE_SHA_1,
            "convergence_status": "converged",
            "metrics": {"v_ripple_mv": 12.5},
            "metric_units": {"v_ripple_mv": "mV"},
        }
        safe_file.write_text(json.dumps(safe_data), encoding="utf-8")

        # 1. Safe load within base_dir passes
        report, err = load_external_analysis_report("valid_report.json", base_dir=base_dir)
        assert err is None
        assert report is not None
        assert report.report_id == "SPICE_RUN_001"

        # 2. Path traversal escaping base_dir rejected
        _, trav_err = load_external_analysis_report("../../etc/passwd", base_dir=base_dir)
        assert trav_err is not None
        assert "escapes project directory" in trav_err

        # 3. Size limit exceeded
        large_file = base_dir / "large.json"
        large_file.write_text("x" * (10 * 1024 * 1024 + 100), encoding="utf-8")
        _, size_err = load_external_analysis_report(large_file, base_dir=base_dir)
        assert size_err is not None
        assert "exceeds size limit" in size_err


def test_foreign_board_and_stale_source_rejected() -> None:
    """Proves foreign-board reports and stale source hashes cannot PASS."""
    context = ReviewContext(
        project_name="my_active_board",
        project_source_sha256=SAMPLE_SHA_1,
    )

    # A) Foreign board report
    foreign_rep = ExternalAnalysisReport(
        report_id="FOREIGN_001",
        tool_name="openEMS",
        tool_version="0.0.36",
        analysis_type="emc",
        project_key="other_foreign_board",  # Mismatch!
        source_sha256=SAMPLE_SHA_1,
    )
    eval_foreign = evaluate_external_evidence(context, foreign_rep)
    assert eval_foreign.status == AssessmentStatus.FAIL
    assert "Foreign board report rejected" in eval_foreign.summary

    # B) Stale source report
    stale_rep = ExternalAnalysisReport(
        report_id="STALE_001",
        tool_name="openEMS",
        tool_version="0.0.36",
        analysis_type="emc",
        project_key="my_active_board",
        source_sha256=SAMPLE_SHA_2,  # Stale hash!
    )
    eval_stale = evaluate_external_evidence(context, stale_rep)
    assert eval_stale.status == AssessmentStatus.FAIL
    assert "Stale source report rejected" in eval_stale.summary


def test_mismatched_stackup_and_divergence_rejected() -> None:
    """Proves stackup mismatches and numerical solver divergences cannot PASS."""
    context = ReviewContext(
        project_name="my_board",
        project_source_sha256=SAMPLE_SHA_1,
        explicit_requirements={"expected_stackup_id": "jlcpcb_4layer_jlc04161h"},
    )

    # 1. Stackup mismatch
    mismatched_rep = ExternalAnalysisReport(
        report_id="STACK_001",
        tool_name="anysolver",
        tool_version="1.0",
        analysis_type="fem",
        project_key="my_board",
        source_sha256=SAMPLE_SHA_1,
        stackup_id="pcbway_6layer_std",  # Mismatch!
    )
    eval_stack = evaluate_external_evidence(context, mismatched_rep)
    assert eval_stack.status == AssessmentStatus.FAIL
    assert "Stackup mismatch" in eval_stack.summary

    # 2. Solver divergence
    diverged_rep = ExternalAnalysisReport(
        report_id="DIV_001",
        tool_name="ngspice",
        tool_version="42",
        analysis_type="spice",
        project_key="my_board",
        source_sha256=SAMPLE_SHA_1,
        stackup_id="jlcpcb_4layer_jlc04161h",
        convergence_status="diverged",
        termination_reason="timestep too small (singular matrix)",
    )
    eval_div = evaluate_external_evidence(context, diverged_rep)
    assert eval_div.status == AssessmentStatus.FAIL
    assert "Simulation failed to converge" in eval_div.summary


def test_incompatible_units_yields_not_assessed() -> None:
    """Metrics with non-physical or unrecognized units cannot return PASS."""
    context = ReviewContext(
        project_name="my_board",
        project_source_sha256=SAMPLE_SHA_1,
    )
    unit_rep = ExternalAnalysisReport(
        report_id="UNIT_001",
        tool_name="tool",
        tool_version="1.0",
        analysis_type="custom",
        project_key="my_board",
        source_sha256=SAMPLE_SHA_1,
        metrics={"delay": 42.0},
        metric_units={"delay": "parsecs"},  # Unrecognized unit
    )
    eval_unit = evaluate_external_evidence(context, unit_rep)
    assert eval_unit.status == AssessmentStatus.NOT_ASSESSED
    assert "Incompatible unit" in eval_unit.summary


def test_optional_external_review_local_offline() -> None:
    """Missing external analysis report returns NOT_ASSESSED without blocking local review."""
    context = ReviewContext(project_name="offline_board")
    eval_offline = evaluate_external_evidence(context, None)

    assert eval_offline.status == AssessmentStatus.NOT_ASSESSED
    assert "offline and active" in eval_offline.summary


def test_clean_report_passes_and_converts_to_evidence_record() -> None:
    """Clean, verified external report passes and converts into first-class EvidenceRecord."""
    context = ReviewContext(
        project_name="clean_board",
        project_source_sha256=SAMPLE_SHA_1,
    )
    clean_rep = ExternalAnalysisReport(
        report_id="REPORT_CLEAN_001",
        tool_name="openEMS",
        tool_version="0.0.36",
        analysis_type="ibis_eye",
        method=EvaluationMethod.ANALYTICAL,
        project_key="clean_board",
        source_sha256=SAMPLE_SHA_1,
        convergence_status="converged",
        metrics={"eye_height_mv": 320.0, "eye_width_ps": 850.0},
        metric_units={"eye_height_mv": "mV", "eye_width_ps": "ps"},
        violations=[],
    )

    assessment = evaluate_external_evidence(context, clean_rep)
    assert assessment.status == AssessmentStatus.PASS
    assert assessment.evidence_refs == ["REPORT_CLEAN_001"]

    # Convert to EvidenceRecord
    ev_record = report_to_evidence_record(clean_rep)
    assert ev_record.evidence_id == "REPORT_CLEAN_001"
    assert ev_record.kind == EvidenceRecordKind.VERIFICATION_RUN
    assert ev_record.producer == "openEMS"
    assert ev_record.source_sha256 == SAMPLE_SHA_1
    assert ev_record.provenance_source == "external_tool:openEMS"
