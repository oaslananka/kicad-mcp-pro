from __future__ import annotations

import json

import pytest

import kicad_mcp.evals.geometry_differential as geometry
from kicad_mcp.evals.geometry_differential import (
    GEOMETRY_AUTHORITY,
    GEOMETRY_COMPARISON_METHOD,
    GEOMETRY_OPERATION,
    classify_geometry_differential,
    geometry_signature_hash,
    normalize_custom_outline_bounds,
    normalize_native_board_stats,
)

SOURCE_SHA = "a" * 40
FIXTURE_HASH = "sha256:" + "b" * 64

NATIVE_STATS = """PCB statistics report
=====================
Board
-----
- Width: 100.0000 mm
- Height: 60.0000 mm
- Area: 6000.00 mm²
- Min track width: 0.2000 mm
"""


def test_native_and_custom_outline_geometry_normalize_at_native_precision() -> None:
    native = normalize_native_board_stats(NATIVE_STATS)
    custom = normalize_custom_outline_bounds((10.0, 20.0, 110.0, 80.0))

    assert native == custom == ("100.0000", "60.0000")
    assert geometry_signature_hash(native) == geometry_signature_hash(custom)


def test_native_json_ignores_localized_report_labels_and_preserves_geometry_hash() -> None:
    # A Turkish Windows KiCad installation localizes the text labels, while
    # --format json emits stable board.width/board.height field names.
    native_json = (
        '{"metadata":{"board_name":"clean-led-kicad10"},'
        '"board":{"has_outline":true,"width":"100.0000 mm",'
        '"height":"60.0000 mm"},"pads":{"delik_içinden":0}}'
    )
    assert normalize_native_board_stats(native_json) == ("100.0000", "60.0000")
    assert geometry_signature_hash(normalize_native_board_stats(native_json)) == (
        geometry_signature_hash(normalize_native_board_stats(NATIVE_STATS))
    )


@pytest.mark.parametrize(
    ("width", "height"),
    [
        ("100,0000 mm", "60,0000 mm"),
        ("100.0000 mm", "60,0000 mm"),
        ("100,0000 mm", "60.0000 mm"),
    ],
)
def test_native_json_accepts_single_locale_decimal_separator(width: str, height: str) -> None:
    report = json.dumps({"board": {"has_outline": True, "width": width, "height": height}})
    normalized = normalize_native_board_stats(report)
    assert normalized == ("100.0000", "60.0000")
    assert geometry_signature_hash(normalized) == geometry_signature_hash(
        normalize_native_board_stats(NATIVE_STATS)
    )


def test_native_json_rejects_invalid_or_ambiguous_board_dimensions() -> None:
    reports = (
        "[]",
        '{"board":{"has_outline":true,"width":"100 mm","height":"60 in"}}',
        '{"board":{"has_outline":true,"width":"100.000,0 mm","height":"60 mm"}}',
        '{"board":{"has_outline":true,"width":"100,000.0 mm","height":"60 mm"}}',
        '{"board":{"has_outline":true,"width":"1,234,567 mm","height":"60 mm"}}',
        '{"board":{"has_outline":false,"width":"100 mm","height":"60 mm"}}',
        '{"board":{"has_outline":true,"width":"100 mm","width":"101 mm","height":"60 mm"}}',
        '{"board":{"has_outline":true,"width":"0 mm","height":"60 mm"}}',
        '{"board":{"has_outline":true,"width":100,"height":"60 mm"}}',
        '{"board":{"has_outline":true,"width":"100 mm","height":"60 mm"}',
    )
    for report in reports:
        with pytest.raises(ValueError):
            normalize_native_board_stats(report)


def test_geometry_classifier_detects_seeded_width_divergence() -> None:
    result = classify_geometry_differential(
        source_sha=SOURCE_SHA,
        lane="stable",
        kicad_version="10.0.6",
        fixture_id="clean-led-kicad10",
        fixture_hash=FIXTURE_HASH,
        native_stats_text=NATIVE_STATS,
        custom_outline_bounds=(10.0, 20.0, 109.5, 80.0),
    )

    assert result.status == "divergence"
    assert result.native_result_hash != result.custom_result_hash
    assert result.operation == GEOMETRY_OPERATION
    assert result.authority == GEOMETRY_AUTHORITY
    assert result.comparison_method == GEOMETRY_COMPARISON_METHOD
    assert result.false_pass is False
    assert result.false_fail is False


