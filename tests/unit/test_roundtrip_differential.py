from __future__ import annotations

from pathlib import Path

from kicad_mcp.evals.roundtrip_differential import (
    ROUNDTRIP_AUTHORITY,
    ROUNDTRIP_COMPARISON_METHOD,
    ROUNDTRIP_OPERATION,
    RoundTripSnapshot,
    classify_roundtrip_differential,
    hash_roundtrip_fixture,
    roundtrip_snapshot_hash,
)

SOURCE_SHA = "a" * 40
FIXTURE_HASH = "sha256:" + "b" * 64


def _snapshot(*, tracks: int = 2) -> RoundTripSnapshot:
    return RoundTripSnapshot(
        footprint_count=3,
        track_count=tracks,
        via_count=1,
        zone_count=1,
        net_names=("3V3", "GND"),
    )


def test_roundtrip_snapshot_hash_is_order_stable_for_named_nets() -> None:
    first = RoundTripSnapshot(3, 2, 1, 1, ("GND", "3V3", "GND", ""))
    second = RoundTripSnapshot(3, 2, 1, 1, ("3V3", "GND"))

    assert roundtrip_snapshot_hash(first) == roundtrip_snapshot_hash(second)


def test_roundtrip_classifier_matches_equal_native_and_custom_snapshots() -> None:
    result = classify_roundtrip_differential(
        source_sha=SOURCE_SHA,
        lane="preview",
        kicad_version="11.0.0",
        fixture_id="clean-led-kicad10",
        fixture_hash=FIXTURE_HASH,
        native_snapshot=_snapshot(),
        custom_snapshot=_snapshot(),
    )

    assert result.status == "match"
    assert result.operation == ROUNDTRIP_OPERATION
    assert result.authority == ROUNDTRIP_AUTHORITY
    assert result.comparison_method == ROUNDTRIP_COMPARISON_METHOD
    assert result.native_result_hash == result.custom_result_hash


def test_roundtrip_classifier_detects_seeded_semantic_divergence() -> None:
    result = classify_roundtrip_differential(
        source_sha=SOURCE_SHA,
        lane="preview",
        kicad_version="11.0.0",
        fixture_id="clean-led-kicad10",
        fixture_hash=FIXTURE_HASH,
        native_snapshot=_snapshot(tracks=3),
        custom_snapshot=_snapshot(tracks=2),
    )

    assert result.status == "divergence"
    assert result.native_result_hash != result.custom_result_hash
    assert result.false_pass is False
    assert result.false_fail is False


def test_roundtrip_classifier_fails_closed_without_native_authority() -> None:
    result = classify_roundtrip_differential(
        source_sha=SOURCE_SHA,
        lane="preview",
        kicad_version="10.99.0",
        fixture_id="clean-led-kicad10",
        fixture_hash=FIXTURE_HASH,
        native_snapshot=None,
        custom_snapshot=None,
        authority_available=False,
        reason="headless IPC unavailable",
    )

    assert result.status == "unavailable-authority"
    assert result.native_result_hash is None
    assert result.custom_result_hash is None


def test_roundtrip_classifier_marks_probe_failure_infrastructure_invalid() -> None:
    result = classify_roundtrip_differential(
        source_sha=SOURCE_SHA,
        lane="preview",
        kicad_version="11.0.0",
        fixture_id="clean-led-kicad10",
        fixture_hash=FIXTURE_HASH,
        native_snapshot=None,
        custom_snapshot=None,
        infrastructure_valid=False,
        reason="reopen failed",
    )

    assert result.status == "infrastructure-invalid"
    assert result.reason == "reopen failed"


def test_roundtrip_fixture_hash_tracks_board_file_content(tmp_path: Path) -> None:
    board = tmp_path / "demo.kicad_pcb"
    board.write_text("(kicad_pcb (version 20250101))\n", encoding="utf-8")
    first = hash_roundtrip_fixture(board)
    board.write_text("(kicad_pcb (version 20250102))\n", encoding="utf-8")
    second = hash_roundtrip_fixture(board)

    assert first.startswith("sha256:")
    assert first != second
