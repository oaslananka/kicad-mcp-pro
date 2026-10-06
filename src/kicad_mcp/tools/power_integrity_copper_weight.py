"""Thin FastMCP adapter for routed-copper current-capacity analysis."""

# pyright: reportUnusedFunction=false

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, cast

from kipy.proto.board.board_types_pb2 import BoardLayer
from mcp.server.mcpserver import MCPServer as FastMCP

from ..connection import get_board
from ..models.power_integrity import CopperWeightCheckInput
from ..models.verdict import VerdictReport
from ..pcb.board_access import board_tracks
from ..pcb.geometry import track_segment_length_mm
from ..power_integrity.copper_weight import (
    CopperTrackObservation,
    PowerIntegrityCopperWeightService,
)
from ..utils.impedance import copper_thickness_mm
from ..utils.units import nm_to_mm


class _TrackLike(Protocol):
    start: object
    end: object
    width: int
    layer: BoardLayer.ValueType
    net: object


TrackProvider = Callable[[str], list[CopperTrackObservation]]


def _layer_copper_thickness_mm(layer_value: BoardLayer.ValueType, stackup: object) -> float:
    for layer in getattr(stackup, "layers", []):
        if getattr(layer, "layer", None) == layer_value:
            thickness_nm = int(getattr(layer, "thickness", 0))
            if thickness_nm > 0:
                return nm_to_mm(thickness_nm)
    return copper_thickness_mm(1.0)


def _copper_track_observations(net_name: str) -> list[CopperTrackObservation]:
    board = get_board()
    stackup = board.get_stackup()
    observations: list[CopperTrackObservation] = []
    for track in cast(list[_TrackLike], board_tracks(board)):
        track_net = str(getattr(getattr(track, "net", None), "name", "") or "")
        if track_net != net_name:
            continue
        observations.append(
            CopperTrackObservation(
                width_mm=nm_to_mm(int(track.width)),
                length_mm=track_segment_length_mm(track),
                copper_thickness_mm=_layer_copper_thickness_mm(track.layer, stackup),
                external=track.layer in {BoardLayer.BL_F_Cu, BoardLayer.BL_B_Cu},
            )
        )
    return observations


def register(
    mcp: FastMCP,
    service: PowerIntegrityCopperWeightService | None = None,
    *,
    track_provider: TrackProvider = _copper_track_observations,
) -> None:
    """Register routed-copper current-capacity tools."""
    copper_service = service or PowerIntegrityCopperWeightService()

    @mcp.tool()
    def pdn_check_copper_weight(
        net_name: str,
        expected_current_a: float,
        ambient_temp_c: float = 25.0,
        max_temp_rise_c: float = 10.0,
    ) -> VerdictReport:
        """Check whether the routed copper for a net looks sufficient for the load current."""
        payload = CopperWeightCheckInput(
            net_name=net_name,
            expected_current_a=expected_current_a,
            ambient_temp_c=ambient_temp_c,
            max_temp_rise_c=max_temp_rise_c,
        )
        return copper_service.analyze(payload, track_provider(payload.net_name))
