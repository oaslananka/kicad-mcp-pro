"""Maintained stale-evidence escape regression corpus for #942 criterion 8."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

import kicad_mcp.evals.stale_evidence_escape as escape_module
from kicad_mcp.evals.stale_evidence_escape import (
    STALE_EVIDENCE_ESCAPE_CORPUS_PATH,
    StaleEvidenceEscapeCorpus,
    build_stale_evidence_escape_report,
    evaluate_stale_evidence_escape_case,
    load_stale_evidence_escape_corpus,
    render_stale_evidence_escape_report_json,
)
from kicad_mcp.project.release_evidence_policy import (
    ContractReleaseEvidenceResult,
    ContractReleaseEvidenceState,
    ReleaseEvidenceGateResult,
)

ROOT = Path(__file__).resolve().parents[2]
CORPUS_PATH = ROOT / "evals/evidence_freshness/stale_escape_cases.json"
REPORT_PATH = ROOT / "docs/evidence/stale-evidence-escape-report.json"


def _corpus() -> StaleEvidenceEscapeCorpus:
    return load_stale_evidence_escape_corpus()


def test_loader_is_pinned_to_committed_corpus() -> None:
    assert STALE_EVIDENCE_ESCAPE_CORPUS_PATH == CORPUS_PATH
    assert STALE_EVIDENCE_ESCAPE_CORPUS_PATH.is_file()


def test_committed_corpus_has_zero_stale_evidence_escape_rate() -> None:
    report = build_stale_evidence_escape_report(_corpus())
    assert report.stale_cases == 10
    assert report.total_cases == 12
    assert report.escape_count == 0
    assert report.escape_rate == 0.0
    assert report.target_escape_rate == 0.0
    assert report.target_met
    assert report.all_expectations_met


def test_committed_corpus_covers_positive_and_fail_closed_controls() -> None:
    corpus = _corpus()
    scenarios = {case.scenario.value for case in corpus.cases}
    assert scenarios == {
        "unrelated_component_edit",
        "usb_entity_edit",
        "stackup_entity_edit",
        "contract_entity_edit",
        "usb_hash_change",
        "unknown_mutation_scope",
        "missing_stackup_hash",
        "missing_freshness_assessment",
        "dependency_edge_removed",
        "tampered_evidence_record",
        "fresh_reviewed_waiver",
        "stale_reviewed_waiver",
    }


def test_machine_readable_report_matches_committed_fixture() -> None:
    report = build_stale_evidence_escape_report(_corpus())
    committed = REPORT_PATH.read_text(encoding="utf-8")
    assert committed == render_stale_evidence_escape_report_json(report)
    parsed = json.loads(committed)
    assert parsed["escape_count"] == 0
    assert parsed["escape_rate"] == 0.0
    assert parsed["target_met"] is True


def test_corpus_rejects_duplicate_case_ids() -> None:
    payload = _corpus().model_dump(mode="json")
    payload["cases"].append(payload["cases"][0])
    with pytest.raises(ValidationError, match="duplicate stale-evidence escape case ID"):
        StaleEvidenceEscapeCorpus.model_validate(payload)


def test_corpus_requires_at_least_one_must_block_case() -> None:
    payload = _corpus().model_dump(mode="json")
    payload["cases"] = [case for case in payload["cases"] if not case["must_block"]]
    with pytest.raises(ValidationError, match="corpus requires at least one must-block case"):
        StaleEvidenceEscapeCorpus.model_validate(payload)


def test_corpus_rejects_waiver_expectation_shape_mismatch() -> None:
    payload = _corpus().model_dump(mode="json")
    payload["cases"][0]["expected_waiver_freshness"] = "still_valid"
    with pytest.raises(ValidationError, match="waiver scenarios require"):
        StaleEvidenceEscapeCorpus.model_validate(payload)


def test_corpus_requires_must_block_to_match_blocked_state() -> None:
    payload = _corpus().model_dump(mode="json")
    payload["cases"][1]["must_block"] = False
    with pytest.raises(ValidationError, match="must_block must match"):
        StaleEvidenceEscapeCorpus.model_validate(payload)


def _unsafe_approved_gate(*_args: object, **_kwargs: object) -> ReleaseEvidenceGateResult:
    return ReleaseEvidenceGateResult(
        approved=True,
        contracts=(
            ContractReleaseEvidenceResult(
                contract_id="INTENT-USB-SI",
                contract_version=1,
                state=ContractReleaseEvidenceState.SATISFIED,
                evidence_ids=("EVID-USB-Z0",),
            ),
        ),
    )


def test_escape_metric_detects_unsafe_approval_of_invalidated_proof(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = next(case for case in _corpus().cases if case.case_id == "usb-geometry-edit-blocks")
    monkeypatch.setattr(escape_module, "evaluate_release_evidence", _unsafe_approved_gate)
    result = evaluate_stale_evidence_escape_case(case)
    assert result.primary_freshness.value == "invalidated"
    assert result.release_approved
    assert result.escaped
    assert not result.passed


def test_escape_metric_detects_unsafe_approval_without_freshness_assessment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = next(
        case for case in _corpus().cases if case.case_id == "missing-freshness-assessment-blocks"
    )
    monkeypatch.setattr(escape_module, "evaluate_release_evidence", _unsafe_approved_gate)
    result = evaluate_stale_evidence_escape_case(case)
    assert result.primary_freshness.value == "still_valid"
    assert result.release_approved
    assert result.escaped
    assert not result.passed
