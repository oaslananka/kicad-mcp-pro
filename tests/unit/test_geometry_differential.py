from __future__ import annotations

import pytest

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
    with pytest.raises(ValueError, match="exactly one Width"):
        normalize_native_board_stats(NATIVE_STATS.replace("- Width: 100.0000 mm\n", ""))

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
