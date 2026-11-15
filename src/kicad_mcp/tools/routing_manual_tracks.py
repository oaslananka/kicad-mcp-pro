"""Thin FastMCP adapter for manual track routing tools."""

# pyright: reportUnusedFunction=false

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import cast

from kipy.board import Board
from kipy.board_types import Net, Pad, Track, Via
from kipy.geometry import Vector2
from kipy.proto.board.board_types_pb2 import ViaType
from mcp.server.mcpserver import MCPServer as FastMCP

from ..config import get_config
from ..connection import get_board
from ..pcb.board_access import board_footprints, board_pads
from ..pcb.geometry import point_xy_mm
from ..pcb.live_edit_runtime import execute_live_board_mutation, get_live_edit_service
from ..pcb.pad_mapping import MappedPad, map_pads_to_footprints
from ..pcb.route_drc_preflight import RoutePreflightError, run_route_drc_preflight
from ..pcb.routing_obstacle_snapshot import snapshot_route_obstacles
from ..routing.differential_pair_candidate import inspect_straight_pair
from ..routing.manual_tracks import RoutingManualTrackService, TrackSpec, ViaSpec, _find_pad
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


def _via_from_spec(spec: ViaSpec) -> Via:
    """Create one through via using the existing KiCad IPC model."""
    via = Via()
    via.position = Vector2.from_xy_mm(spec.x_mm, spec.y_mm)
    via.diameter = mm_to_nm(spec.diameter_mm)
    via.drill_diameter = mm_to_nm(spec.drill_mm)
    via.type = ViaType.VT_THROUGH
    net = Net()
    net.name = spec.net_name
    via.net = net
    return via


def _verify_route_items(
    live_board: Board,
    created: list[Track | Via],
    expected_count: int,
    via_required: bool,
) -> bool:
    ids = [getattr(getattr(item, "id", None), "value", None) for item in created]
    if len(ids) != expected_count or not all(ids) or len(set(ids)) != expected_count:
        return False
    current = {
        getattr(getattr(item, "id", None), "value", None) for item in live_board.get_tracks()
    }
    if via_required:
        current.update(
            getattr(getattr(item, "id", None), "value", None) for item in live_board.get_vias()
        )
    return set(ids) <= current


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

    return _publish_route_specs(specs, revision, evidence, candidate_id)


