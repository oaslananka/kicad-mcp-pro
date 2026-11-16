"""Native KiCad MCP adapter for bounded, obstacle-aware matched P/N routes.

This uses the existing native board, routing planner, DRC preflight and
transaction machinery. It is not a second autorouter or an impedance solver.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from math import hypot, isfinite
from typing import cast

from kipy.board_types import Pad
from mcp.server.mcpserver import MCPServer as FastMCP

from ..config import get_config
from ..connection import get_board
from ..pcb.board_access import board_footprints, board_pads, board_tracks
from ..pcb.geometry import point_xy_mm
from ..pcb.pad_mapping import map_pads_to_footprints
from ..pcb.route_drc_preflight import run_route_drc_preflight
from ..pcb.routing_obstacle_snapshot import snapshot_route_obstacles
from ..routing.differential_pair_candidate import plan_coupled_hv45_pair
from ..routing.manual_tracks import TrackSpec, _find_pad
from ..routing.path_planner import RoutePlanningError
from .metadata import requires_kicad_running
from .routing_manual_tracks import (
    _already_present_track,
    _publish_route_specs,
    _validate_endpoint_layer,
)


def _coupled_endpoints(
    board: object,
    p_ref1: str,
    p_pad1: str,
    p_ref2: str,
    p_pad2: str,
    n_ref1: str,
    n_pad1: str,
    n_ref2: str,
    n_pad2: str,
    layer: str,
) -> tuple[Pad, Pad, Pad, Pad]:
    mapped = map_pads_to_footprints(board_pads(board), board_footprints(board))
    refs = (
        (p_ref1, p_pad1),
        (p_ref2, p_pad2),
        (n_ref1, n_pad1),
        (n_ref2, n_pad2),
    )
    candidates = [_find_pad(mapped, ref, number) for ref, number in refs]
    if any(item is None for item in candidates):
        raise RoutePlanningError("One or more named P/N pads were not found")
    pads = tuple(cast(Pad, item.pad) for item in candidates if item is not None)
    if len(pads) != 4:
        raise RoutePlanningError("Native differential pair pad mapping is incomplete")
    identities = [pad.id.value for pad in pads]
    if not all(identities) or len(set(identities)) != 4:
        raise RoutePlanningError("Four unique native P/N pad identities are required")
    positive_a, positive_b, negative_a, negative_b = pads
    if (
        not positive_a.net.name
        or positive_a.net.name != positive_b.net.name
        or not negative_a.net.name
        or negative_a.net.name != negative_b.net.name
    ):
        raise RoutePlanningError("P/N pad endpoints must each share one named net")
    if positive_a.net.name == negative_a.net.name:
        raise RoutePlanningError("P/N lanes must use distinct named nets, not the same net")
    positive_name, negative_name = positive_a.net.name.upper(), negative_a.net.name.upper()
    if (
        "USB" in positive_name
        and "USB" in negative_name
        and (
            positive_name.endswith(("_N", "_DM", "D-"))
            or negative_name.endswith(("_P", "_DP", "D+"))
        )
    ):
        raise RoutePlanningError(
            "P/N lane assignment contradicts the USB net polarity labels; "
            "verify source and target pad mappings"
        )
    if not (
        _validate_endpoint_layer(positive_a, positive_b, layer)
        and _validate_endpoint_layer(negative_a, negative_b, layer)
    ):
        raise RoutePlanningError("P/N pads do not share the requested enabled copper layer")
    return positive_a, positive_b, negative_a, negative_b


def _pair_pad_geometry(
    plus_start: tuple[float, float],
    plus_end: tuple[float, float],
    minus_start: tuple[float, float],
    minus_end: tuple[float, float],
    width_mm: float,
    gap_mm: float,
) -> dict[str, float | bool] | None:
    """Measure P/N endpoint offsets; do not infer electrical impedance or delay."""
    coords = (*plus_start, *plus_end, *minus_start, *minus_end, width_mm, gap_mm)
    if not all(isfinite(value) for value in coords):
        return None
    start_delta = (minus_start[0] - plus_start[0], minus_start[1] - plus_start[1])
    end_delta = (minus_end[0] - plus_end[0], minus_end[1] - plus_end[1])
    axis = (plus_end[0] - plus_start[0], plus_end[1] - plus_start[1])
    axis_length = hypot(*axis)
    start_side = (
        (axis[0] * start_delta[1] - axis[1] * start_delta[0]) / axis_length
        if axis_length > 1e-6
        else 0.0
    )
    end_side = (
        (axis[0] * end_delta[1] - axis[1] * end_delta[0]) / axis_length
        if axis_length > 1e-6
        else 0.0
    )
    return {
        "startPadSeparationMm": round(hypot(*start_delta), 6),
        "endPadSeparationMm": round(hypot(*end_delta), 6),
        "requestedCenterSpacingMm": round(width_mm + gap_mm, 6),
        "offsetChangeMm": round(
            hypot(start_delta[0] - end_delta[0], start_delta[1] - end_delta[1]), 6
        ),
        "padOrderReversed": start_side * end_side < 0
        and min(abs(start_side), abs(end_side)) > 0.0001,
    }


def _pair_refusal(reason: str, pad_geometry: dict[str, float | bool] | None) -> str:
    """Explain the physical blocker without coupling report policy to IPC."""
    refusal: dict[str, object] = {
        "status": "refused",
        "candidateOnly": True,
        "reason": reason,
    }
    if pad_geometry is None or not (
        "pad order reverses" in reason or "aligned pads" in reason or "spacing/offset" in reason
    ):
        return json.dumps(refusal, sort_keys=True)

    refusal["padGeometry"] = pad_geometry
    if pad_geometry["padOrderReversed"]:
        refusal["blockerType"] = "pad_order_reversal"
        refusal["nextAction"] = (
            "P/N pad order is reversed: do not cross the lanes on one copper "
            "layer. Review pad mappings and independently qualify any "
            "layer transition, return path and stackup before routing. "
            "No physical signoff."
        )
    elif (
        abs(pad_geometry["startPadSeparationMm"] - pad_geometry["requestedCenterSpacingMm"]) > 0.001
        or abs(pad_geometry["endPadSeparationMm"] - pad_geometry["requestedCenterSpacingMm"])
        > 0.001
    ):
        refusal["blockerType"] = "fanout_required"
        refusal["nextAction"] = (
            "P/N pad order is consistent; the endpoint spacing needs a "
            "reviewed differential-pair fanout, not a polarity swap. "
            "Use KiCad's native differential-pair fanout and tuning with "
            "verified stackup, return path and DRC. No physical signoff."
        )
    else:
        refusal["blockerType"] = "unsupported_alignment"
        refusal["nextAction"] = (
            "P/N spacing is consistent but this bounded planner cannot "
            "handle the endpoint alignment. Review the native KiCad "
            "differential-pair routing and verified board constraints. "
            "No physical signoff."
        )
    return json.dumps(refusal, sort_keys=True)


def _preview_coupled_pair(
    p_ref1: str,
    p_pad1: str,
    p_ref2: str,
    p_pad2: str,
    n_ref1: str,
    n_pad1: str,
    n_ref2: str,
    n_pad2: str,
    layer: str = "F_Cu",
    width_mm: float = 0.25,
    gap_mm: float = 0.5,
    clearance_mm: float = 0.20,
    max_skew_mm: float = 0.1,
) -> str:
    """READ-only IPC snapshot; both routes are planned around the same obstacles."""
    pad_geometry: dict[str, float | bool] | None = None
    try:
        board = get_board()
        raw = board.get_as_string()
        if not isinstance(raw, str) or not raw.startswith("(kicad_pcb"):
            raise RoutePlanningError("Native board serialization unavailable")
        revision = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        p1, p2, n1, n2 = _coupled_endpoints(
            board,
            p_ref1,
            p_pad1,
            p_ref2,
            p_pad2,
            n_ref1,
            n_pad1,
            n_ref2,
            n_pad2,
            layer,
        )
        pad_geometry = _pair_pad_geometry(
            point_xy_mm(p1.position),
            point_xy_mm(p2.position),
            point_xy_mm(n1.position),
            point_xy_mm(n2.position),
            width_mm,
            gap_mm,
        )
        if pad_geometry is not None and pad_geometry["padOrderReversed"]:
            raise RoutePlanningError(
                "P/N pad order reverses between endpoints: a single-layer coupled route "
                "would cross; review pad mapping or a separately qualified layer transition"
            )
        # Each native snapshot validates the exact pad/net mapping. Keep only
        # obstacles common to both to ignore existing P and N copper while
        # preserving foreign-net copper, zones, keepouts and board boundary.
        plus_obstacles = snapshot_route_obstacles(
            board,
            layer,
            frozenset((p1.id.value, p2.id.value)),
            require_outline=True,
            expected_endpoint_count=2,
            routing_net=p1.net.name,
        )
        minus_obstacles = snapshot_route_obstacles(
            board,
            layer,
            frozenset((n1.id.value, n2.id.value)),
            require_outline=True,
            expected_endpoint_count=2,
            routing_net=n1.net.name,
        )
        minus_set = set(minus_obstacles)
        obstacles = tuple(obstacle for obstacle in plus_obstacles if obstacle in minus_set)
        plus, minus, geometry = plan_coupled_hv45_pair(
            plus_start=point_xy_mm(p1.position),
            plus_end=point_xy_mm(p2.position),
            minus_start=point_xy_mm(n1.position),
            minus_end=point_xy_mm(n2.position),
            obstacles=obstacles,
            layer=layer,
            net_plus=p1.net.name,
            net_minus=n1.net.name,
            width_mm=width_mm,
            gap_mm=gap_mm,
            clearance_mm=clearance_mm,
            max_skew_mm=max_skew_mm,
        )
        if hashlib.sha256(get_board().get_as_string().encode("utf-8")).hexdigest() != revision:
            raise RoutePlanningError("Native board changed while previewing paired route")
        planned = (*plus, *minus)
        existing = board_tracks(board)
        repeated = sum(_already_present_track(spec, existing) for spec in planned)
        if repeated == len(planned):
            raise RoutePlanningError("Paired route already exists; no new copper is required")
        if repeated:
            raise RoutePlanningError(
                "Paired candidate overlaps existing same-net copper; "
                "review the partial route instead of duplicating tracks"
            )
        segments = [asdict(spec) for spec in planned]
        fingerprint = {
            "boardRevision": revision,
            "positivePads": (p_ref1, p_pad1, p_ref2, p_pad2),
            "negativePads": (n_ref1, n_pad1, n_ref2, n_pad2),
            "gapMm": gap_mm,
            "maxSkewMm": max_skew_mm,
            "clearanceMm": clearance_mm,
            "segments": segments,
        }
        identifier = hashlib.sha256(
            json.dumps(fingerprint, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return json.dumps(
            {
                "status": "candidate",
                "schemaVersion": "coupled-differential-pair-preview.v1",
                "candidateId": identifier,
                "boardRevision": revision,
                "candidateOnly": True,
                "drcVerified": False,
                "noBoardMutation": True,
                "segments": segments,
                "positiveSegmentCount": len(plus),
                "negativeSegmentCount": len(minus),
                "netPlus": p1.net.name,
                "netMinus": n1.net.name,
                "geometry": geometry,
                "warning": (
                    "Matched, obstacle-screened geometry only; native KiCad "
                    "DRC required before writing. Physical impedance NOT verified."
                ),
            },
            sort_keys=True,
        )
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        return _pair_refusal(str(exc), pad_geometry)


# S107 exception: preserve the flat paired candidate contract consumed by the MCP adapter.
# Keep candidate identity, four P/N pad coordinates and five route options independently typed.
def _apply_coupled_pair(  # NOSONAR - S107: paired MCP input compatibility
    candidate_id: str,
    p_ref1: str,
    p_pad1: str,
    p_ref2: str,
    p_pad2: str,
    n_ref1: str,
    n_pad1: str,
    n_ref2: str,
    n_pad2: str,
    layer: str = "F_Cu",
    width_mm: float = 0.25,
    gap_mm: float = 0.5,
    clearance_mm: float = 0.20,
    max_skew_mm: float = 0.1,
) -> str:
    """WRITE an unchanged paired route after BOTH nets pass one native DRC."""

    def refused(reason: str, **details: object) -> str:
        return json.dumps(
            {"status": "refused", "committed": False, "reason": reason, **details},
            sort_keys=True,
        )

    try:
        preview = json.loads(
            _preview_coupled_pair(
                p_ref1=p_ref1,
                p_pad1=p_pad1,
                p_ref2=p_ref2,
                p_pad2=p_pad2,
                n_ref1=n_ref1,
                n_pad1=n_pad1,
                n_ref2=n_ref2,
                n_pad2=n_pad2,
                layer=layer,
                width_mm=width_mm,
                gap_mm=gap_mm,
                clearance_mm=clearance_mm,
                max_skew_mm=max_skew_mm,
            )
        )
        if preview.get("status") != "candidate":
            return refused(preview.get("reason", "No safe native coupled pair candidate"))
        if not isinstance(candidate_id, str) or candidate_id != preview["candidateId"]:
            return refused("Stale or incorrect paired candidate ID")
        original = get_board().get_as_string()
        revision = preview["boardRevision"]
        if hashlib.sha256(original.encode("utf-8")).hexdigest() != revision:
            return refused("Native board changed before paired DRC")
        specs = [TrackSpec(**data) for data in preview["segments"]]
        config = get_config()
        if config.project_file is None:
            return refused("Project DRC rules file is unavailable")
        evidence = run_route_drc_preflight(
            original,
            specs,
            project_file=config.project_file,
            kicad_cli=config.kicad_cli,
            pair_nets=frozenset((preview["netPlus"], preview["netMinus"])),
        )
    except (ValueError, TypeError, KeyError) as exc:
        return refused(str(exc))
    if not evidence["accepted"]:
        return refused("Native KiCad DRC refused coupled differential pair", **evidence)
    if hashlib.sha256(get_board().get_as_string().encode("utf-8")).hexdigest() != revision:
        return refused("Native board changed during coupled DRC")
    result = json.loads(_publish_route_specs(specs, revision, evidence, candidate_id))
    if result.get("status") == "applied":
        result["pairGeometry"] = preview["geometry"]
        result["warning"] = (
            "P/N routes committed as one KiCad Undo step, NOT saved. "
            "Call pcb_save and verify native DRC after reopening. "
            "No physical impedance/stackup certification."
        )
    return json.dumps(result, sort_keys=True)


def register(mcp: FastMCP) -> None:
    """Expose the bounded coupled pair through the existing MCP tool registry."""

    @mcp.tool()
    @requires_kicad_running
    def route_plan_coupled_differential_pair(
        p_ref1: str,
        p_pad1: str,
        p_ref2: str,
        p_pad2: str,
        n_ref1: str,
        n_pad1: str,
        n_ref2: str,
        n_pad2: str,
        layer: str = "F_Cu",
        width_mm: float = 0.25,
        gap_mm: float = 0.5,
        clearance_mm: float = 0.20,
        max_skew_mm: float = 0.1,
    ) -> str:
        """READ-only bounded H/V/45 obstacle-aware matched USB P/N route preview."""
        return _preview_coupled_pair(
            p_ref1,
            p_pad1,
            p_ref2,
            p_pad2,
            n_ref1,
            n_pad1,
            n_ref2,
            n_pad2,
            layer,
            width_mm,
            gap_mm,
            clearance_mm,
            max_skew_mm,
        )

    @mcp.tool()
    @requires_kicad_running
    # Flat parameter names are an existing FastMCP JSON schema compatibility contract.
    def route_apply_coupled_differential_pair_candidate(  # NOSONAR - S107: stable MCP schema
        candidate_id: str,
        p_ref1: str,
        p_pad1: str,
        p_ref2: str,
        p_pad2: str,
        n_ref1: str,
        n_pad1: str,
        n_ref2: str,
        n_pad2: str,
        layer: str = "F_Cu",
        width_mm: float = 0.25,
        gap_mm: float = 0.5,
        clearance_mm: float = 0.20,
        max_skew_mm: float = 0.1,
    ) -> str:
        """WRITE both P/N lanes as ONE native Undo only after joint KiCad DRC."""
        return _apply_coupled_pair(
            candidate_id,
            p_ref1,
            p_pad1,
            p_ref2,
            p_pad2,
            n_ref1,
            n_pad1,
            n_ref2,
            n_pad2,
            layer,
            width_mm,
            gap_mm,
            clearance_mm,
            max_skew_mm,
        )
