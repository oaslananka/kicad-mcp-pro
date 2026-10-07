"""Native KiCad manufacturing-export inventory semantic differential helpers."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ..export.inventory import (
    IPC2581_DEFAULT_NAME,
    discover_drill_output_files,
    discover_gerber_output_files,
)
from .semantic_differential import (
    DifferentialLane,
    DifferentialResult,
    classify_differential_result,
)

EXPORT_INVENTORY_OPERATION = "export.manufacturing-inventory"
EXPORT_INVENTORY_AUTHORITY = "kicad-cli:pcb-export-manufacturing-files"
EXPORT_INVENTORY_COMPARISON_METHOD = "manufacturing-category-basename-sha256.v1"

type InventoryEntry = tuple[str, str]
type InventorySignature = tuple[InventoryEntry, ...]


def _inventory_hash(signature: InventorySignature) -> str:
    payload = [{"category": category, "filename": filename} for category, filename in signature]
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _native_inventory(
    gerber_dir: Path,
    drill_dir: Path,
    ipc2581_path: Path,
) -> InventorySignature:
    if not gerber_dir.is_dir():
        raise ValueError("Native KiCad Gerber output directory is unavailable.")
    if not drill_dir.is_dir():
        raise ValueError("Native KiCad drill output directory is unavailable.")
    if not ipc2581_path.is_file():
        raise ValueError("Native KiCad IPC-2581 output is unavailable.")

    gerber_files = [path for path in sorted(gerber_dir.iterdir()) if path.is_file()]
    drill_files = [path for path in sorted(drill_dir.iterdir()) if path.is_file()]
    if not gerber_files:
        raise ValueError("Native KiCad Gerber export produced no files.")
    if not drill_files:
        raise ValueError("Native KiCad drill export produced no files.")

    records: list[InventoryEntry] = []
    records.extend(("gerber", path.name) for path in gerber_files)
    records.extend(("drill", path.name) for path in drill_files)
    records.append(("ipc2581", ipc2581_path.name))
    return tuple(sorted(records))


def _custom_inventory(
    gerber_dir: Path,
    drill_dir: Path,
    ipc2581_path: Path,
) -> InventorySignature:
    records: list[InventoryEntry] = []
    records.extend(("gerber", path.name) for path in discover_gerber_output_files(gerber_dir))
    records.extend(("drill", path.name) for path in discover_drill_output_files(drill_dir))
    if ipc2581_path.is_file() and ipc2581_path.name == IPC2581_DEFAULT_NAME:
        records.append(("ipc2581", ipc2581_path.name))
    return tuple(sorted(records))


def classify_export_inventory_differential(
    *,
    source_sha: str,
    lane: DifferentialLane,
    kicad_version: str,
    fixture_id: str,
    fixture_hash: str,
    gerber_dir: Path,
    drill_dir: Path,
    ipc2581_path: Path,
    authority_available: bool = True,
) -> DifferentialResult:
    """Compare native manufacturing outputs with MCP Pro's production inventory discovery."""
    if not authority_available:
        return classify_differential_result(
            source_sha=source_sha,
            lane=lane,
            kicad_version=kicad_version,
            fixture_id=fixture_id,
            fixture_hash=fixture_hash,
            operation=EXPORT_INVENTORY_OPERATION,
            authority=EXPORT_INVENTORY_AUTHORITY,
            comparison_method=EXPORT_INVENTORY_COMPARISON_METHOD,
            native_result_hash=None,
            custom_result_hash=None,
            authority_available=False,
            reason="Native KiCad manufacturing export authority is unavailable.",
        )

    try:
        native = _native_inventory(gerber_dir, drill_dir, ipc2581_path)
        custom = _custom_inventory(gerber_dir, drill_dir, ipc2581_path)
    except (OSError, ValueError) as exc:
        return classify_differential_result(
            source_sha=source_sha,
            lane=lane,
            kicad_version=kicad_version,
            fixture_id=fixture_id,
            fixture_hash=fixture_hash,
            operation=EXPORT_INVENTORY_OPERATION,
            authority=EXPORT_INVENTORY_AUTHORITY,
            comparison_method=EXPORT_INVENTORY_COMPARISON_METHOD,
            native_result_hash=None,
            custom_result_hash=None,
            infrastructure_valid=False,
            reason=f"Manufacturing export differential infrastructure failed: {exc}",
        )

    return classify_differential_result(
        source_sha=source_sha,
        lane=lane,
        kicad_version=kicad_version,
        fixture_id=fixture_id,
        fixture_hash=fixture_hash,
        operation=EXPORT_INVENTORY_OPERATION,
        authority=EXPORT_INVENTORY_AUTHORITY,
        comparison_method=EXPORT_INVENTORY_COMPARISON_METHOD,
        native_result_hash=_inventory_hash(native),
        custom_result_hash=_inventory_hash(custom),
    )


__all__ = [
    "EXPORT_INVENTORY_AUTHORITY",
    "EXPORT_INVENTORY_COMPARISON_METHOD",
    "EXPORT_INVENTORY_OPERATION",
    "classify_export_inventory_differential",
]