def _publish_route_specs(
    specs: list[TrackSpec],
    revision: str,
    evidence: dict[str, bool | int],
    candidate_id: str,
    *,
    through_via: ViaSpec | None = None,
) -> str:
    """Publish one or multiple preflighted tracks as one native KiCad undo."""

    def refused(reason: str) -> str:
        return json.dumps(
            {"status": "refused", "committed": False, "reason": reason}, sort_keys=True
        )

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

    try:
        if hashlib.sha256(get_board().get_as_string().encode("utf-8")).hexdigest() != revision:
            raise RoutePlanningError("Native board changed before staged application")
        items: list[Track | Via] = [_track_from_spec(spec) for spec in specs]
        if through_via is not None:
            items.append(_via_from_spec(through_via))
        execute_live_board_mutation(
            "route_apply_candidate",
            lambda live_board: cast(list[Track | Via], list(live_board.create_items(items))),
            verifier=lambda board, created: _verify_route_items(
                board, created, len(items), through_via is not None
            ),
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


def _preview_straight_differential_pair(
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
    clearance_mm: float = 0.2,
    max_skew_mm: float = 0.1,
) -> str:
    """Read-only matched straight-pair preview; no autonomous bend or impedance claim."""

    def refused(reason: str) -> str:
        return json.dumps(
            {
                "status": "refused",
                "candidateOnly": True,
                "reason": reason,
            },
            sort_keys=True,
        )

    try:
        plus = json.loads(
            _preview_route_between_pads(
                p_ref1, p_pad1, p_ref2, p_pad2, layer, width_mm, clearance_mm
            )
        )
        minus = json.loads(
            _preview_route_between_pads(
                n_ref1, n_pad1, n_ref2, n_pad2, layer, width_mm, clearance_mm
            )
        )
        if plus.get("status") != "candidate" or minus.get("status") != "candidate":
            return refused("Both lanes require safe native candidate paths")
        revision = plus.get("boardRevision")
        if not isinstance(revision, str) or revision != minus.get("boardRevision"):
            return refused("Board changed while previewing the paired routes")
        if not isinstance(plus.get("segments"), list) or not isinstance(
            minus.get("segments"), list
        ):
            return refused("Invalid native paired segment evidence")
        if len(plus["segments"]) != 1 or len(minus["segments"]) != 1:
            return refused("Only exactly one straight segment per USB lane is supported")
        specs = [TrackSpec(**item) for item in (plus["segments"][0], minus["segments"][0])]
        matching = inspect_straight_pair(specs[0], specs[1], gap_mm=gap_mm, max_skew_mm=max_skew_mm)
        if hashlib.sha256(get_board().get_as_string().encode("utf-8")).hexdigest() != revision:
            return refused("Native board changed during pair preview")
        segments = plus["segments"] + minus["segments"]
        payload = {
            "boardRevision": revision,
            "positivePads": (p_ref1, p_pad1, p_ref2, p_pad2),
            "negativePads": (n_ref1, n_pad1, n_ref2, n_pad2),
            "gapMm": gap_mm,
            "maxSkewMm": max_skew_mm,
            "clearanceMm": clearance_mm,
            "segments": segments,
        }
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return json.dumps(
            {
                "status": "candidate",
                "schemaVersion": "differential-pair-preview.v1",
                "candidateId": digest,
                "boardRevision": revision,
                "candidateOnly": True,
                "drcVerified": False,
                "noBoardMutation": True,
                "netPlus": specs[0].net_name,
                "netMinus": specs[1].net_name,
                "segments": segments,
                "geometry": matching,
                "warning": (
                    "Straight pair geometry only; combined native DRC is required before write. "
                    "Physical impedance and stackup are NOT verified."
                ),
            },
            sort_keys=True,
        )
    except (RoutePlanningError, TypeError, ValueError, KeyError) as exc:
        return refused(str(exc))


def _apply_straight_differential_pair(
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
    clearance_mm: float = 0.2,
    max_skew_mm: float = 0.1,
) -> str:
    """Atomic two-net write only after matched preview and combined native DRC."""

    def refused(reason: str, **details: object) -> str:
        return json.dumps(
            {"status": "refused", "committed": False, "reason": reason, **details},
            sort_keys=True,
        )

    try:
        preview = json.loads(
            _preview_straight_differential_pair(
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
        )
        if preview.get("status") != "candidate":
            return refused(preview.get("reason", "No matched straight pair candidate"))
        if not isinstance(candidate_id, str) or candidate_id != preview["candidateId"]:
            return refused("Stale or wrong matched differential pair candidate ID")
        board_text = get_board().get_as_string()
        revision = preview["boardRevision"]
        if hashlib.sha256(board_text.encode("utf-8")).hexdigest() != revision:
            return refused("Native board changed before pair DRC preflight")
        specs = [TrackSpec(**item) for item in preview["segments"]]
        inspect_straight_pair(specs[0], specs[1], gap_mm=gap_mm, max_skew_mm=max_skew_mm)
        config = get_config()
        if config.project_file is None:
            return refused("Project DRC rules file is unavailable")
        evidence = run_route_drc_preflight(
            board_text,
            specs,
            project_file=config.project_file,
            kicad_cli=config.kicad_cli,
            pair_nets=frozenset((specs[0].net_name, specs[1].net_name)),
        )
    except (RoutePreflightError, RoutePlanningError, KeyError, TypeError, ValueError) as exc:
        return refused(str(exc))
    if not evidence["accepted"]:
        return refused("Native KiCad differential pair DRC rejected the candidate", **evidence)
    if hashlib.sha256(get_board().get_as_string().encode("utf-8")).hexdigest() != revision:
        return refused("Native board changed during differential pair DRC preflight")
    outcome = json.loads(_publish_route_specs(specs, revision, evidence, candidate_id))
    if outcome.get("status") == "applied":
        outcome["pairGeometry"] = preview["geometry"]
        outcome["warning"] = (
            "Both lanes committed as one KiCad undo step, not saved. "
            "Explicit pcb_save and native DRC/reopen required; no impedance certification."
        )
    return json.dumps(outcome, sort_keys=True)


def _register_straight_pair_tools(mcp: FastMCP) -> None:
    """Keep specialized USB tool schemas out of the core routing registration."""

    @mcp.tool()
    @requires_kicad_running
    def route_plan_straight_differential_pair(
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
        clearance_mm: float = 0.2,
        max_skew_mm: float = 0.1,
    ) -> str:
        """READ-only matched straight differential-pair preview.

        Only one H/V/45 segment per lane, exactly parallel and correctly
        spaced. Does not verify physical impedance or create any copper.
        """
        return _preview_straight_differential_pair(
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
    def route_apply_straight_differential_pair_candidate(
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
        clearance_mm: float = 0.2,
        max_skew_mm: float = 0.1,
    ) -> str:
        """WRITE both matched straight lanes in one KiCad Undo after native DRC.

        Reject missing project evidence, stale identity, incorrect geometry
        and DRC regressions. Never automatically save the user's board.
        """
        return _apply_straight_differential_pair(
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

    _register_straight_pair_tools(mcp)
