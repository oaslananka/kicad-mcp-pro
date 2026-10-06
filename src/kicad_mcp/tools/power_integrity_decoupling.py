"""Thin FastMCP adapter for PDN decoupling recommendations."""

# pyright: reportUnusedFunction=false

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import cast

from mcp.server.mcpserver import MCPServer as FastMCP

from ..config import get_config
from ..connection import get_board
from ..models.common import _FootprintLike
from ..models.power_integrity import DecouplingRecommendationInput
from ..pcb.board_access import board_footprints
from ..pcb.geometry import point_xy_mm
from ..power_integrity.decoupling import CapacitorCandidate, PowerIntegrityDecouplingService
from ..utils.impedance import recommended_decoupling_distance_mm

FootprintsProvider = Callable[[], list[_FootprintLike]]
RecommendedDistanceProvider = Callable[[float], float]
MaxItemsProvider = Callable[[], int]


def _footprint_reference(footprint: _FootprintLike) -> str:
    return str(footprint.reference_field.text.value)


def _footprint_value(footprint: _FootprintLike) -> str:
    return str(footprint.value_field.text.value)


def _nearest_capacitors(
    reference: str,
    footprints: list[_FootprintLike],
) -> list[CapacitorCandidate]:
    anchor = next(
        (footprint for footprint in footprints if _footprint_reference(footprint) == reference),
        None,
    )
    if anchor is None:
        return []

    source_x_mm, source_y_mm = point_xy_mm(anchor.position)
    matches: list[CapacitorCandidate] = []
    for footprint in footprints:
        candidate_ref = _footprint_reference(footprint)
        if candidate_ref == reference or not candidate_ref.upper().startswith("C"):
            continue
        x_mm, y_mm = point_xy_mm(footprint.position)
        matches.append(
            (
                candidate_ref,
                math.hypot(source_x_mm - x_mm, source_y_mm - y_mm),
                _footprint_value(footprint),
            )
        )
    return sorted(matches, key=lambda item: item[1])


@dataclass(frozen=True)
class PowerIntegrityDecouplingDependencies:
    service: PowerIntegrityDecouplingService
    footprints_provider: FootprintsProvider
    recommended_distance_provider: RecommendedDistanceProvider
    max_items_provider: MaxItemsProvider


def _default_dependencies() -> PowerIntegrityDecouplingDependencies:
    return PowerIntegrityDecouplingDependencies(
        service=PowerIntegrityDecouplingService(),
        footprints_provider=lambda: cast(list[_FootprintLike], board_footprints(get_board())),
        recommended_distance_provider=lambda frequency_mhz: recommended_decoupling_distance_mm(
            frequency_mhz
        ),
        max_items_provider=lambda: get_config().max_items_per_response,
    )


def register(
    mcp: FastMCP,
    dependencies: PowerIntegrityDecouplingDependencies | None = None,
) -> None:
    """Register PDN decoupling recommendation tools."""
    deps = dependencies or _default_dependencies()

    @mcp.tool()
    def pdn_recommend_decoupling_caps(
        ic_refs: list[str],
        vcc_net: str,
        supply_voltage_v: float,
        target_ripple_mv: float = 20.0,
    ) -> str:
        """Recommend local and bulk decoupling from a simple PDN heuristic."""
        payload = DecouplingRecommendationInput(
            ic_refs=ic_refs,
            vcc_net=vcc_net,
            supply_voltage_v=supply_voltage_v,
            target_ripple_mv=target_ripple_mv,
        )
        references = payload.ic_refs[: deps.max_items_provider()]
        recommendation_mm = deps.recommended_distance_provider(200.0)
        footprints = deps.footprints_provider()
        nearby_by_ref = {
            reference: _nearest_capacitors(reference, footprints) for reference in references
        }
        return deps.service.recommend(
            payload=payload,
            references=references,
            recommendation_mm=recommendation_mm,
            nearby_by_ref=nearby_by_ref,
        )
