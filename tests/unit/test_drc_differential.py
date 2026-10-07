from __future__ import annotations

import json
from pathlib import Path

import pytest

import kicad_mcp.evals.drc_differential as drc_diff
from kicad_mcp.evals.drc_differential import (
    DRC_AUTHORITY,
    DRC_COMPARISON_METHOD,
    DRC_OPERATION,
    compare_drc_report_file,
    hash_fixture_tree,
)

SOURCE_SHA = "a" * 40


def _fixture(tmp_path: Path) -> Path:
    fixture = tmp_path / "fixture"
    fixture.mkdir(parents=True)
    (fixture / "board.kicad_pcb").write_text("(kicad_pcb demo)\n", encoding="utf-8")
    (fixture / "board.kicad_pro").write_text('{"board": {}}\n', encoding="utf-8")
    return fixture


def _write_report(path: Path, payload: object) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _compare(tmp_path: Path, payload: object, **kwargs: object):
    tmp_path.mkdir(parents=True, exist_ok=True)
    fixture = _fixture(tmp_path)
    report = _write_report(tmp_path / "drc.json", payload)
    return compare_drc_report_file(
        report_path=report,
        fixture_path=fixture,
        source_sha=SOURCE_SHA,
        lane="stable",
        kicad_version="10.0.6",
        fixture_id="demo",
        **kwargs,
    )


def test_fixture_hash_is_deterministic_and_content_sensitive(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    first = hash_fixture_tree(fixture)
    assert first == hash_fixture_tree(fixture)
    assert first.startswith("sha256:")

    (fixture / "board.kicad_pcb").write_text("(kicad_pcb changed)\n", encoding="utf-8")
    assert hash_fixture_tree(fixture) != first


def test_fixture_hash_ignores_volatile_kicad_project_local_state(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    first = hash_fixture_tree(fixture)
    (fixture / "board.kicad_prl").write_text('{"board": {"active_layer": 1}}\n', encoding="utf-8")
    assert hash_fixture_tree(fixture) == first


def test_native_and_custom_drc_projection_match_type_and_severity_semantics(
    tmp_path: Path,
) -> None:
    result = _compare(
        tmp_path,
        {
            "violations": [
                {"type": "clearance", "severity": "error"},
                {"type": "silk_overlap", "severity": "warning"},
            ],
            "unconnected_items": [{"type": "unconnected_items", "severity": "error"}],
        },
    )

    assert result.status == "match"
    assert result.native_pass is False
    assert result.custom_pass is False
    assert result.operation == DRC_OPERATION
    assert result.authority == DRC_AUTHORITY
    assert result.comparison_method == DRC_COMPARISON_METHOD
    assert result.native_result_hash == result.custom_result_hash


def test_seeded_false_pass_and_false_fail_are_detected(tmp_path: Path) -> None:
    false_pass = _compare(
        tmp_path / "false-pass",
        {"violations": [{"type": "clearance", "severity": "error"}]},
        custom_classifier=lambda _report: ("clean", None),
    )
    false_fail = _compare(
        tmp_path / "false-fail",
        {"violations": []},
        custom_classifier=lambda _report: ("findings", None),
    )

    assert false_pass.status == "divergence"
    assert false_pass.false_pass is True
    assert false_pass.false_fail is False
    assert false_fail.status == "divergence"
    assert false_fail.false_pass is False
    assert false_fail.false_fail is True


def test_seeded_severity_normalization_divergence_is_detected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(drc_diff, "normalize_report_severity", lambda _value: "error")
    result = _compare(
        tmp_path,
        {"violations": [{"type": "silk_overlap", "severity": "warning"}]},
    )

    assert result.status == "divergence"
    assert result.native_pass is False
    assert result.custom_pass is False
    assert result.false_pass is False
    assert result.false_fail is False
    assert result.native_result_hash != result.custom_result_hash


def test_custom_parser_rejecting_native_valid_report_is_infrastructure_invalid(
    tmp_path: Path,
) -> None:
    result = _compare(
        tmp_path,
        {"violations": []},
        custom_classifier=lambda _report: ("malformed", "custom schema rejected native report"),
    )

    assert result.status == "infrastructure-invalid"
    assert result.native_result_hash is not None
    assert result.custom_result_hash is None
    assert result.native_pass is True
    assert result.custom_pass is None
    assert result.reason is not None
    assert "custom schema rejected native report" in result.reason


def test_missing_native_report_is_unavailable_authority(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    result = compare_drc_report_file(
        report_path=tmp_path / "missing.json",
        fixture_path=fixture,
        source_sha=SOURCE_SHA,
        lane="preview",
        kicad_version="11.0.0",
        fixture_id="demo",
    )

    assert result.status == "unavailable-authority"
    assert result.native_result_hash is None
    assert result.native_pass is None
    assert result.reason is not None
    assert "not produced" in result.reason


def test_invalid_native_json_and_schema_are_infrastructure_invalid(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    invalid_json = tmp_path / "invalid.json"
    invalid_json.write_text("{not-json", encoding="utf-8")
    malformed = _write_report(tmp_path / "malformed.json", {"violations": "bad"})

    invalid_json_result = compare_drc_report_file(
        report_path=invalid_json,
        fixture_path=fixture,
        source_sha=SOURCE_SHA,
        lane="stable",
        kicad_version="10.0.6",
        fixture_id="demo-invalid-json",
    )
    malformed_result = compare_drc_report_file(
        report_path=malformed,
        fixture_path=fixture,
        source_sha=SOURCE_SHA,
        lane="stable",
        kicad_version="10.0.6",
        fixture_id="demo-malformed",
    )

    assert invalid_json_result.status == "infrastructure-invalid"
    assert invalid_json_result.reason is not None
    assert "valid JSON" in invalid_json_result.reason
    assert malformed_result.status == "infrastructure-invalid"
    assert malformed_result.reason is not None
    assert "violations" in malformed_result.reason
