"""Narrow native F.Cu/B.Cu routing through one full-stack via.

Reuse the current obstacle snapshot, KiCad CLI DRC and one-Undo IPC publisher.
No via layer cost guarantees, physical stackup signoff or impedance claims.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Collection
from dataclasses import asdict
from typing import cast

from kipy.board_types import Pad
from kipy.proto.board.board_types_pb2 import BoardLayer
from mcp.server.mcpserver import MCPServer as FastMCP

from ..config import get_config
from ..connection import get_board
from ..pcb.board_access import board_footprints, board_pads
from ..pcb.geometry import point_xy_mm
from ..pcb.pad_mapping import map_pads_to_footprints
from ..pcb.route_drc_preflight import run_route_drc_preflight
from ..pcb.routing_obstacle_snapshot import snapshot_route_obstacles
from ..routing.manual_tracks import TrackSpec, ViaSpec, _find_pad
from ..routing.path_planner import RoutePlanningError
from ..routing.through_via_planner import plan_one_through_via
from ..utils.layers import resolve_layer
from .metadata import requires_kicad_running
from .routing_manual_tracks import _publish_route_specs


def _ensure_distinct_outer_pad_layers(
    source: Pad,
    target: Pad,
    *,
    start_layer: str,
    end_layer: str,
    enabled_layers: Collection[BoardLayer.ValueType],
) -> None:
    """Use only enabled, mutually exclusive F.Cu/B.Cu SMD endpoint layers."""
    if (start_layer, end_layer) not in (("F_Cu", "B_Cu"), ("B_Cu", "F_Cu")):
        raise RoutePlanningError("Only one full-stack outer layer transition is supported")
    first, last = resolve_layer(start_layer), resolve_layer(end_layer)
    if first not in enabled_layers or last not in enabled_layers:
        raise RoutePlanningError("Both requested copper layers must be enabled")
    source_layers = set(source.padstack.layers)
    target_layers = set(target.padstack.layers)
    if not (
        first in source_layers
        and last in target_layers
        and last not in source_layers
        and first not in target_layers
    ):
        raise RoutePlanningError(
            "A via is only offered between distinct F/B SMD pads with no common copper layer"
        )


def _preview_one_via(
    ref1: str,
    pad1: str,
    ref2: str,
    pad2: str,
    start_layer: str = "F_Cu",
    end_layer: str = "B_Cu",
    width_mm: float = 0.25,
    via_diameter_mm: float = 0.8,
    via_drill_mm: float = 0.4,
    clearance_mm: float = 0.20,
) -> str:
    """READ-only candidate; a via is considered only for opposite SMD layers."""

    def refused(reason: str) -> str:
        return json.dumps(
            {"status": "refused", "candidateOnly": True, "reason": reason},
            sort_keys=True,
        )

    try:
        board = get_board()
        original = board.get_as_string()
        if not isinstance(original, str) or not original.startswith("(kicad_pcb"):
            raise RoutePlanningError("Native board snapshot is unavailable")
        revision = hashlib.sha256(original.encode("utf-8")).hexdigest()
        mapped = map_pads_to_footprints(board_pads(board), board_footprints(board))
        a = _find_pad(mapped, ref1, pad1)
        b = _find_pad(mapped, ref2, pad2)
        if a is None or b is None:
            raise RoutePlanningError("One or both named via-route pads are missing")
        source, target = cast(Pad, a.pad), cast(Pad, b.pad)
        if source.id.value == target.id.value or not source.id.value or not target.id.value:
            raise RoutePlanningError("Distinct stable native pad identities are required")
        net = source.net.name
        if not net or net != target.net.name:
            raise RoutePlanningError("Opposite layer pads must share one named net")
        _ensure_distinct_outer_pad_layers(
            source,
            target,
            start_layer=start_layer,
            end_layer=end_layer,
            enabled_layers=board.get_enabled_layers(),
        )
        front = snapshot_route_obstacles(
            board,
            "F_Cu",
            frozenset((source.id.value if start_layer == "F_Cu" else target.id.value,)),
            expected_endpoint_count=1,
            require_outline=True,
            routing_net=net,
        )
        back = snapshot_route_obstacles(
            board,
            "B_Cu",
            frozenset((target.id.value if end_layer == "B_Cu" else source.id.value,)),
            expected_endpoint_count=1,
            require_outline=True,
            routing_net=net,
        )
        front_via = snapshot_route_obstacles(
            board,
            "F_Cu",
            frozenset((source.id.value if start_layer == "F_Cu" else target.id.value,)),
            expected_endpoint_count=1,
            require_outline=True,
            routing_net=net,
            for_via=True,
        )
        back_via = snapshot_route_obstacles(
            board,
            "B_Cu",
            frozenset((target.id.value if end_layer == "B_Cu" else source.id.value,)),
            expected_endpoint_count=1,
            require_outline=True,
            routing_net=net,
            for_via=True,
        )
        segments, via, geometry = plan_one_through_via(
            point_xy_mm(source.position),
            point_xy_mm(target.position),
            front_obstacles=front,
            back_obstacles=back,
            front_via_obstacles=front_via,
            back_via_obstacles=back_via,
            start_layer=start_layer,
            end_layer=end_layer,
            net_name=net,
            width_mm=width_mm,
            clearance_mm=clearance_mm,
            diameter_mm=via_diameter_mm,
            drill_mm=via_drill_mm,
        )
        if hashlib.sha256(get_board().get_as_string().encode("utf-8")).hexdigest() != revision:
            raise RoutePlanningError("Board revision changed while planning via route")
        paths = [asdict(segment) for segment in segments]
        via_dict = asdict(via)
        payload = {
            "boardRevision": revision,
            "sourcePad": (ref1, pad1),
            "targetPad": (ref2, pad2),
            "segments": paths,
            "throughVia": via_dict,
            "clearanceMm": clearance_mm,
        }
        candidate_id = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return json.dumps(
            {
                "status": "candidate",
                "schemaVersion": "single-through-via-preview.v1",
                "candidateOnly": True,
                "noBoardMutation": True,
                "drcVerified": False,
                "boardRevision": revision,
                "candidateId": candidate_id,
                "net": net,
                "segments": paths,
                "throughVia": via_dict,
                "geometry": geometry,
                "warning": (
                    "Preliminary one-via geometry only. Native KiCad DRC is mandatory "
                    "before WRITE. Via cost is a heuristic; stackup/impedance NOT certified."
                ),
            },
            sort_keys=True,
        )
    except (AttributeError, ValueError, TypeError) as exc:
        return refused(str(exc))


def _apply_one_via(
    candidate_id: str,
    ref1: str,
    pad1: str,
    ref2: str,
    pad2: str,
    start_layer: str = "F_Cu",
    end_layer: str = "B_Cu",
    width_mm: float = 0.25,
    via_diameter_mm: float = 0.8,
    via_drill_mm: float = 0.4,
    clearance_mm: float = 0.20,
) -> str:
    """WRITE only an unchanged, independently native-DRC-accepted via candidate."""

    def refused(reason: str, **evidence: object) -> str:
        return json.dumps(
            {"status": "refused", "committed": False, "reason": reason, **evidence},
            sort_keys=True,
        )

    try:
        preview = json.loads(
            _preview_one_via(
                ref1,
                pad1,
                ref2,
                pad2,
                start_layer,
                end_layer,
                width_mm,
                via_diameter_mm,
                via_drill_mm,
                clearance_mm,
            )
        )
        if preview.get("status") != "candidate":
            return refused(preview.get("reason", "No safe through-via candidate"))
        if not isinstance(candidate_id, str) or candidate_id != preview["candidateId"]:
            return refused("Stale or incorrect through-via candidate ID")
        board_text = get_board().get_as_string()
        revision = preview["boardRevision"]
        if hashlib.sha256(board_text.encode("utf-8")).hexdigest() != revision:
            return refused("Board changed before through-via DRC")
        segments = [TrackSpec(**item) for item in preview["segments"]]
        via = ViaSpec(**preview["throughVia"])
        config = get_config()
        if config.project_file is None:
            return refused("KiCad native project rules unavailable")
        evidence = run_route_drc_preflight(
            board_text,
            segments,
            project_file=config.project_file,
            kicad_cli=config.kicad_cli,
            through_via=via,
        )
    except (KeyError, ValueError, TypeError) as exc:
        return refused(str(exc))
    if not evidence["accepted"]:
        return refused("Native KiCad DRC rejected the layer transition", **evidence)
    if hashlib.sha256(get_board().get_as_string().encode("utf-8")).hexdigest() != revision:
        return refused("Board changed during through-via DRC")
    result = json.loads(
        _publish_route_specs(
            segments,
            revision,
            evidence,
            candidate_id,
            through_via=via,
        )
    )
    if result.get("status") == "applied":
        result["viaGeometry"] = preview["throughVia"]
        result["warning"] = (
            "Two copper segments plus ONE through-via are committed as one KiCad Undo; "
            "NOT saved. Call pcb_save, native DRC and reopen. No impedance certification."
        )
    return json.dumps(result, sort_keys=True)


def register(mcp: FastMCP) -> None:
    """Expose two strictly scoped tools in the existing routing catalog."""

    @mcp.tool()
    @requires_kicad_running
    def route_plan_one_through_via(
        ref1: str,
        pad1: str,
        ref2: str,
        pad2: str,
        start_layer: str = "F_Cu",
        end_layer: str = "B_Cu",
        width_mm: float = 0.25,
        via_diameter_mm: float = 0.8,
        via_drill_mm: float = 0.4,
        clearance_mm: float = 0.20,
    ) -> str:
        """READ-only one-through-via plan between opposite-layer SMD pads."""
        return _preview_one_via(
            ref1,
            pad1,
            ref2,
            pad2,
            start_layer,
            end_layer,
            width_mm,
            via_diameter_mm,
            via_drill_mm,
            clearance_mm,
        )

    @mcp.tool()
    @requires_kicad_running
    def route_apply_one_through_via_candidate(
        candidate_id: str,
        ref1: str,
        pad1: str,
        ref2: str,
        pad2: str,
        start_layer: str = "F_Cu",
        end_layer: str = "B_Cu",
        width_mm: float = 0.25,
        via_diameter_mm: float = 0.8,
        via_drill_mm: float = 0.4,
        clearance_mm: float = 0.20,
    ) -> str:
        """WRITE two traces plus one via in ONE native Undo after KiCad DRC."""
        return _apply_one_via(
            candidate_id,
            ref1,
            pad1,
            ref2,
            pad2,
            start_layer,
            end_layer,
            width_mm,
            via_diameter_mm,
            via_drill_mm,
            clearance_mm,
        )
