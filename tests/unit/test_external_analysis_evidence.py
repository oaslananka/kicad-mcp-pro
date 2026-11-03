"""Unit tests for external analysis evidence import and validation (#1585, T8)."""

from __future__ import annotations

import json
import math
import tempfile
from pathlib import Path

import pytest
from pydantic import ValidationError

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


@pytest.mark.parametrize(
    "context",
    [
        ReviewContext(project_name="my_board"),
        ReviewContext(project_source_sha256=SAMPLE_SHA_1),
        ReviewContext(),
    ],
)
def test_source_identity_missing_cannot_approve_external_report(context: ReviewContext) -> None:
    report = ExternalAnalysisReport(
        report_id="NO_CONTEXT_001",
        tool_name="spice",
        tool_version="42",
        analysis_type="spice",
        project_key="my_board",
        source_sha256=SAMPLE_SHA_1,
    )
    result = evaluate_external_evidence(context, report)
    assert result.status == AssessmentStatus.NOT_ASSESSED
    assert result.missing_inputs


@pytest.mark.parametrize("sha", ["z" * 64, "a" * 63, "a" * 65])
def test_external_report_requires_valid_sha256_digest(sha: str) -> None:
    with pytest.raises(ValidationError):
        ExternalAnalysisReport(
            report_id="BAD_SHA_001",
            tool_name="spice",
            tool_version="42",
            analysis_type="spice",
            project_key="my_board",
            source_sha256=sha,
        )


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_nonfinite_external_solver_metrics_rejected(value: float) -> None:
    with pytest.raises(ValidationError):
        ExternalAnalysisReport(
            report_id="BAD_METRIC_001",
            tool_name="spice",
            tool_version="42",
            analysis_type="spice",
            project_key="my_board",
            source_sha256=SAMPLE_SHA_1,
            metrics={"result": value},
            metric_units={"result": "V"},
        )


def test_report_stackup_requires_matching_active_stackup() -> None:
    report = ExternalAnalysisReport(
        report_id="MISSING_STACK_001",
        tool_name="simulator",
        tool_version="1.0",
        analysis_type="si",
        project_key="my_board",
        source_sha256=SAMPLE_SHA_1,
        stackup_id="pcb4",
    )
    context = ReviewContext(project_name="my_board", project_source_sha256=SAMPLE_SHA_1)
    assessment = evaluate_external_evidence(context, report)
    assert assessment.status == AssessmentStatus.NOT_ASSESSED
    assert "expected_stackup_id" in assessment.missing_inputs


def test_wrong_metric_dimension_never_passes() -> None:
    report = ExternalAnalysisReport(
        report_id="BAD_UNIT_CONTRACT_001",
        tool_name="simulator",
        tool_version="1.0",
        analysis_type="si",
        project_key="my_board",
        source_sha256=SAMPLE_SHA_1,
        metrics={"delay": 1.0},
        metric_units={"delay": "V"},
    )
    context = ReviewContext(
        project_name="my_board",
        project_source_sha256=SAMPLE_SHA_1,
        explicit_requirements={"expected_metric_units": {"delay": "ps"}},
    )
    assessment = evaluate_external_evidence(context, report)
    assert assessment.status == AssessmentStatus.NOT_ASSESSED
    assert "compatible_metric_units" in assessment.missing_inputs


def test_report_loader_rejects_bad_json_shape_schema_and_missing_file(tmp_path: Path) -> None:
    absent, absent_error = load_external_analysis_report("none.json", base_dir=tmp_path)
    assert absent is None
    assert absent_error is not None
    assert "does not exist" in absent_error

    file = tmp_path / "bad.json"
    file.write_text("{", encoding="utf-8")
    malformed, malformed_error = load_external_analysis_report(file, base_dir=tmp_path)
    assert malformed is None
    assert malformed_error is not None
    assert "Failed to parse" in malformed_error

    file.write_text("[]", encoding="utf-8")
    not_mapping, mapping_error = load_external_analysis_report(file, base_dir=tmp_path)
    assert not_mapping is None
    assert mapping_error is not None
    assert "mapping" in mapping_error

    file.write_text("{}", encoding="utf-8")
    bad_schema, schema_error = load_external_analysis_report(file, base_dir=tmp_path)
    assert bad_schema is None
    assert schema_error is not None
    assert "schema validation" in schema_error


