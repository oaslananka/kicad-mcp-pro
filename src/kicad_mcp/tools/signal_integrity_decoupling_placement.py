"""Thin FastMCP adapter for decoupling placement analysis."""

# pyright: reportUnusedFunction=false

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import cast

from mcp.server.mcpserver import MCPServer as FastMCP

from ..connection import get_board
from ..models.common import _FootprintLike, _PadLike
from ..models.signal_integrity import DecouplingPlacementInput
from ..pcb.board_access import board_footprints, board_pads
from ..pcb.geometry import point_xy_mm
from ..signal_integrity.decoupling_placement import (
    CapacitorCandidate,
    SignalIntegrityDecouplingPlacementService,
)
from ..utils.impedance import recommended_decoupling_distance_mm

PowerAnchorProvider = Callable[[str, str], tuple[float, float]]
CapacitorProvider = Callable[[str, float, float], list[CapacitorCandidate]]
RecommendedDistanceProvider = Callable[[float], float]


def _footprint_reference(footprint: _FootprintLike) -> str:
    return str(footprint.reference_field.text.value)


def _footprint_value(footprint: _FootprintLike) -> str:
    return str(footprint.value_field.text.value)


def _find_footprint(reference: str) -> _FootprintLike | None:
    for footprint in cast(list[_FootprintLike], board_footprints(get_board())):
        if _footprint_reference(footprint) == reference:
            return footprint
    return None


def _find_power_anchor(ic_ref: str, power_pin: str) -> tuple[float, float]:
    for pad in cast(list[_PadLike], board_pads(get_board())):
        if _footprint_reference(pad.parent) == ic_ref and str(pad.number) == power_pin:
            return point_xy_mm(pad.position)

    footprint = _find_footprint(ic_ref)
    if footprint is None:
        raise ValueError(f"Footprint '{ic_ref}' was not found on the active board.")
    return point_xy_mm(footprint.position)


def _nearest_capacitors(
    source_ref: str,
    source_x_mm: float,
    source_y_mm: float,
) -> list[CapacitorCandidate]:
    matches: list[CapacitorCandidate] = []
    for footprint in cast(list[_FootprintLike], board_footprints(get_board())):
        reference = _footprint_reference(footprint)
        if reference == source_ref or not reference.upper().startswith("C"):
            continue
        x_mm, y_mm = point_xy_mm(footprint.position)
        distance_mm = math.hypot(source_x_mm - x_mm, source_y_mm - y_mm)
        matches.append((reference, distance_mm, _footprint_value(footprint)))
    return sorted(matches, key=lambda item: item[1])


@dataclass(frozen=True)
class SignalIntegrityDecouplingPlacementDependencies:
    service: SignalIntegrityDecouplingPlacementService
    anchor_provider: PowerAnchorProvider
    capacitor_provider: CapacitorProvider
    recommended_distance_provider: RecommendedDistanceProvider


def _default_dependencies() -> SignalIntegrityDecouplingPlacementDependencies:
    return SignalIntegrityDecouplingPlacementDependencies(
        service=SignalIntegrityDecouplingPlacementService(),
        anchor_provider=lambda ic_ref, power_pin: _find_power_anchor(ic_ref, power_pin),
        capacitor_provider=lambda ic_ref, x_mm, y_mm: _nearest_capacitors(ic_ref, x_mm, y_mm),
        recommended_distance_provider=lambda frequency_mhz: recommended_decoupling_distance_mm(
            frequency_mhz
        ),
    )


def register(
    mcp: FastMCP,
    dependencies: SignalIntegrityDecouplingPlacementDependencies | None = None,
) -> None:
    """Register decoupling placement analysis tools."""
    deps = dependencies or _default_dependencies()

    @mcp.tool()
    def si_calculate_decoupling_placement(
        ic_ref: str,
        power_pin: str,
        target_freq_mhz: float,
    ) -> str:
        """Estimate decoupling placement quality around an IC power pin."""
        payload = DecouplingPlacementInput(
            ic_ref=ic_ref,
            power_pin=power_pin,
            target_freq_mhz=target_freq_mhz,
        )
        source_x_mm, source_y_mm = deps.anchor_provider(payload.ic_ref, payload.power_pin)
        recommended_mm = deps.recommended_distance_provider(payload.target_freq_mhz)
        capacitors = deps.capacitor_provider(payload.ic_ref, source_x_mm, source_y_mm)
        return deps.service.analyze(
            payload=payload,
            source_x_mm=source_x_mm,
            source_y_mm=source_y_mm,
            recommended_mm=recommended_mm,
            capacitors=capacitors,
        )
