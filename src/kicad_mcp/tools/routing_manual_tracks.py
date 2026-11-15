"""Thin FastMCP adapter for manual track routing tools."""

# pyright: reportUnusedFunction=false

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import cast

from kipy.board_types import Net, Pad, Track
from kipy.geometry import Vector2
from mcp.server.mcpserver import MCPServer as FastMCP

from ..connection import get_board
from ..pcb.board_access import board_footprints, board_pads
from ..pcb.geometry import point_xy_mm
from ..pcb.live_edit_runtime import execute_live_board_mutation
from ..pcb.pad_mapping import MappedPad, map_pads_to_footprints
from ..routing.manual_tracks import RoutingManualTrackService, TrackSpec, _find_pad
from ..routing.path_planner import RoutePlanningError, plan_hv45_path
from ..utils.layers import resolve_layer, resolve_layer_name
from ..utils.units import mm_to_nm
from .metadata import requires_kicad_running
from .routing_obstacle_snapshot import snapshot_route_obstacles


@dataclass(frozen=True)
class RoutingManualTrackDependencies:
    service: RoutingManualTrackService


def _track_from_spec(spec: TrackSpec) -> Track:
    track = Track()
    track.start = Vector2.from_xy_mm(spec.x1_mm, spec.y1_mm)
    track.end = Vector2.from_xy_mm(spec.x2_mm, spec.y2_mm)
    track.layer = resolve_layer(spec.layer)
    track.width = mm_to_nm(spec.width_mm)
    if spec.net_name:
        net = Net()
        net.name = spec.net_name
        track.net = net
    return track


def _write_tracks(operation: str, specs: list[TrackSpec]) -> None:
    tracks = [_track_from_spec(spec) for spec in specs]
    execute_live_board_mutation(
        operation,
        lambda board: list(board.create_items(tracks)),
        verifier=None,
    )


def _mapped_live_pads() -> list[MappedPad]:
    board = get_board()
    return map_pads_to_footprints(board_pads(board), board_footprints(board))


def _validate_endpoint_layer(start_pad: object, end_pad: object, layer: str) -> bool:
    """Require an enabled copper layer on both native padstacks.

    PadStack.copper_layers stores *geometry templates*, not connectivity:
    a PTH PST_NORMAL stack stores only F_Cu geometry even when its
    PadStack.layers contains both outer copper layers.
    """
    try:
        canonical = resolve_layer_name(layer)
    except ValueError:
        return False
    if not canonical.endswith("_Cu"):
        return False

    layer_id = resolve_layer(canonical)
    enabled_layers = get_board().get_enabled_layers()
    if layer_id not in enabled_layers:
        return False
    for pad in (start_pad, end_pad):
        stack = getattr(pad, "padstack", None)
        layers = getattr(stack, "layers", ()) if stack is not None else ()
        if layer_id not in layers:
            return False
    return True


def _default_dependencies() -> RoutingManualTrackDependencies:
    return RoutingManualTrackDependencies(
        service=RoutingManualTrackService(
            list_pads=_mapped_live_pads,
            write_tracks=_write_tracks,
            validate_layer=_validate_endpoint_layer,
        )
    )


def _preview_route_between_pads(
    ref1: str,
    pad1: str,
    ref2: str,
    pad2: str,
    layer: str = "F_Cu",
    width_mm: float = 0.25,
    clearance_mm: float = 0.20,
) -> str:
    """Read current native board geometry and produce a candidate, without writing."""
    try:
        board = get_board()
        mapped = map_pads_to_footprints(board_pads(board), board_footprints(board))
        start = _find_pad(mapped, ref1, pad1)
        end = _find_pad(mapped, ref2, pad2)
        if start is None or end is None:
            raise RoutePlanningError("One or both named pads were not found")
        start_pad, end_pad = cast(Pad, start.pad), cast(Pad, end.pad)
        start_net, end_net = start_pad.net.name or "", end_pad.net.name or ""
        if not start_net or start_net != end_net:
            raise RoutePlanningError("Pads must belong to the same nonempty net")
        if not _validate_endpoint_layer(start_pad, end_pad, layer):
            raise RoutePlanningError("Pads do not support the requested enabled copper layer")
        identities = (start_pad.id.value, end_pad.id.value)
        if not all(identities):
            raise RoutePlanningError("Native pad identities unavailable")
        obstacles = snapshot_route_obstacles(board, layer, frozenset(identities))
        path = plan_hv45_path(
            point_xy_mm(start_pad.position),
            point_xy_mm(end_pad.position),
            obstacles,
            track_width_mm=width_mm,
            clearance_mm=clearance_mm,
        )
    except (RoutePlanningError, ValueError) as exc:
        return json.dumps({"status": "refused", "candidateOnly": True, "reason": str(exc)})
    segments = [
        {
            "x1_mm": a[0],
            "y1_mm": a[1],
            "x2_mm": b[0],
            "y2_mm": b[1],
            "layer": layer,
            "width_mm": width_mm,
            "net_name": start_net,
        }
        for a, b in zip(path, path[1:], strict=False)
    ]
    return json.dumps(
        {
            "status": "candidate",
            "candidateOnly": True,
            "drcVerified": False,
            "noBoardMutation": True,
            "net": start_net,
            "path_mm": path,
            "segments": segments,
            "warning": (
                "Geometry preview only. Board may have unsupported DRC constraints. "
                "Review and verify independent native DRC before applying."
            ),
        },
        sort_keys=True,
    )


def register(
    mcp: FastMCP,
    dependencies: RoutingManualTrackDependencies | None = None,
) -> None:
    """Register manual track routing tools."""
    deps = dependencies or _default_dependencies()

    @mcp.tool()
    @requires_kicad_running
    def route_single_track(
        x1_mm: float,
        y1_mm: float,
        x2_mm: float,
        y2_mm: float,
        layer: str = "F_Cu",
        width_mm: float = 0.25,
        net_name: str = "",
    ) -> str:
        """Route a single straight track segment."""
        return deps.service.route_single(
            x1_mm,
            y1_mm,
            x2_mm,
            y2_mm,
            layer,
            width_mm,
            net_name,
        )

    @mcp.tool()
    @requires_kicad_running
    def route_from_pad_to_pad(
        ref1: str,
        pad1: str,
        ref2: str,
        pad2: str,
        layer: str = "F_Cu",
        width_mm: float = 0.25,
    ) -> str:
        """Connect same-net pads on an enabled copper layer using orthogonal tracks.

        Pads must share the same named net and support the requested enabled
        copper layer. This raw track writer does not guarantee DRC-clean routing;
        save and verify the resulting board independently.
        """
        return deps.service.route_pad_to_pad(
            ref1,
            pad1,
            ref2,
            pad2,
            layer,
            width_mm,
        )

    @mcp.tool()
    @requires_kicad_running
    def route_plan_between_pads(
        ref1: str,
        pad1: str,
        ref2: str,
        pad2: str,
        layer: str = "F_Cu",
        width_mm: float = 0.25,
        clearance_mm: float = 0.20,
    ) -> str:
        """READ-ONLY preview of a bounded H/V/45 route between same-net pads.

        No copper is created or saved. Unsupported pad shapes, board zones or
        contours refuse planning. DRC remains UNVERIFIED until independent
        validation; the returned segments must not be applied blindly.
        """
        return _preview_route_between_pads(ref1, pad1, ref2, pad2, layer, width_mm, clearance_mm)