def test_geometry_classifier_fails_closed_when_native_authority_is_unavailable() -> None:
    result = classify_geometry_differential(
        source_sha=SOURCE_SHA,
        lane="stable",
        kicad_version="10.0.6",
        fixture_id="clean-led-kicad10",
        fixture_hash=FIXTURE_HASH,
        native_stats_text=None,
        custom_outline_bounds=(0.0, 0.0, 100.0, 60.0),
        authority_available=False,
        reason="KiCad board statistics export unavailable.",
    )

    assert result.status == "unavailable-authority"
    assert result.native_result_hash is None
    assert result.custom_result_hash is not None
    assert result.reason == "KiCad board statistics export unavailable."


def test_geometry_classifier_reports_infrastructure_invalid_without_fabricated_hashes() -> None:
    result = classify_geometry_differential(
        source_sha=SOURCE_SHA,
        lane="stable",
        kicad_version="10.0.6",
        fixture_id="clean-led-kicad10",
        fixture_hash=FIXTURE_HASH,
        native_stats_text=None,
        custom_outline_bounds=None,
        infrastructure_valid=False,
        reason="Geometry parser failed.",
    )

    assert result.status == "infrastructure-invalid"
    assert result.native_result_hash is None
    assert result.custom_result_hash is None
    assert result.reason == "Geometry parser failed."


def test_geometry_normalizers_reject_missing_ambiguous_or_invalid_facts() -> None:
    missing_width = NATIVE_STATS.replace("- Width: 100.0000 mm\n", "")
    with pytest.raises(ValueError, match="exactly one Width"):
        normalize_native_board_stats(missing_width)

    duplicate_width = NATIVE_STATS + "- Width: 100.0000 mm\n"
    with pytest.raises(ValueError, match="exactly one Width"):
        normalize_native_board_stats(duplicate_width)

    with pytest.raises(ValueError, match="positive width and height"):
        normalize_custom_outline_bounds((10.0, 20.0, 10.0, 80.0))

    with pytest.raises(ValueError, match="required for a valid comparison"):
        classify_geometry_differential(
            source_sha=SOURCE_SHA,
            lane="stable",
            kicad_version="10.0.6",
            fixture_id="clean-led-kicad10",
            fixture_hash=FIXTURE_HASH,
            native_stats_text=NATIVE_STATS,
            custom_outline_bounds=None,
        )


def test_geometry_normalization_rejects_non_numeric_and_sub_precision_dimensions() -> None:
    class FloatableButNotDecimal:
        def __float__(self) -> float:
            return 1.0

        def __str__(self) -> str:
            return "not-a-decimal"

    with pytest.raises(ValueError, match="finite numeric millimetre values"):
        geometry._canonical_mm(object())

    bad_float = FloatableButNotDecimal()
    with pytest.raises(ValueError, match="finite numeric millimetre values"):
        geometry._canonical_mm(bad_float)

    with pytest.raises(ValueError, match="positive width and height"):
        geometry._canonical_mm(0.00001)


def test_geometry_normalizer_rejects_missing_outline_bounds() -> None:
    with pytest.raises(ValueError, match="did not produce board outline bounds"):
        normalize_custom_outline_bounds(None)


def test_geometry_classifier_requires_native_stats_when_authority_is_available() -> None:
    with pytest.raises(ValueError, match="Native KiCad board statistics are required"):
        classify_geometry_differential(
            source_sha=SOURCE_SHA,
            lane="stable",
            kicad_version="10.0.6",
            fixture_id="clean-led-kicad10",
            fixture_hash=FIXTURE_HASH,
            native_stats_text=None,
            custom_outline_bounds=(0.0, 0.0, 100.0, 60.0),
        )
