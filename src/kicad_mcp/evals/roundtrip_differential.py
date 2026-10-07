"""Native save/reopen versus MCP file-parser semantic differential helpers."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from .semantic_differential import (
    DifferentialLane,
    DifferentialResult,
    classify_differential_result,
)

ROUNDTRIP_OPERATION = "file-roundtrip.board-save-reopen"
ROUNDTRIP_AUTHORITY = "kicad-headless-ipc:save-as-reopen"
ROUNDTRIP_COMPARISON_METHOD = "board-semantic-inventory-sha256.v1"


@dataclass(frozen=True, slots=True)
class RoundTripSnapshot:
    """Normalized board semantics compared after a native save/reopen cycle."""

    footprint_count: int
    track_count: int
    via_count: int
    zone_count: int
    net_names: tuple[str, ...]

    def normalized(self) -> RoundTripSnapshot:
        counts = (
            self.footprint_count,
            self.track_count,
            self.via_count,
            self.zone_count,
        )
        if any(value < 0 for value in counts):
            raise ValueError("Round-trip semantic counts cannot be negative")
        nets = tuple(sorted({str(name).strip() for name in self.net_names if str(name).strip()}))
        return RoundTripSnapshot(*counts, nets)


def roundtrip_snapshot_hash(snapshot: RoundTripSnapshot) -> str:
    """Hash one normalized board semantic inventory deterministically."""
    normalized = snapshot.normalized()
    payload = {
        "footprint_count": normalized.footprint_count,
        "net_names": list(normalized.net_names),
        "track_count": normalized.track_count,
        "via_count": normalized.via_count,
        "zone_count": normalized.zone_count,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def hash_roundtrip_fixture(project_or_board: Path) -> str:
    """Hash the source board used for the native save/reopen comparison."""
    resolved = project_or_board.expanduser().resolve(strict=True)
    board = resolved if resolved.suffix == ".kicad_pcb" else resolved.with_suffix(".kicad_pcb")
    if not board.is_file():
        raise ValueError("Round-trip differential requires a .kicad_pcb fixture")
    digest = hashlib.sha256()
    name = board.name.encode("utf-8")
    content = board.read_bytes()
    digest.update(len(name).to_bytes(8, "big"))
    digest.update(name)
    digest.update(len(content).to_bytes(8, "big"))
    digest.update(content)
    return f"sha256:{digest.hexdigest()}"


def classify_roundtrip_differential(
    *,
    source_sha: str,
    lane: DifferentialLane,
    kicad_version: str,
    fixture_id: str,
    fixture_hash: str,
    native_snapshot: RoundTripSnapshot | None,
    custom_snapshot: RoundTripSnapshot | None,
    authority_available: bool = True,
    infrastructure_valid: bool = True,
    reason: str | None = None,
) -> DifferentialResult:
    """Classify native reopened semantics against MCP Pro's file-backed parser semantics."""
    if not infrastructure_valid:
        return classify_differential_result(
            source_sha=source_sha,
            lane=lane,
            kicad_version=kicad_version,
            fixture_id=fixture_id,
            fixture_hash=fixture_hash,
            operation=ROUNDTRIP_OPERATION,
            authority=ROUNDTRIP_AUTHORITY,
            comparison_method=ROUNDTRIP_COMPARISON_METHOD,
            native_result_hash=None,
            custom_result_hash=None,
            infrastructure_valid=False,
            reason=reason or "Round-trip differential infrastructure is invalid.",
        )

    if not authority_available:
        return classify_differential_result(
            source_sha=source_sha,
            lane=lane,
            kicad_version=kicad_version,
            fixture_id=fixture_id,
            fixture_hash=fixture_hash,
            operation=ROUNDTRIP_OPERATION,
            authority=ROUNDTRIP_AUTHORITY,
            comparison_method=ROUNDTRIP_COMPARISON_METHOD,
            native_result_hash=None,
            custom_result_hash=(
                roundtrip_snapshot_hash(custom_snapshot) if custom_snapshot is not None else None
            ),
            authority_available=False,
            reason=reason or "KiCad headless save/reopen authority is unavailable.",
        )

    if native_snapshot is None or custom_snapshot is None:
        raise ValueError("Native and custom round-trip snapshots are required for comparison")
    return classify_differential_result(
        source_sha=source_sha,
        lane=lane,
        kicad_version=kicad_version,
        fixture_id=fixture_id,
        fixture_hash=fixture_hash,
        operation=ROUNDTRIP_OPERATION,
        authority=ROUNDTRIP_AUTHORITY,
        comparison_method=ROUNDTRIP_COMPARISON_METHOD,
        native_result_hash=roundtrip_snapshot_hash(native_snapshot),
        custom_result_hash=roundtrip_snapshot_hash(custom_snapshot),
    )


__all__ = [
    "ROUNDTRIP_AUTHORITY",
    "ROUNDTRIP_COMPARISON_METHOD",
    "ROUNDTRIP_OPERATION",
    "RoundTripSnapshot",
    "classify_roundtrip_differential",
    "hash_roundtrip_fixture",
    "roundtrip_snapshot_hash",
]