def test_report_loads_safe_yaml_without_executing_code(tmp_path: Path) -> None:
    document = tmp_path / "evidence.yml"
    document.write_text(
        "schema_version: 1\nreport_id: YAML_VALID_001\n"
        "tool_name: spice\ntool_version: '42'\nanalysis_type: transient\n"
        "project_key: my_board\nsource_sha256: " + SAMPLE_SHA_1 + "\n",
        encoding="utf-8",
    )
    report, error = load_external_analysis_report(document, base_dir=tmp_path)
    assert error is None
    assert report is not None
    assert report.report_id == "YAML_VALID_001"


def test_external_tool_violation_causes_hard_failure() -> None:
    report = ExternalAnalysisReport(
        report_id="VIOLATION_001",
        tool_name="spice",
        tool_version="42",
        analysis_type="spice",
        project_key="my_board",
        source_sha256=SAMPLE_SHA_1,
        violations=["voltage exceeded safe limit"],
    )
    context = ReviewContext(project_name="my_board", project_source_sha256=SAMPLE_SHA_1)
    assessment = evaluate_external_evidence(context, report)
    assert assessment.status == AssessmentStatus.FAIL
    assert assessment.findings[0].severity == "error"


@pytest.mark.parametrize(
    "digest",
    ["a" * 63, "b" * 65, "z" * 64, "A" * 64],
)
def test_artifact_hashes_reject_invalid_sha256(digest: str) -> None:
    with pytest.raises(ValidationError, match="Artifact digest"):
        ExternalAnalysisReport(
            report_id="ARTIFACT_BAD_001",
            tool_name="spice",
            tool_version="42",
            analysis_type="spice",
            project_key="my_board",
            source_sha256=SAMPLE_SHA_1,
            artifact_hashes={"output": digest},
        )


def test_valid_artifact_hash_and_absolute_report_path(tmp_path: Path) -> None:
    report = ExternalAnalysisReport(
        report_id="ARTIFACT_GOOD_001",
        tool_name="spice",
        tool_version="42",
        analysis_type="spice",
        project_key="my_board",
        source_sha256=SAMPLE_SHA_1,
        artifact_hashes={"output": SAMPLE_SHA_2},
    )
    file = tmp_path / "report.json"
    file.write_text(report.model_dump_json(), encoding="utf-8")
    parsed, error = load_external_analysis_report(file)
    assert error is None
    assert parsed is not None
    assert parsed.artifact_hashes["output"] == SAMPLE_SHA_2


@pytest.mark.parametrize("unit_contract", ["invalid", {"delay": "ps"}, {"delay": "unknown"}])
def test_missing_or_invalid_required_metric_units_rejected(unit_contract: object) -> None:
    report = ExternalAnalysisReport(
        report_id="NO_METRIC_001",
        tool_name="spice",
        tool_version="42",
        analysis_type="spice",
        project_key="my_board",
        source_sha256=SAMPLE_SHA_1,
    )
    context = ReviewContext(
        project_name="my_board",
        project_source_sha256=SAMPLE_SHA_1,
        explicit_requirements={"expected_metric_units": unit_contract},
    )
    result = evaluate_external_evidence(context, report)
    assert result.status == AssessmentStatus.NOT_ASSESSED
    assert "compatible_metric_units" in result.missing_inputs


def test_valid_expected_metric_units_preserve_clean_result() -> None:
    report = ExternalAnalysisReport(
        report_id="VALID_DIMENSION_001",
        tool_name="spice",
        tool_version="42",
        analysis_type="transient",
        project_key="my_board",
        source_sha256=SAMPLE_SHA_1,
        metrics={"delay": 2.1},
        metric_units={"delay": "ps"},
    )
    context = ReviewContext(
        project_name="my_board",
        project_source_sha256=SAMPLE_SHA_1,
        explicit_requirements={"expected_metric_units": {"delay": "ps"}},
    )
    result = evaluate_external_evidence(context, report)
    assert result.status == AssessmentStatus.PASS
