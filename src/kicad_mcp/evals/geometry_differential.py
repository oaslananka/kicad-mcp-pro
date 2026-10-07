"""Board-geometry normalization for native KiCad semantic differentials."""

from __future__ import annotations

import hashlib
import json
import math
import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from .semantic_differential import (
    DifferentialLane,
    DifferentialResult,
    classify_differential_result,
)

GEOMETRY_OPERATION = "geometry.board-outline-size"
GEOMETRY_AUTHORITY = "kicad-cli:pcb-export-stats"
GEOMETRY_COMPARISON_METHOD = "board-outline-width-height-0.0001mm-sha256.v1"

GeometryScalar = str | int | float | Decimal
GeometrySignature = tuple[str, str]
_NATIVE_FACT = re.compile(
    r"^-\s+(?P<name>Width|Height):\s+"
    r"(?P<value>[+-]?(?:\d+(?:\.\d*)?|\.\d+))\s+mm\s*$",
    re.MULTILINE,
)
_NATIVE_PRECISION_MM = Decimal("0.0001")


def _canonical_mm(value: GeometryScalar) -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Geometry dimensions must be finite numeric millimetre values") from exc
    if not math.isfinite(numeric) or numeric <= 0.0:
        raise ValueError("Geometry requires positive width and height")
    try:
        decimal = Decimal(str(value)).quantize(_NATIVE_PRECISION_MM, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Geometry dimensions must be finite numeric millimetre values") from exc
    if decimal <= 0:
        raise ValueError("Geometry requires positive width and height")
    return format(decimal, ".4f")


def normalize_native_board_stats(stats_text: str) -> GeometrySignature:
    """Normalize KiCad board-stat width/height facts at native report precision."""
    values: dict[str, list[str]] = {"Width": [], "Height": []}
    for match in _NATIVE_FACT.finditer(stats_text):
        values[match.group("name")].append(match.group("value"))
    for name in ("Width", "Height"):
        if len(values[name]) != 1:
            raise ValueError(f"Native board statistics require exactly one {name} fact")
    return _canonical_mm(values["Width"][0]), _canonical_mm(values["Height"][0])


def normalize_custom_outline_bounds(
    bounds: tuple[float, float, float, float] | None,
) -> GeometrySignature:
    """Normalize MCP Pro file-backed Edge.Cuts bounds into width/height facts."""
    if bounds is None:
        raise ValueError("Custom Edge.Cuts parser did not produce board outline bounds")
    min_x_mm, min_y_mm, max_x_mm, max_y_mm = bounds
    return _canonical_mm(max_x_mm - min_x_mm), _canonical_mm(max_y_mm - min_y_mm)


def geometry_signature_hash(signature: GeometrySignature) -> str:
    """Hash normalized width/height facts deterministically."""
    width_mm, height_mm = signature
    canonical = json.dumps(
        {"height_mm": height_mm, "width_mm": width_mm},
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(canonical).hexdigest()}"


def classify_geometry_differential(
    *,
    source_sha: str,
    lane: DifferentialLane,
    kicad_version: str,
    fixture_id: str,
    fixture_hash: str,
    native_stats_text: str | None,
    custom_outline_bounds: tuple[float, float, float, float] | None,
    authority_available: bool = True,
    infrastructure_valid: bool = True,
    reason: str | None = None,
) -> DifferentialResult:
    """Classify native board-stat bounds against file-backed Edge.Cuts bounds."""
    if not infrastructure_valid:
        return classify_differential_result(
            source_sha=source_sha,
            lane=lane,
            kicad_version=kicad_version,
            fixture_id=fixture_id,
            fixture_hash=fixture_hash,
            operation=GEOMETRY_OPERATION,
            authority=GEOMETRY_AUTHORITY,
            comparison_method=GEOMETRY_COMPARISON_METHOD,
            native_result_hash=None,
            custom_result_hash=None,
            authority_available=authority_available,
            infrastructure_valid=False,
            reason=reason or "Geometry differential infrastructure is invalid.",
        )

    if custom_outline_bounds is None:
        raise ValueError("Custom outline bounds are required for a valid comparison")
    custom_signature = normalize_custom_outline_bounds(custom_outline_bounds)
    custom_hash = geometry_signature_hash(custom_signature)

    if not authority_available:
        return classify_differential_result(
            source_sha=source_sha,
            lane=lane,
            kicad_version=kicad_version,
            fixture_id=fixture_id,
            fixture_hash=fixture_hash,
            operation=GEOMETRY_OPERATION,
            authority=GEOMETRY_AUTHORITY,
            comparison_method=GEOMETRY_COMPARISON_METHOD,
            native_result_hash=None,
            custom_result_hash=custom_hash,
            authority_available=False,
            reason=reason or "KiCad native board statistics authority is unavailable.",
        )

    if native_stats_text is None:
        raise ValueError("Native KiCad board statistics are required when authority is available")
    native_hash = geometry_signature_hash(normalize_native_board_stats(native_stats_text))
    return classify_differential_result(
        source_sha=source_sha,
        lane=lane,
        kicad_version=kicad_version,
        fixture_id=fixture_id,
        fixture_hash=fixture_hash,
        operation=GEOMETRY_OPERATION,
        authority=GEOMETRY_AUTHORITY,
        comparison_method=GEOMETRY_COMPARISON_METHOD,
        native_result_hash=native_hash,
        custom_result_hash=custom_hash,
    )


__all__ = [
    "GEOMETRY_AUTHORITY",
    "GEOMETRY_COMPARISON_METHOD",
    "GEOMETRY_OPERATION",
    "GeometrySignature",
    "classify_geometry_differential",
    "geometry_signature_hash",
    "normalize_custom_outline_bounds",
    "normalize_native_board_stats",
]
