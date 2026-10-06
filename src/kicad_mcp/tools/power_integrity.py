"""Power-integrity and thermal heuristics for practical PCB review.

These are first-order estimates, not a substitute for a distributed IR-drop / current-
density solver or a thermal FEA tool. Use them as a fast first-pass review, not as
formal sign-off. Distributed PDN and thermal-network solvers are planned (P3-T2/P3-T4).
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from typing import Protocol, cast

from kipy.board import Board
from kipy.board_types import Net, Zone
from kipy.geometry import PolyLineNode, Vector2
from kipy.proto.board.board_types_pb2 import BoardLayer
from mcp.server.mcpserver import MCPServer as FastMCP

from ..config import get_config
from ..connection import get_board
from ..models.common import _FootprintLike
from ..models.power_integrity import PowerPlaneInput, ThermalPourInput
from ..models.verdict import Verdict, VerdictReport
from ..pcb.board_access import board_footprints, board_shapes, board_zones
from ..pcb.geometry import point_xy_mm
from ..pcb.live_edit_runtime import execute_live_board_mutation
from ..utils.layers import resolve_layer
from ..utils.units import mm_to_nm


class _ZoneLike(Protocol):
    name: str
    net: object
    layers: Iterable[BoardLayer.ValueType]


def _net(name: str) -> Net:
    net = Net()
    net.name = name
    return net


def _edge_cuts_bounds() -> tuple[float, float, float, float] | None:
    xs: list[float] = []
    ys: list[float] = []
    for shape in board_shapes(get_board()):
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


def _footprint_bounds() -> tuple[float, float, float, float] | None:
    footprints = cast(list[_FootprintLike], board_footprints(get_board()))
    if not footprints:
        return None
    xs = [point_xy_mm(footprint.position)[0] for footprint in footprints]
    ys = [point_xy_mm(footprint.position)[1] for footprint in footprints]
    margin_mm = 5.0
    return min(xs) - margin_mm, min(ys) - margin_mm, max(xs) + margin_mm, max(ys) + margin_mm


def _plane_bounds() -> tuple[float, float, float, float] | None:
    return _edge_cuts_bounds() or _footprint_bounds()


def _zone_already_exists(net_name: str, layer: BoardLayer.ValueType) -> bool:
    for zone in cast(list[_ZoneLike], board_zones(get_board())):
        zone_net = str(getattr(getattr(zone, "net", None), "name", "") or "")
        zone_layers = list(getattr(zone, "layers", []))
        if zone_net == net_name and layer in zone_layers:
            return True
    return False


def register(mcp: FastMCP) -> None:
    """Register power-integrity and thermal tools."""

    from . import (
        power_integrity_copper_weight,
        power_integrity_decoupling,
        power_integrity_pdn_mesh,
        power_integrity_thermal_plane,
        power_integrity_thermal_via,
        power_integrity_voltage_drop,
    )

    power_integrity_voltage_drop.register(mcp)

    power_integrity_pdn_mesh.register(mcp)

    power_integrity_decoupling.register(mcp)

    power_integrity_copper_weight.register(mcp)

    @mcp.tool()
    def pdn_generate_power_plane(net_name: str, layer: str, clearance_mm: float = 0.5) -> str:
        """Generate a rectangular copper plane on the requested copper layer."""
        payload = PowerPlaneInput(net_name=net_name, layer=layer, clearance_mm=clearance_mm)
        layer_value = resolve_layer(payload.layer)
        if layer_value not in {BoardLayer.BL_F_Cu, BoardLayer.BL_B_Cu}:
            return "Power plane generation currently supports only F_Cu and B_Cu."
        if _zone_already_exists(payload.net_name, layer_value):
            return f"A copper zone for '{payload.net_name}' already exists on {payload.layer}."

        bounds = _plane_bounds()
        if bounds is None:
            return (
                "Could not determine board bounds. Add an Edge.Cuts outline or at least one "
                "footprint before generating a power plane."
            )
        x1_mm, y1_mm, x2_mm, y2_mm = bounds
        zone = Zone()
        zone.name = f"{payload.net_name}_PLANE"
        zone.net = _net(payload.net_name)
        zone.proto.layers.append(layer_value)
        zone.clearance = mm_to_nm(payload.clearance_mm)
        zone.min_thickness = mm_to_nm(0.25)
        zone.proto.outline.polygons.add()
        outline = zone.outline.outline
        outline.closed = True
        points = [
            (x1_mm + payload.clearance_mm, y1_mm + payload.clearance_mm),
            (x2_mm - payload.clearance_mm, y1_mm + payload.clearance_mm),
            (x2_mm - payload.clearance_mm, y2_mm - payload.clearance_mm),
            (x1_mm + payload.clearance_mm, y2_mm - payload.clearance_mm),
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

        return (
            f"Generated a copper plane for '{payload.net_name}' on {payload.layer} "
            f"with {payload.clearance_mm:.3f} mm clearance."
        )

    power_integrity_thermal_via.register(mcp)

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
        zones = [
            zone
            for zone in cast(list[_ZoneLike], board_zones(get_board()))
            if str(getattr(getattr(zone, "net", None), "name", "") or "") == payload.net_name
        ]
        if not zones:
            message = (
                f"No copper pours were found for net '{payload.net_name}'. "
                "Add a pour or plane for thermal spreading before release."
            )
            return VerdictReport.from_text_verdict(
                text=message,
                summary=message,
                verdict="WARN",
                source="thermal_check_copper_pour",
                evidence=[{"net_name": payload.net_name, "matching_pours": 0}],
                remediation=(
                    "Add a copper pour or plane for thermal spreading, then rerun "
                    "thermal_check_copper_pour()."
                ),
                failure_mode="configuration",
                metadata={"domain": "thermal"},
            )

        verdict: Verdict = (
            "PASS" if len(zones) >= max(1, math.ceil(payload.expected_power_w)) else "WARN"
        )
        lines = [
            f"Thermal copper-pour review for {payload.net_name} ({verdict}):",
            f"- Expected dissipation: {payload.expected_power_w:.3f} W",
            f"- Matching pours / planes: {len(zones)}",
        ]
        for zone in zones[: get_config().max_items_per_response]:
            zone_layers = ",".join(BoardLayer.Name(layer) for layer in getattr(zone, "layers", []))
            lines.append(f"- {zone.name or '(unnamed)'} on {zone_layers or '(unknown layers)'}")
        if verdict == "WARN":
            lines.append("- Consider a wider pour, more copper area, and stitched thermal vias.")
        return VerdictReport.from_text_verdict(
            text="\n".join(lines),
            summary=f"Thermal copper support has {len(zones)} matching pour(s)/plane(s).",
            verdict=verdict,
            source="thermal_check_copper_pour",
            evidence=[
                {
                    "net_name": payload.net_name,
                    "expected_power_w": payload.expected_power_w,
                    "matching_pours": len(zones),
                }
            ],
            remediation=(
                "Increase thermal copper area and stitching, then rerun "
                "thermal_check_copper_pour()."
            )
            if verdict != "PASS"
            else "",
            metadata={"domain": "thermal"},
        )

    power_integrity_thermal_plane.register(mcp)
