from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

import kicad_mcp.evals as evals
from kicad_mcp.evals.semantic_differential import (
    DIFFERENTIAL_REPORT_SCHEMA_VERSION,
    DIFFERENTIAL_RESULT_SCHEMA_VERSION,
    DifferentialResult,
    aggregate_differential_results,
    classify_differential_result,
    render_differential_report_json,
)

SOURCE_SHA = "a" * 40
FIXTURE_HASH = "sha256:" + "b" * 64
NATIVE_HASH = "sha256:" + "c" * 64
CUSTOM_HASH = "sha256:" + "d" * 64


def _classify(**overrides: object) -> DifferentialResult:
    payload: dict[str, object] = {
        "source_sha": SOURCE_SHA,
        "lane": "stable",
        "kicad_version": "10.0.6",
        "fixture_id": "clean-board",
        "fixture_hash": FIXTURE_HASH,
        "operation": "connectivity.net-compilation",
        "authority": "kicad-cli:netlist",
        "comparison_method": "normalized-json-sha256",
        "native_result_hash": NATIVE_HASH,
        "custom_result_hash": NATIVE_HASH,
        "native_pass": True,
        "custom_pass": True,
    }
    payload.update(overrides)
    return classify_differential_result(**payload)  # type: ignore[arg-type]


def test_match_requires_real_native_and_custom_hash_equality() -> None:
    result = _classify()

    assert result.schema_version == DIFFERENTIAL_RESULT_SCHEMA_VERSION
    assert result.status == "match"
    assert result.false_pass is False
    assert result.false_fail is False
    assert result.native_result_hash == result.custom_result_hash


def test_divergence_classifies_false_pass_and_false_fail() -> None:
    false_pass = _classify(
        custom_result_hash=CUSTOM_HASH,
        native_pass=False,
        custom_pass=True,
    )
    false_fail = _classify(
        custom_result_hash=CUSTOM_HASH,
        native_pass=True,
        custom_pass=False,
    )

    assert false_pass.status == "divergence"
    assert false_pass.false_pass is True
    assert false_pass.false_fail is False
    assert false_fail.status == "divergence"
    assert false_fail.false_pass is False
    assert false_fail.false_fail is True


def test_unavailable_authority_and_infrastructure_invalid_fail_closed() -> None:
    unavailable = _classify(
        authority_available=False,
        native_result_hash=None,
        native_pass=None,
        reason="KiCad CLI does not expose this comparison on this lane.",
    )
    invalid = _classify(
        infrastructure_valid=False,
        native_result_hash=None,
        custom_result_hash=None,
        native_pass=None,
        custom_pass=None,
        reason="Fixture failed to open in the native canary environment.",
    )

    assert unavailable.status == "unavailable-authority"
    assert unavailable.false_pass is False
    assert unavailable.false_fail is False
    assert invalid.status == "infrastructure-invalid"
    assert invalid.false_pass is False
    assert invalid.false_fail is False


def test_result_schema_rejects_fabricated_match_and_bad_identity() -> None:
    payload = _classify().model_dump(mode="json")
    payload["custom_result_hash"] = CUSTOM_HASH

    with pytest.raises(ValidationError, match="match requires equal native/custom result hashes"):
        DifferentialResult.model_validate(payload)

    payload = _classify().model_dump(mode="json")
    payload["source_sha"] = "not-a-git-sha"
    with pytest.raises(ValidationError):
        DifferentialResult.model_validate(payload)


def test_aggregate_counts_statuses_and_false_outcomes_without_task_success_taxonomy() -> None:
    records = [
        _classify(),
        _classify(
            fixture_id="dirty-board",
            fixture_hash="sha256:" + "e" * 64,
            custom_result_hash=CUSTOM_HASH,
            native_pass=False,
            custom_pass=True,
        ),
        _classify(
            fixture_id="future-only",
            fixture_hash="sha256:" + "f" * 64,
            authority_available=False,
            native_result_hash=None,
            native_pass=None,
            reason="Native authority unavailable.",
        ),
        _classify(
            fixture_id="broken-env",
            fixture_hash="sha256:" + "1" * 64,
            infrastructure_valid=False,
            native_result_hash=None,
            custom_result_hash=None,
            native_pass=None,
            custom_pass=None,
            reason="Canary infrastructure invalid.",
        ),
    ]

    report = aggregate_differential_results(records)

    assert report.schema_version == DIFFERENTIAL_REPORT_SCHEMA_VERSION
    assert report.source_sha == SOURCE_SHA
    assert report.lane == "stable"
    assert report.kicad_version == "10.0.6"
    assert report.results_total == 4
    assert report.match_count == 1
    assert report.divergence_count == 1
    assert report.unavailable_authority_count == 1
    assert report.infrastructure_invalid_count == 1
    assert report.false_pass_count == 1
    assert report.false_fail_count == 0
    assert not hasattr(report, "task_success")


def test_aggregate_rejects_mixed_source_lane_or_kicad_version() -> None:
    baseline = _classify()

    for other in (
        _classify(source_sha="2" * 40),
        _classify(lane="preview"),
        _classify(kicad_version="11.0.0"),
    ):
        with pytest.raises(ValueError, match="same source SHA, lane, and KiCad version"):
            aggregate_differential_results([baseline, other])


