"""Thin FastMCP adapter for manual track routing tools."""

# pyright: reportUnusedFunction=false

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import cast

from kipy.board import Board
from kipy.board_types import Net, Pad, Track
from kipy.geometry import Vector2
from mcp.server.mcpserver import MCPServer as FastMCP

from ..config import get_config
from ..connection import get_board
from ..pcb.board_access import board_footprints, board_pads
from ..pcb.geometry import point_xy_mm
from ..pcb.live_edit_runtime import execute_live_board_mutation, get_live_edit_service
from ..pcb.pad_mapping import MappedPad, map_pads_to_footprints
from ..pcb.route_drc_preflight import RoutePreflightError, run_route_drc_preflight
from ..pcb.routing_obstacle_snapshot import snapshot_route_obstacles
from ..routing.manual_tracks import RoutingManualTrackService, TrackSpec, _find_pad
from ..routing.path_planner import RoutePlanningError, plan_hv45_path
from ..utils.layers import resolve_layer, resolve_layer_name
from ..utils.units import mm_to_nm
from .metadata import requires_kicad_running


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
        original_text = board.get_as_string()
        if not isinstance(original_text, str) or not original_text:
            raise RoutePlanningError("Native board revision is unavailable")
        revision = hashlib.sha256(original_text.encode("utf-8")).hexdigest()
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
        obstacles = snapshot_route_obstacles(
            board, layer, frozenset(identities), require_outline=True
        )
        path = plan_hv45_path(
            point_xy_mm(start_pad.position),
            point_xy_mm(end_pad.position),
            obstacles,
            track_width_mm=width_mm,
            clearance_mm=clearance_mm,
        )
        updated_text = board.get_as_string()
        if not isinstance(updated_text, str) or (
            hashlib.sha256(updated_text.encode("utf-8")).hexdigest() != revision
        ):
            raise RoutePlanningError("Native board changed while planning; retry preview")
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
    candidate_payload = {
        "boardRevision": revision,
        "ref1": ref1,
        "pad1": pad1,
        "ref2": ref2,
        "pad2": pad2,
        "clearance_mm": clearance_mm,
        "segments": segments,
    }
    candidate_id = hashlib.sha256(
        json.dumps(candidate_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return json.dumps(
        {
            "status": "candidate",
            "schemaVersion": "route-preview.v1",
            "boardRevision": revision,
            "candidateId": candidate_id,
            "candidateOnly": True,
            "drcVerified": False,
            "noBoardMutation": True,
            "net": start_net,
            "path_mm": path,
            "segments": segments,
            "warning": (
                "Candidate is bound to boardRevision; refuse application if the board changed. "
                "Geometry preview only. Review and verify independent native DRC before applying."
            ),
        },
        sort_keys=True,
    )


def _apply_route_candidate(
    candidate_id: str,
    ref1: str,
    pad1: str,
    ref2: str,
    pad2: str,
    layer: str = "F_Cu",
    width_mm: float = 0.25,
    clearance_mm: float = 0.20,
) -> str:
    """Apply only an unchanged, independently DRC-preflighted native candidate."""

    def refused(reason: str, **details: object) -> str:
        return json.dumps(
            {"status": "refused", "committed": False, "reason": reason, **details},
            sort_keys=True,
        )

    try:
        preview = json.loads(
            _preview_route_between_pads(ref1, pad1, ref2, pad2, layer, width_mm, clearance_mm)
        )
        if preview.get("status") != "candidate":
            return refused(preview.get("reason", "No safe candidate is available"))
        if candidate_id != preview.get("candidateId"):
            return refused("Candidate ID does not match the current native board revision")
        board_text = get_board().get_as_string()
        revision = preview["boardRevision"]
        if hashlib.sha256(board_text.encode("utf-8")).hexdigest() != revision:
            return refused("Native board changed before DRC preflight")
        specs = [TrackSpec(**segment) for segment in preview["segments"]]
        config = get_config()
        if config.project_file is None:
            return refused("Project rules file is unavailable")
        evidence = run_route_drc_preflight(
            board_text,
            specs,
            project_file=config.project_file,
            kicad_cli=config.kicad_cli,
        )
    except (RoutePreflightError, RoutePlanningError, ValueError, KeyError, TypeError) as exc:
        return refused(str(exc))
    if not evidence["accepted"]:
        return refused(
            "Independent native KiCad DRC rejected the candidate",
            **evidence,
        )

    if hashlib.sha256(get_board().get_as_string().encode("utf-8")).hexdigest() != revision:
        return refused("Native board changed during DRC preflight")

    service = get_live_edit_service()
    try:
        started = service.begin()
    except Exception:
        return json.dumps(
            {
                "status": "recovery_required",
                "reason": "Native transaction begin was interrupted; inspect KiCad before retry",
                "committed": None,
            }
        )
    if not started.startswith("Transaction group started."):
        return refused("Could not start an exclusive native KiCad transaction")

    def verify_created(live_board: Board, created: list[Track]) -> bool:
        created_ids = [getattr(getattr(item, "id", None), "value", None) for item in created]
        if len(created_ids) != len(specs) or not all(created_ids):
            return False
        current = {
            getattr(getattr(item, "id", None), "value", None) for item in live_board.get_tracks()
        }
        return len(set(created_ids)) == len(created_ids) and set(created_ids) <= current

    try:
        if hashlib.sha256(get_board().get_as_string().encode("utf-8")).hexdigest() != revision:
            raise RoutePlanningError("Native board changed before staged application")
        tracks = [_track_from_spec(spec) for spec in specs]
        execute_live_board_mutation(
            "route_apply_candidate",
            lambda live_board: cast(list[Track], list(live_board.create_items(tracks))),
            verifier=verify_created,
        )
        if hashlib.sha256(get_board().get_as_string().encode("utf-8")).hexdigest() != revision:
            raise RoutePlanningError("Native board changed while staging the route")
    except Exception as exc:
        try:
            dropped = service.drop()
        except Exception:
            dropped = "Native transaction rollback could not be proven."
        if dropped != "Transaction group discarded successfully.":
            return json.dumps(
                {
                    "status": "recovery_required",
                    "reason": "Native transaction recovery could not be verified; do not retry",
                    "committed": None,
                }
            )
        return refused(f"Staged route cancelled: {type(exc).__name__}")

    try:
        pushed = service.push()
    except Exception:
        pushed = "Native transaction publication could not be verified."
    if pushed != "Transaction group committed successfully.":
        return json.dumps(
            {
                "status": "recovery_required",
                "reason": "KiCad publish or postcondition could not be verified; do not retry",
                "committed": None,
            }
        )
    return json.dumps(
        {
            "status": "applied",
            "candidateId": candidate_id,
            "committed": True,
            "drcPreflightAccepted": True,
            "introducedViolations": evidence["introducedViolations"],
            "unconnectedBefore": evidence["unconnectedBefore"],
            "unconnectedAfter": evidence["unconnectedAfter"],
            "saved": False,
            "warning": (
                "Applied as one native KiCad undo step, not saved to disk. "
                "Use pcb_save, then reopen and confirm independent DRC."
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
        contours refuse planning. The boardRevision and candidateId identify
        the native board snapshot and planned geometry; re-plan after any edit
        or reconnect. DRC remains UNVERIFIED until independent validation;
        the returned segments must not be applied blindly.
        """
        return _preview_route_between_pads(ref1, pad1, ref2, pad2, layer, width_mm, clearance_mm)

    @mcp.tool()
    @requires_kicad_running
    def route_apply_candidate(
        candidate_id: str,
        ref1: str,
        pad1: str,
        ref2: str,
        pad2: str,
        layer: str = "F_Cu",
        width_mm: float = 0.25,
        clearance_mm: float = 0.20,
    ) -> str:
        """Apply an unchanged H/V/45 candidate only after native KiCad DRC preflight.

        WRITE operation, limited to one copper layer and named endpoints.
        Creates one native Undo step, does not save the board automatically.
        Unsupported geometry, stale IDs and new DRC violations are refused.
        """
        return _apply_route_candidate(
            candidate_id, ref1, pad1, ref2, pad2, layer, width_mm, clearance_mm
        )
