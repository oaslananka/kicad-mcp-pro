"""Thin FastMCP adapter for thermal copper-pour review."""

# pyright: reportUnusedFunction=false

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Protocol, cast

from kipy.proto.board.board_types_pb2 import BoardLayer
from mcp.server.mcpserver import MCPServer as FastMCP

from ..config import get_config
from ..connection import get_board
from ..models.power_integrity import ThermalPourInput
from ..models.verdict import VerdictReport
from ..pcb.board_access import board_zones
from ..power_integrity.thermal_pour import CopperPourObservation, PowerIntegrityThermalPourService


class _ZoneLike(Protocol):
    name: str
    net: object
    layers: Iterable[BoardLayer.ValueType]


PourProvider = Callable[[str], list[CopperPourObservation]]
MaxItemsProvider = Callable[[], int]


def _pour_observations(net_name: str) -> list[CopperPourObservation]:
    board = get_board()
    observations: list[CopperPourObservation] = []
    for zone in cast(list[_ZoneLike], board_zones(board)):
        zone_net = str(getattr(getattr(zone, "net", None), "name", "") or "")
        if zone_net != net_name:
            continue
        observations.append(
            CopperPourObservation(
                name=str(zone.name or ""),
                layers=tuple(BoardLayer.Name(layer) for layer in getattr(zone, "layers", [])),
            )
        )
    return observations


def register(
    mcp: FastMCP,
    service: PowerIntegrityThermalPourService | None = None,
    *,
    pour_provider: PourProvider = _pour_observations,
    max_items_provider: MaxItemsProvider = lambda: get_config().max_items_per_response,
) -> None:
    """Register thermal copper-pour review tools."""
    thermal_pour_service = service or PowerIntegrityThermalPourService()

    @mcp.tool()
    def thermal_check_copper_pour(
        net_name: str,
        expected_power_w: float,
        preferred_layer: str = "auto",
    ) -> VerdictReport:
        """Check whether the board already has copper pour support for the net."""
        payload = ThermalPourInput(
            net_name=net_name,
            expected_power_w=expected_power_w,
            preferred_layer=preferred_layer,
        )
        return thermal_pour_service.analyze(
            payload,
            pour_provider(payload.net_name),
            max_items=max_items_provider(),
        )