def test_json_report_is_deterministic_and_sanitized() -> None:
    report = aggregate_differential_results([_classify()])
    rendered = render_differential_report_json(report)

    assert rendered.endswith("\n")
    payload = json.loads(rendered)
    assert payload["schema_version"] == DIFFERENTIAL_REPORT_SCHEMA_VERSION
    assert payload["results"][0]["schema_version"] == DIFFERENTIAL_RESULT_SCHEMA_VERSION
    assert rendered == render_differential_report_json(report)

    sensitive = _classify(fixture_id="/home/private/fixture")
    with pytest.raises(ValueError, match="sensitive string"):
        render_differential_report_json(aggregate_differential_results([sensitive]))


def test_eval_package_exports_differential_reporting_surface() -> None:
    assert evals.DIFFERENTIAL_RESULT_SCHEMA_VERSION == DIFFERENTIAL_RESULT_SCHEMA_VERSION
    assert evals.DIFFERENTIAL_REPORT_SCHEMA_VERSION == DIFFERENTIAL_REPORT_SCHEMA_VERSION
    assert evals.classify_differential_result is classify_differential_result
    assert evals.aggregate_differential_results is aggregate_differential_results
    assert evals.render_differential_report_json is render_differential_report_json


def test_result_schema_rejects_inconsistent_semantic_evidence() -> None:
    payload = _classify(custom_result_hash=CUSTOM_HASH).model_dump(mode="json")
    payload["custom_result_hash"] = payload["native_result_hash"]
    with pytest.raises(ValidationError, match="divergence requires different"):
        DifferentialResult.model_validate(payload)

    payload = _classify(
        authority_available=False,
        native_result_hash=None,
        native_pass=None,
        reason="Native authority unavailable.",
    ).model_dump(mode="json")
    payload["reason"] = None
    with pytest.raises(ValidationError, match="requires a reason"):
        DifferentialResult.model_validate(payload)

    payload["reason"] = "Native authority unavailable."
    payload["native_result_hash"] = NATIVE_HASH
    with pytest.raises(ValidationError, match="cannot carry native authority evidence"):
        DifferentialResult.model_validate(payload)

    payload = _classify(
        custom_result_hash=CUSTOM_HASH,
        native_pass=False,
        custom_pass=True,
    ).model_dump(mode="json")
    payload["false_pass"] = False
    with pytest.raises(ValidationError, match="false_pass must reflect"):
        DifferentialResult.model_validate(payload)

    payload = _classify(
        custom_result_hash=CUSTOM_HASH,
        native_pass=True,
        custom_pass=False,
    ).model_dump(mode="json")
    payload["false_fail"] = False
    with pytest.raises(ValidationError, match="false_fail must reflect"):
        DifferentialResult.model_validate(payload)

    payload = _classify().model_dump(mode="json")
    payload["custom_pass"] = False
    with pytest.raises(ValidationError, match="match cannot carry conflicting"):
        DifferentialResult.model_validate(payload)


def test_result_schema_rejects_remaining_invalid_flag_and_hash_states() -> None:
    payload = _classify(
        custom_result_hash=CUSTOM_HASH,
        native_pass=False,
        custom_pass=True,
    ).model_dump(mode="json")
    payload["false_fail"] = True
    with pytest.raises(ValidationError, match="cannot both be true"):
        DifferentialResult.model_validate(payload)

    payload = _classify().model_dump(mode="json")
    payload["native_result_hash"] = None
    with pytest.raises(ValidationError, match="requires native and custom result hashes"):
        DifferentialResult.model_validate(payload)


def test_report_validator_rejects_non_partitioning_constructed_statuses() -> None:
    invalid_result = DifferentialResult.model_construct(
        source_sha=SOURCE_SHA,
        lane="stable",
        kicad_version="10.0.6",
        fixture_id="constructed-invalid",
        fixture_hash=FIXTURE_HASH,
        operation="connectivity.net-compilation",
        authority="fixture",
        comparison_method="fixture",
        status="not-a-real-status",
    )
    report = evals.DifferentialReport.model_construct(
        source_sha=SOURCE_SHA,
        lane="stable",
        kicad_version="10.0.6",
        results_total=1,
        match_count=0,
        divergence_count=0,
        unavailable_authority_count=0,
        infrastructure_invalid_count=0,
        false_pass_count=0,
        false_fail_count=0,
        results=(invalid_result,),
    )

    with pytest.raises(ValueError, match="status counts must partition"):
        report._validate_counts()


def test_classifier_rejects_inconsistent_authority_inputs() -> None:
    with pytest.raises(ValueError, match="Unavailable native authority"):
        _classify(authority_available=False, reason="Unavailable")

    with pytest.raises(ValueError, match="hashes are required"):
        _classify(native_result_hash=None)


def test_aggregate_and_report_schema_reject_inconsistent_counts() -> None:
    with pytest.raises(ValueError, match="At least one differential result"):
        aggregate_differential_results([])

    report_payload = aggregate_differential_results([_classify()]).model_dump(mode="json")
    report_payload["results_total"] = 2
    with pytest.raises(ValidationError, match="results_total"):
        evals.DifferentialReport.model_validate(report_payload)

    report_payload = aggregate_differential_results([_classify()]).model_dump(mode="json")
    report_payload["match_count"] = 0
    report_payload["divergence_count"] = 1
    with pytest.raises(ValidationError, match="match_count does not match"):
        evals.DifferentialReport.model_validate(report_payload)
