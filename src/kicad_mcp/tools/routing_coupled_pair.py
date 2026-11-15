"""Native KiCad MCP adapter for bounded, obstacle-aware matched P/N routes.

This uses the existing native board, routing planner, DRC preflight and
transaction machinery. It is not a second autorouter or an impedance solver.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from typing import cast

from kipy.board_types import Pad
from mcp.server.mcpserver import MCPServer as FastMCP

from ..config import get_config
from ..connection import get_board
from ..pcb.board_access import board_footprints, board_pads
from ..pcb.geometry import point_xy_mm
from ..pcb.pad_mapping import map_pads_to_footprints
from ..pcb.route_drc_preflight import run_route_drc_preflight
from ..pcb.routing_obstacle_snapshot import snapshot_route_obstacles
from ..routing.differential_pair_candidate import plan_coupled_hv45_pair
from ..routing.manual_tracks import TrackSpec, _find_pad
from ..routing.path_planner import RoutePlanningError
from .metadata import requires_kicad_running
from .routing_manual_tracks import _publish_route_specs, _validate_endpoint_layer


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
    if not (
        _validate_endpoint_layer(positive_a, positive_b, layer)
        and _validate_endpoint_layer(negative_a, negative_b, layer)
    ):
        raise RoutePlanningError("P/N pads do not share the requested enabled copper layer")
    return positive_a, positive_b, negative_a, negative_b


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
        obstacles = snapshot_route_obstacles(
            board,
            layer,
            frozenset(pad.id.value for pad in (p1, p2, n1, n2)),
            require_outline=True,
            expected_endpoint_count=4,
        )
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
        segments = [asdict(spec) for spec in (*plus, *minus)]
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
        return json.dumps(
            {"status": "refused", "candidateOnly": True, "reason": str(exc)},
            sort_keys=True,
        )


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
