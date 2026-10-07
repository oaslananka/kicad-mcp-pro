"""Pure normalization and hashing for KiCad connectivity semantic differentials."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Iterable, Mapping

from .semantic_differential import (
    DifferentialLane,
    DifferentialResult,
    classify_differential_result,
)

type Pin = tuple[str, str]
type PinGroup = tuple[Pin, ...]
type ConnectivitySignature = tuple[PinGroup, ...]


def _pin(reference: object, pin: object) -> Pin:
    ref = str(reference).strip()
    number = str(pin).strip()
    if not ref or not number:
        raise ValueError("Connectivity pin records require non-empty reference and pin values")
    return ref, number


def normalize_native_net_map(net_map: Mapping[tuple[str, str], str]) -> ConnectivitySignature:
    """Normalize KiCad-native net membership without relying on generated net names."""
    grouped: dict[str, set[Pin]] = defaultdict(set)
    for (reference, pin), net_name in net_map.items():
        name = str(net_name).strip()
        if not name:
            raise ValueError("Native connectivity records require a non-empty net identity")
        grouped[name].add(_pin(reference, pin))
    return tuple(sorted({tuple(sorted(pins)) for pins in grouped.values() if pins}))


def normalize_custom_connectivity_groups(
    groups: Iterable[Mapping[str, object]],
) -> ConnectivitySignature:
    """Normalize MCP Pro connectivity groups to the same pin-membership representation."""
    normalized: set[PinGroup] = set()
    seen_pins: set[Pin] = set()
    for group in groups:
        raw_pins = group.get("pins", [])
        if not isinstance(raw_pins, list | tuple):
            raise ValueError("Custom connectivity group pins must be a sequence")
        pins: set[Pin] = set()
        for raw_pin in raw_pins:
            if not isinstance(raw_pin, Mapping):
                raise ValueError("Custom connectivity pins must be mappings")
            pins.add(_pin(raw_pin.get("reference", ""), raw_pin.get("pin", "")))
        if pins:
            overlap = seen_pins.intersection(pins)
            if overlap:
                duplicate = sorted(overlap)[0]
                raise ValueError(
                    f"Pin {duplicate[0]}:{duplicate[1]} appears in multiple connectivity groups"
                )
            seen_pins.update(pins)
            normalized.add(tuple(sorted(pins)))
    return tuple(sorted(normalized))


def connectivity_signature_hash(signature: ConnectivitySignature) -> str:
    """Hash one normalized connectivity signature deterministically."""
    payload = json.dumps(signature, ensure_ascii=False, separators=(",", ":"))
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def build_connectivity_differential_result(
    *,
    source_sha: str,
    lane: DifferentialLane,
    kicad_version: str,
    fixture_id: str,
    fixture_hash: str,
    native_net_map: Mapping[tuple[str, str], str],
    custom_groups: Iterable[Mapping[str, object]],
) -> DifferentialResult:
    """Compare native KiCad and MCP Pro connectivity by normalized pin membership."""
    native_signature = normalize_native_net_map(native_net_map)
    custom_signature = normalize_custom_connectivity_groups(custom_groups)
    if not native_signature:
        raise ValueError("Native connectivity authority produced an empty signature")
    return classify_differential_result(
        source_sha=source_sha,
        lane=lane,
        kicad_version=kicad_version,
        fixture_id=fixture_id,
        fixture_hash=fixture_hash,
        operation="connectivity.net-compilation",
        authority="kicad-cli:sch-export-netlist-kicadsexpr",
        comparison_method="pin-membership-sha256.v1",
        native_result_hash=connectivity_signature_hash(native_signature),
        custom_result_hash=connectivity_signature_hash(custom_signature),
    )


__all__ = [
    "ConnectivitySignature",
    "Pin",
    "PinGroup",
    "build_connectivity_differential_result",
    "connectivity_signature_hash",
    "normalize_custom_connectivity_groups",
    "normalize_native_net_map",
]
