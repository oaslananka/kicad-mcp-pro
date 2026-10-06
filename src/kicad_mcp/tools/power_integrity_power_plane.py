"""Thin FastMCP adapter and KiCad backend for power-plane generation."""

# pyright: reportUnusedFunction=false

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from typing import Protocol, cast

from kipy.board import Board
from kipy.board_types import Net, Zone
from kipy.geometry import PolyLineNode, Vector2
from kipy.proto.board.board_types_pb2 import BoardLayer
from mcp.server.mcpserver import MCPServer as FastMCP

from ..connection import get_board
from ..models.common import _FootprintLike
from ..models.power_integrity import PowerPlaneInput
from ..pcb.board_access import board_footprints, board_shapes, board_zones
from ..pcb.geometry import point_xy_mm
from ..pcb.live_edit_runtime import execute_live_board_mutation
from ..power_integrity.power_plane import PowerIntegrityPowerPlaneService, PowerPlaneBackend
from ..utils.layers import resolve_layer
from ..utils.units import mm_to_nm


class _ZoneLike(Protocol):
    name: str
    net: object
    layers: Iterable[BoardLayer.ValueType]


class _KiCadPowerPlaneBackend:
    def __init__(self, board: Board) -> None:
        self._board = board

    def resolve_layer(self, layer: str) -> int:
        return int(resolve_layer(layer))

    def is_supported_copper_layer(self, layer: int) -> bool:
        return layer in {int(BoardLayer.BL_F_Cu), int(BoardLayer.BL_B_Cu)}

    def zone_exists(self, net_name: str, layer: int) -> bool:
        for zone in cast(list[_ZoneLike], board_zones(self._board)):
            zone_net = str(getattr(getattr(zone, "net", None), "name", "") or "")
            zone_layers = [int(value) for value in getattr(zone, "layers", [])]
            if zone_net == net_name and layer in zone_layers:
                return True
        return False

    def plane_bounds(self) -> tuple[float, float, float, float] | None:
        edge_bounds = self._edge_cuts_bounds()
        return edge_bounds if edge_bounds is not None else self._footprint_bounds()

    def _edge_cuts_bounds(self) -> tuple[float, float, float, float] | None:
        xs: list[float] = []
        ys: list[float] = []
        for shape in board_shapes(self._board):
            if getattr(shape, "layer", None) != BoardLayer.BL_Edge_Cuts:
                continue
            for attr in ("start", "end", "top_left", "bottom_right", "center", "radius_point"):
                point = getattr(shape, attr, None)
                if point is None:
                    continue
                x_mm, y_mm = point_xy_mm(point)
                xs.append(x_mm)
                ys.append(y_mm)
        if xs and ys:
            return min(xs), min(ys), max(xs), max(ys)
        return None

    def _footprint_bounds(self) -> tuple[float, float, float, float] | None:
        footprints = cast(list[_FootprintLike], board_footprints(self._board))
        if not footprints:
            return None
        xs = [point_xy_mm(footprint.position)[0] for footprint in footprints]
        ys = [point_xy_mm(footprint.position)[1] for footprint in footprints]
        margin_mm = 5.0
        return min(xs) - margin_mm, min(ys) - margin_mm, max(xs) + margin_mm, max(ys) + margin_mm

    def create_plane(
        self,
        *,
        net_name: str,
        layer: int,
        clearance_mm: float,
        bounds: tuple[float, float, float, float],
    ) -> None:
        x1_mm, y1_mm, x2_mm, y2_mm = bounds
        zone = Zone()
        zone.name = f"{net_name}_PLANE"
        net = Net()
        net.name = net_name
        zone.net = net
        zone.proto.layers.append(layer)
        zone.clearance = mm_to_nm(clearance_mm)
        zone.min_thickness = mm_to_nm(0.25)
        zone.proto.outline.polygons.add()
        outline = zone.outline.outline
        outline.closed = True
        points = [
            (x1_mm + clearance_mm, y1_mm + clearance_mm),
            (x2_mm - clearance_mm, y1_mm + clearance_mm),
            (x2_mm - clearance_mm, y2_mm - clearance_mm),
            (x1_mm + clearance_mm, y2_mm - clearance_mm),
        ]
        for x_mm, y_mm in points:
            outline.append(PolyLineNode.from_point(Vector2.from_xy_mm(x_mm, y_mm)))

        def _create_power_plane(board: Board) -> Sequence[object]:
            created = list(board.create_items([zone]))
            board.refill_zones(block=True, max_poll_seconds=60.0)
            return created

        execute_live_board_mutation(
            "pdn_generate_power_plane",
            _create_power_plane,
            verifier=None,
        )


BackendFactory = Callable[[], PowerPlaneBackend]


def _default_backend() -> PowerPlaneBackend:
    return _KiCadPowerPlaneBackend(get_board())


def register(
    mcp: FastMCP,
    service: PowerIntegrityPowerPlaneService | None = None,
    *,
    backend_factory: BackendFactory = _default_backend,
) -> None:
    """Register power-plane generation tools."""
    power_plane_service = service or PowerIntegrityPowerPlaneService()

    @mcp.tool()
    def pdn_generate_power_plane(
        net_name: str,
        layer: str,
        clearance_mm: float = 0.5,
    ) -> str:
        """Generate a rectangular copper plane on the requested copper layer."""
        payload = PowerPlaneInput(net_name=net_name, layer=layer, clearance_mm=clearance_mm)
        return power_plane_service.generate(payload, backend_factory())
