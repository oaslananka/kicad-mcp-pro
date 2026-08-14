"""Advanced routing helpers, rule orchestration, and FreeRouting integration."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, cast

from kipy.board_types import Net, Track
from kipy.geometry import Vector2
from mcp.server.fastmcp import Context, FastMCP

from ..config import get_config
from ..connection import board_transaction, get_board
from ..errors import ManualStepRequiredError
from ..models.common import _PadLike
from ..models.pcb import AddTrackInput
from ..models.tool_result import ArtifactRef, StateDelta, ToolResult
from ..pcb.board_access import board_nets_filtered, board_pads, board_tracks
from ..pcb.geometry import point_xy_mm, track_segment_length_mm
from ..utils.freerouting import FreeRoutingRunner
from ..utils.layers import resolve_layer
from ..utils.router_core import apply_ses_to_pcb
from ..utils.sexpr import _sexpr_string
from ..utils.units import mm_to_nm
from .export_support import _get_pcb_file
from .metadata import headless_compatible, requires_dependency, requires_kicad_running
from .pcb import _transactional_board_write
from .project import load_design_intent as _load_design_intent
from .routing_rules import _load_rules_content, _mm, _rules_file_path, _upsert_rule, _write_rule

__all__ = [
    "_load_rules_content",
    "_mm",
    "_rules_file_path",
    "_upsert_rule",
    "_write_rule",
]
_STATE_DIRNAME = ".kicad-mcp"
_TUNING_PROFILES_FILENAME = "tuning_profiles.json"
_TUNING_ASSIGNMENTS_FILENAME = "tuning_profile_assignments.json"


def _find_pad(reference: str, pad_number: str) -> _PadLike | None:
    for pad in cast(list[_PadLike], board_pads(get_board())):
        if pad.parent.reference_field.text.value == reference and str(pad.number) == str(
            pad_number
        ):
            return pad
    return None


def _list_board_net_names() -> set[str]:
    return {
        str(net.name)
        for net in cast(list[Net], board_nets_filtered(get_board(), netclass_filter=None))
        if getattr(net, "name", "")
    }


def _current_track_length_mm(net_name: str) -> float:
    length = 0.0
    for track in cast(list[Track], board_tracks(get_board())):
        track_net = getattr(getattr(track, "net", None), "name", "")
        if track_net == net_name:
            length += track_segment_length_mm(track)
    return length


def _current_track_length_for_pattern_mm(net_pattern: str) -> float:
    if "*" not in net_pattern:
        return _current_track_length_mm(net_pattern)
    regex = re.compile("^" + re.escape(net_pattern).replace(r"\*", ".*") + "$")
    matching_names = [name for name in _list_board_net_names() if regex.fullmatch(name) is not None]
    return sum(_current_track_length_mm(name) for name in matching_names)


def _infer_diff_pair_base(net_p: str, net_n: str) -> str | None:
    candidates = [
        (r"(.+)_P$", r"(.+)_N$"),
        (r"(.+)_DP$", r"(.+)_DN$"),
        (r"(.+)\+$", r"(.+)-$"),
        (r"(.+)P$", r"(.+)N$"),
    ]
    for pattern_p, pattern_n in candidates:
        match_p = re.fullmatch(pattern_p, net_p)
        match_n = re.fullmatch(pattern_n, net_n)
        if match_p and match_n and match_p.group(1) == match_n.group(1):
            return match_p.group(1).rstrip("_-+/")
    return None


def _net_class_rule_body(
    net_class: str,
    width_mm: float,
    clearance_mm: float,
    via_diameter_mm: float,
    via_drill_mm: float,
) -> tuple[str, str]:
    track_width_constraint = (
        f"  (constraint track_width (min {_mm(width_mm)}) "
        f"(opt {_mm(width_mm)}) (max {_mm(width_mm)}))"
    )
    via_diameter_constraint = (
        f"  (constraint via_diameter (min {_mm(via_diameter_mm)}) "
        f"(opt {_mm(via_diameter_mm)}) (max {_mm(via_diameter_mm)}))"
    )
    via_drill_constraint = (
        f"  (constraint via_drill (min {_mm(via_drill_mm)}) "
        f"(opt {_mm(via_drill_mm)}) (max {_mm(via_drill_mm)}))"
    )
    name = f"Net class {net_class}"
    body = "\n".join(
        [
            f"(rule {_sexpr_string(name)}",
            f"  (condition \"A.NetClass == '{net_class}'\")",
            track_width_constraint,
            f"  (constraint clearance (min {_mm(clearance_mm)}))",
            via_diameter_constraint,
            via_drill_constraint,
            ")",
        ]
    )
    return name, body


def _diff_pair_rule_body(
    net_p: str,
    net_n: str,
    width_mm: float,
    gap_mm: float,
    length_tolerance_mm: float,
) -> tuple[str, str]:
    base_name = _infer_diff_pair_base(net_p, net_n)
    condition = (
        f"A.inDiffPair('{base_name}')"
        if base_name is not None
        else f"A.NetName == '{net_p}' || A.NetName == '{net_n}'"
    )
    track_width_constraint = (
        f"  (constraint track_width (min {_mm(width_mm)}) "
        f"(opt {_mm(width_mm)}) (max {_mm(width_mm)}))"
    )
    gap_constraint = (
        f"  (constraint diff_pair_gap (min {_mm(gap_mm)}) (opt {_mm(gap_mm)}) (max {_mm(gap_mm)}))"
    )
    name = f"Differential pair {net_p} {net_n}"
    body = "\n".join(
        [
            f"(rule {_sexpr_string(name)}",
            f'  (condition "{condition}")',
            track_width_constraint,
            gap_constraint,
            f"  (constraint skew (max {_mm(length_tolerance_mm)}))",
            ")",
        ]
    )
    return name, body


def _length_tune_rule_body(net_name: str, target_mm: float, tolerance_mm: float) -> tuple[str, str]:
    name = f"Length tune {net_name}"
    body = "\n".join(
        [
            f"(rule {_sexpr_string(name)}",
            f"  (condition \"A.NetName == '{net_name}'\")",
            f"  (constraint length (min {_mm(max(target_mm - tolerance_mm, 0.0))}) "
            f"(opt {_mm(target_mm)}) (max {_mm(target_mm + tolerance_mm)}))",
            ")",
        ]
    )
    return name, body


def _diff_pair_length_rule_body(
    net_name_p: str,
    net_name_n: str,
    target_length_mm: float,
) -> list[tuple[str, str]]:
    rules = [
        _length_tune_rule_body(net_name_p, target_length_mm, 0.1),
        _length_tune_rule_body(net_name_n, target_length_mm, 0.1),
    ]
    pair_rule_name = f"Length match {net_name_p} {net_name_n}"
    pair_rule_body = "\n".join(
        [
            f"(rule {_sexpr_string(pair_rule_name)}",
            f"  (condition \"A.NetName == '{net_name_p}' || A.NetName == '{net_name_n}'\")",
            "  (constraint skew (max 0.1000mm))",
            ")",
        ]
    )
    rules.append((pair_rule_name, pair_rule_body))
    return rules


def _relative_project_path(path: Path) -> str:
    cfg = get_config()
    try:
        return str(path.resolve().relative_to(cfg.project_root))
    except ValueError:
        return str(path.resolve())


def _routing_state_dir() -> Path:
    cfg = get_config()
    if cfg.project_dir is None:
        raise ValueError(
            "No active project directory is configured. Call kicad_set_project() first."
        )
    target = cfg.project_dir / _STATE_DIRNAME
    target.mkdir(parents=True, exist_ok=True)
    return target


def _load_state_file(filename: str, default: dict[str, object]) -> dict[str, object]:
    path = _routing_state_dir() / filename
    if not path.exists():
        path.write_text(json.dumps(default, indent=2), encoding="utf-8")
        return dict(default)
    return cast(dict[str, object], json.loads(path.read_text(encoding="utf-8")))


def _save_state_file(filename: str, payload: dict[str, object]) -> Path:
    path = _routing_state_dir() / filename
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _net_pattern_condition(net_pattern: str) -> str:
    if "*" in net_pattern:
        regex = re.escape(net_pattern).replace(r"\*", ".*")
        return f"A.NetName =~ '{regex}'"
    return f"A.NetName == '{net_pattern}'"


def _delay_to_length_mm(delay_ps: float, propagation_speed_factor: float) -> float:
    return delay_ps * 0.299792458 * propagation_speed_factor


async def _report_progress(
    ctx: Context[Any, Any, Any] | None,
    progress: float,
    total: float,
    message: str,
) -> None:
    if ctx is None:
        return
    try:
        await ctx.report_progress(progress, total, message)
    except ValueError:
        return


def register(mcp: FastMCP) -> None:
    """Register routing tools."""

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
        payload = AddTrackInput(
            x1_mm=x1_mm,
            y1_mm=y1_mm,
            x2_mm=x2_mm,
            y2_mm=y2_mm,
            layer=layer,
            width_mm=width_mm,
            net_name=net_name,
        )
        track = Track()
        track.start = Vector2.from_xy_mm(payload.x1_mm, payload.y1_mm)
        track.end = Vector2.from_xy_mm(payload.x2_mm, payload.y2_mm)
        track.layer = resolve_layer(payload.layer)
        track.width = mm_to_nm(payload.width_mm)
        if payload.net_name:
            net = Net()
            net.name = payload.net_name
            track.net = net
        with board_transaction() as board:
            board.create_items([track])
        return "Single track routed successfully."

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
        """Create a simple orthogonal route between two pads."""
        start_pad = _find_pad(ref1, pad1)
        end_pad = _find_pad(ref2, pad2)
        if start_pad is None or end_pad is None:
            return "One or both pads were not found on the active board."

        start_x, start_y = point_xy_mm(start_pad.position)
        end_x, end_y = point_xy_mm(end_pad.position)
        net_name = start_pad.net.name or end_pad.net.name or ""
        payloads = [
            AddTrackInput(
                x1_mm=start_x,
                y1_mm=start_y,
                x2_mm=end_x,
                y2_mm=start_y,
                layer=layer,
                width_mm=width_mm,
                net_name=net_name,
            ),
            AddTrackInput(
                x1_mm=end_x,
                y1_mm=start_y,
                x2_mm=end_x,
                y2_mm=end_y,
                layer=layer,
                width_mm=width_mm,
                net_name=net_name,
            ),
        ]
        tracks: list[Track] = []
        for payload in payloads:
            track = Track()
            track.start = Vector2.from_xy_mm(payload.x1_mm, payload.y1_mm)
            track.end = Vector2.from_xy_mm(payload.x2_mm, payload.y2_mm)
            track.layer = resolve_layer(payload.layer)
            track.width = mm_to_nm(payload.width_mm)
            if payload.net_name:
                net = Net()
                net.name = payload.net_name
                track.net = net
            tracks.append(track)
        with board_transaction() as board:
            board.create_items(tracks)
        return (
            f"Created an orthogonal two-segment route from {ref1}:{pad1} to {ref2}:{pad2}. "
            "Run DRC to verify the path."
        )

    @mcp.tool()
    @headless_compatible
    def route_export_dsn(output_path: str = "output/routing/board.dsn") -> ToolResult:
        """Export a Specctra DSN for FreeRouting; may require a one-time KiCad GUI step.

        Uses headless ``kicad-cli pcb export specctra`` when the CLI supports it. If KiCad
        cannot export the DSN headlessly, returns a human-gated result describing the
        File > Export > Specctra DSN step instead of failing opaquely.
        """
        runner = FreeRoutingRunner()
        pcb_file = _get_pcb_file()
        try:
            dsn_path = runner.export_dsn(pcb_file, Path(output_path))
        except ManualStepRequiredError as exc:
            manual = ToolResult.failure("route_export_dsn", str(exc))
            manual.human_gate_required = True
            return manual
        except (RuntimeError, ValueError) as exc:
            return ToolResult.failure(
                "route_export_dsn", f"Specctra DSN export is unavailable: {exc}"
            )
        return ToolResult.success(
            "route_export_dsn",
            changed=True,
            artifacts=[ArtifactRef(path=str(dsn_path), kind="dsn")],
            state_delta=StateDelta(
                summary=(
                    f"Specctra DSN ready at {_relative_project_path(dsn_path)}. "
                    "You can route it with route_autoroute_freerouting()."
                ),
                changed_files=[str(dsn_path)],
            ),
        )

    @mcp.tool()
    @headless_compatible
    def route_import_ses(ses_path: str = "output/routing/board.ses") -> ToolResult:
        """Stage a routed Specctra SES and surface the required KiCad GUI import step.

        KiCad has no headless SES import, so this stages the session and returns a
        human-gated result: the routing is applied by running File > Import > Specctra
        Session in the PCB Editor. It never reports the board as routed when it is not
        (``changed=False``, ``human_gate_required=True``).
        """
        runner = FreeRoutingRunner()
        try:
            resolved_ses = get_config().resolve_within_project(Path(ses_path))
            staged = runner.stage_ses(resolved_ses)
        except (FileNotFoundError, RuntimeError, ValueError) as exc:
            return ToolResult.failure("route_import_ses", f"Specctra SES staging failed: {exc}")
        result = ToolResult.success(
            "route_import_ses",
            changed=False,
            artifacts=[ArtifactRef(path=str(staged), kind="ses")],
            state_delta=StateDelta(
                summary=(
                    f"Specctra SES session staged at {_relative_project_path(staged)}. "
                    "KiCad has no headless SES import: open the PCB Editor and run "
                    "File > Import > Specctra Session to apply the routing, then save."
                ),
                changed_files=[str(staged)],
            ),
        )
        result.human_gate_required = True
        return result

    @mcp.tool()
    @headless_compatible
    def route_apply_ses(ses_path: str = "output/routing/board.ses") -> ToolResult:
        """Apply a routed Specctra SES to the active board headlessly -- no GUI step.

        KiCad has no headless SES import, so this parses the routed session and writes its
        segments and vias directly into the .kicad_pcb via the round-trip-safe S-expression
        layer; the rest of the board file is untouched. Re-applying the same session is
        deterministic and idempotent (it replaces, not duplicates, the routing). This closes
        the manual File > Import > Specctra Session step. Run run_drc() afterwards to verify.
        """
        cfg = get_config()
        try:
            resolved_ses = cfg.resolve_within_project(Path(ses_path))
        except (ValueError, OSError) as exc:
            return ToolResult.failure("route_apply_ses", f"Invalid SES path: {exc}")
        if not resolved_ses.exists():
            return ToolResult.failure(
                "route_apply_ses", f"Routed SES not found: {_relative_project_path(resolved_ses)}"
            )
        try:
            ses_text = resolved_ses.read_text(encoding="utf-8", errors="ignore")
        except (ValueError, OSError) as exc:
            return ToolResult.failure("route_apply_ses", f"Could not read the SES: {exc}")

        class _NoRouteInSessionError(ValueError):
            pass

        class _RouteAlreadyAppliedError(ValueError):
            pass

        route = None

        def apply_routing(current: str) -> str:
            nonlocal route
            updated, route = apply_ses_to_pcb(current, ses_text)
            if not route.segments and not route.vias:
                raise _NoRouteInSessionError
            if updated == current:
                raise _RouteAlreadyAppliedError
            return updated

        try:
            pcb_file = Path(_transactional_board_write(apply_routing))
        except _NoRouteInSessionError:
            return ToolResult.failure(
                "route_apply_ses",
                f"The session at {_relative_project_path(resolved_ses)} contained no routed "
                "segments or vias.",
            )
        except _RouteAlreadyAppliedError:
            return ToolResult.success(
                "route_apply_ses",
                changed=False,
                state_delta=StateDelta(
                    summary="Routing already applied; the board is unchanged (idempotent)."
                ),
            )
        except (ValueError, OSError) as exc:
            return ToolResult.failure("route_apply_ses", f"Could not apply the SES: {exc}")

        if route is None:  # pragma: no cover - set by the mutator on every success path
            return ToolResult.failure("route_apply_ses", "Routing produced no result to apply.")
        return ToolResult.success(
            "route_apply_ses",
            changed=True,
            artifacts=[ArtifactRef(path=str(pcb_file), kind="pcb")],
            state_delta=StateDelta(
                summary=(
                    f"Applied {len(route.segments)} segment(s) and {len(route.vias)} via(s) "
                    f"across {len(route.net_names)} net(s) to "
                    f"{_relative_project_path(pcb_file)} headlessly. "
                    "Run run_drc() to verify the routed board is clean."
                ),
                changed_files=[str(pcb_file)],
            ),
        )

    @mcp.tool()
    @headless_compatible
    @requires_dependency("freerouting")
    async def route_autoroute_freerouting(
        dsn_path: str = "output/routing/board.dsn",
        ses_path: str = "output/routing/board.ses",
        net_classes_to_ignore: list[str] | None = None,
        exclude_nets: list[str] | None = None,
        max_passes: int = 100,
        thread_count: int = 4,
        use_docker: bool = True,
        freerouting_jar_path: str | None = None,
        drc_report_path: str = "output/routing/freerouting.drc.json",
        ctx: Context[Any, Any, Any] | None = None,
    ) -> ToolResult:
        """Run FreeRouting after placement, then surface the KiCad import step.

        DSN export is attempted headlessly; FreeRouting runs via Docker or a local JAR.
        Applying the routed SES session back to the board has no headless path in KiCad,
        so this returns a human-gated result (``human_gate_required=True``) describing the
        File > Import > Specctra Session step — it does not claim the board is routed when
        the session has only been staged. If headless DSN export is unavailable, the
        manual export step is surfaced instead of failing opaquely.

        When the experimental MCP Tasks extension is enabled
        (``KICAD_MCP_ENABLE_TASKS=1``), the routing runs in the background and a
        task reference is returned immediately. The caller can poll ``tasks/get``
        for completion and ``tasks/cancel`` to abort routing.
        """

        async def _run() -> ToolResult:
            """Inner coroutine that does the actual work."""
            cfg = get_config()
            runner = FreeRoutingRunner()
            pcb_file = _get_pcb_file()
            dsn_target = cfg.resolve_within_project(Path(dsn_path))
            ses_target = cfg.resolve_within_project(Path(ses_path))
            drc_target = (
                cfg.resolve_within_project(Path(drc_report_path)) if drc_report_path else None
            )

            try:
                import anyio

                await _report_progress(ctx, 10, 100, "Exporting DSN for FreeRouting...")
                dsn_file = await anyio.to_thread.run_sync(
                    lambda: runner.export_dsn(pcb_file, dsn_target)
                )
                await _report_progress(ctx, 40, 100, "Running FreeRouting...")
                result = await anyio.to_thread.run_sync(
                    lambda: runner.run_freerouting(
                        dsn_file,
                        ses_target,
                        max_passes=max_passes,
                        thread_count=thread_count,
                        use_docker=use_docker,
                        freerouting_jar_path=Path(freerouting_jar_path).expanduser()
                        if freerouting_jar_path
                        else None,
                        net_classes_to_ignore=net_classes_to_ignore,
                        exclude_nets=exclude_nets,
                        drc_report_path=drc_target,
                    )
                )
            except ManualStepRequiredError as exc:
                manual = ToolResult.failure("route_autoroute_freerouting", str(exc))
                manual.human_gate_required = True
                return manual
            except (FileNotFoundError, RuntimeError, ValueError) as exc:
                return ToolResult.failure(
                    "route_autoroute_freerouting", f"FreeRouting autoroute failed: {exc}"
                )

            if result.returncode != 0:
                return ToolResult.failure(
                    "route_autoroute_freerouting",
                    (
                        "FreeRouting autoroute failed.\n"
                        f"Mode: {result.mode}\n"
                        f"Command: {' '.join(result.command)}\n"
                        f"stderr: {result.stderr or 'unknown error'}"
                    ),
                )

            ses_output = result.output_ses
            ses_path_obj = Path(ses_output) if ses_output else None
            if ses_path_obj is None:
                return ToolResult.failure(
                    "route_autoroute_freerouting",
                    "FreeRouting autoroute failed: no SES output path was reported.",
                )
            ses_ok = ses_path_obj.exists() and ses_path_obj.stat().st_size > 0
            if not ses_ok:
                return ToolResult.failure(
                    "route_autoroute_freerouting",
                    (
                        "FreeRouting ran but the SES session file is missing or empty — "
                        "this is a known KiCad 10 / Specctra round-trip failure.\n"
                        "Workaround: open the PCB in KiCad GUI and import the DSN manually "
                        f"via File > Import > Specctra Session "
                        f"({_relative_project_path(dsn_file)}).\n"
                        f"SES path checked: {ses_path_obj}"
                    ),
                )

            ignore_text = (
                ", ".join([*(net_classes_to_ignore or []), *(exclude_nets or [])]) or "none"
            )
            route_stats = result
            apply_error: str | None = None
            applied_route = None
            applied_pcb_file: Path | None = None

            # Attempt headless SES apply via the round-trip-safe S-expression layer.
            # This closes the FreeRouting loop without a GUI step on supported KiCad versions.
            await _report_progress(ctx, 85, 100, "Applying SES to board headlessly...")
            try:
                ses_text = ses_path_obj.read_text(encoding="utf-8", errors="ignore")

                class _NoRouteError(ValueError):
                    pass

                class _AlreadyAppliedError(ValueError):
                    pass

                def _apply_ses(current: str) -> str:
                    nonlocal applied_route
                    updated, applied_route = apply_ses_to_pcb(current, ses_text)
                    if not applied_route.segments and not applied_route.vias:
                        raise _NoRouteError
                    if updated == current:
                        raise _AlreadyAppliedError
                    return updated

                applied_pcb_file = Path(
                    await anyio.to_thread.run_sync(lambda: _transactional_board_write(_apply_ses))
                )
            except (_NoRouteError, _AlreadyAppliedError, ValueError, OSError) as exc:
                apply_error = str(exc)
            except Exception as exc:  # noqa: BLE001
                apply_error = f"Unexpected error during headless SES apply: {exc}"

            await _report_progress(ctx, 100, 100, "FreeRouting routing complete.")

            if apply_error is None and applied_pcb_file is not None and applied_route is not None:
                seg_count = len(applied_route.segments)
                via_count = len(applied_route.vias)
                net_count = len(applied_route.net_names)
                return ToolResult.success(
                    "route_autoroute_freerouting",
                    changed=True,
                    artifacts=[
                        ArtifactRef(path=str(dsn_file), kind="dsn"),
                        ArtifactRef(path=str(ses_path_obj), kind="ses"),
                        ArtifactRef(path=str(applied_pcb_file), kind="pcb"),
                    ],
                    state_delta=StateDelta(
                        summary=(
                            f"FreeRouting routed and applied: {seg_count} segment(s), "
                            f"{via_count} via(s), {net_count} net(s).\n"
                            f"Mode: {route_stats.mode}\n"
                            f"DSN: {_relative_project_path(dsn_file)}\n"
                            f"SES: {_relative_project_path(ses_path_obj)}\n"
                            f"Routed: {route_stats.routed_pct:.2f}% ({route_stats.total_nets} "
                            f"net(s), {len(route_stats.unrouted_nets)} unrouted)\n"
                            f"Pass count: {route_stats.pass_count}\n"
                            f"Wall time: {route_stats.wall_seconds:.3f}s\n"
                            f"Ignored net classes: {ignore_text}\n"
                            f"Thread count: {thread_count}\n"
                            "Next step: run run_drc() to verify the routed board, "
                            "then pcb_fill_all_zones() to fill copper pours.\n"
                            f"stdout tail: {route_stats.stdout_tail or '(empty)'}"
                        ),
                        changed_files=[str(applied_pcb_file)],
                    ),
                )

            # Headless apply failed — fall back to staging for the GUI import step.
            try:
                staged = await anyio.to_thread.run_sync(lambda: runner.stage_ses(ses_path_obj))
            except (FileNotFoundError, RuntimeError, ValueError) as exc:
                return ToolResult.failure(
                    "route_autoroute_freerouting",
                    f"FreeRouting autoroute failed while staging the SES file: {exc}",
                )

            fallback = ToolResult.success(
                "route_autoroute_freerouting",
                changed=False,
                artifacts=[
                    ArtifactRef(path=str(dsn_file), kind="dsn"),
                    ArtifactRef(path=str(staged), kind="ses"),
                ],
                state_delta=StateDelta(
                    summary=(
                        "FreeRouting produced a routed session; headless apply failed, "
                        "use File > Import > Specctra Session in KiCad GUI to finish.\n"
                        f"Headless apply error: {apply_error or 'unknown'}\n"
                        f"Mode: {route_stats.mode}\n"
                        f"DSN: {_relative_project_path(dsn_file)}\n"
                        f"SES: {_relative_project_path(staged)}\n"
                        f"Routed: {route_stats.routed_pct:.2f}% ({route_stats.total_nets} "
                        f"net(s), {len(route_stats.unrouted_nets)} unrouted)\n"
                        f"Pass count: {route_stats.pass_count}\n"
                        f"Wall time: {route_stats.wall_seconds:.3f}s\n"
                        f"Ignored net classes: {ignore_text}\n"
                        f"Thread count: {thread_count}\n"
                        "Manual step: open the PCB in KiCad and run "
                        "File > Import > Specctra Session, then save the board.\n"
                        f"stdout tail: {route_stats.stdout_tail or '(empty)'}"
                    ),
                    changed_files=[str(dsn_file), str(staged)],
                ),
            )
            fallback.human_gate_required = True
            return fallback

        # Check if the experimental MCP Tasks extension is active
        task_mgr = getattr(ctx.fastmcp, "_task_manager", None) if ctx is not None else None
        if task_mgr is not None:
            task = await task_mgr.run_and_wait(
                description="FreeRouting autoroute",
                coro_factory=_run,
                ttl_s=7200,
            )
            return ToolResult.success(
                "route_autoroute_freerouting",
                changed=False,
                state_delta=StateDelta(
                    summary=(
                        "FreeRouting autoroute started as a background task.\n"
                        f"Task ID: {task.taskId}\n"
                        "Use tasks/get to poll for completion and tasks/cancel to abort."
                    ),
                ),
            )

        return await _run()

    @mcp.tool()
    @headless_compatible
    def route_set_net_class_rules(
        net_class: str,
        width_mm: float,
        clearance_mm: float,
        via_diameter_mm: float,
        via_drill_mm: float,
    ) -> str:
        """Write net-class routing constraints into the active .kicad_dru file."""
        rule_name, rule_body = _net_class_rule_body(
            net_class,
            width_mm,
            clearance_mm,
            via_diameter_mm,
            via_drill_mm,
        )
        try:
            path = _write_rule(rule_name, rule_body)
        except (OSError, ValueError) as exc:
            return f"Net-class rule update failed: {exc}"
        return (
            f"Net-class routing rule '{rule_name}' written to {path}.\n"
            f"Track width: {_mm(width_mm)}, clearance: {_mm(clearance_mm)}, "
            f"via: {_mm(via_diameter_mm)} / drill {_mm(via_drill_mm)}."
        )

    @mcp.tool()
    @headless_compatible
    def route_differential_pair(
        net_p: str,
        net_n: str,
        layer: str = "F_Cu",
        width_mm: float = 0.2,
        gap_mm: float = 0.2,
        length_tolerance_mm: float = 0.1,
    ) -> str:
        """Write differential-pair routing constraints for a pair of nets."""
        board_nets = _list_board_net_names()
        missing = [name for name in (net_p, net_n) if name not in board_nets]
        if missing:
            return (
                "Differential-pair routing rule was not written. "
                f"Missing nets: {', '.join(missing)}"
            )

        rule_name, rule_body = _diff_pair_rule_body(
            net_p,
            net_n,
            width_mm,
            gap_mm,
            length_tolerance_mm,
        )
        try:
            path = _write_rule(rule_name, rule_body)
        except (OSError, ValueError) as exc:
            return f"Differential-pair rule update failed: {exc}"
        return (
            f"Differential-pair routing rule '{rule_name}' written to {path}.\n"
            f"Layer intent: {layer}, width: {_mm(width_mm)}, gap: {_mm(gap_mm)}, "
            f"max skew: {_mm(length_tolerance_mm)}."
        )

    @mcp.tool()
    @headless_compatible
    def route_tune_length(
        net_name: str,
        target_mm: float,
        meander_amplitude_mm: float = 0.5,
        tolerance_mm: float = 0.1,
    ) -> str:
        """Write a length-tuning rule and report the current delta for a net."""
        board_nets = _list_board_net_names()
        if net_name not in board_nets:
            return (
                "Length-tuning rule was not written. "
                f"Net '{net_name}' was not found on the active board."
            )

        current_length = _current_track_length_mm(net_name)
        delta = target_mm - current_length
        rule_name, rule_body = _length_tune_rule_body(net_name, target_mm, tolerance_mm)
        try:
            path = _write_rule(rule_name, rule_body)
        except (OSError, ValueError) as exc:
            return f"Length-tuning rule update failed: {exc}"

        status = "within tolerance" if abs(delta) <= tolerance_mm else "needs tuning"
        return (
            f"Length-tuning rule '{rule_name}' written to {path}.\n"
            f"Current length: {current_length:.3f} mm\n"
            f"Target length: {target_mm:.3f} mm\n"
            f"Delta: {delta:.3f} mm ({status})\n"
            f"Suggested meander amplitude: {meander_amplitude_mm:.3f} mm"
        )

    @mcp.tool()
    @headless_compatible
    def route_create_tuning_profile(
        name: str,
        layer: str,
        trace_impedance_ohm: float,
        propagation_speed_factor: float,
    ) -> str:
        """Create or update a KiCad 10-style time-domain tuning profile."""
        if not 0.05 <= propagation_speed_factor <= 1.0:
            raise ValueError("propagation_speed_factor must be between 0.05 and 1.0.")
        resolved_layer = resolve_layer(layer)
        _ = resolved_layer
        state = _load_state_file(_TUNING_PROFILES_FILENAME, {"profiles": {}})
        profiles = cast(dict[str, object], state.setdefault("profiles", {}))
        profiles[name] = {
            "layer": layer,
            "trace_impedance_ohm": trace_impedance_ohm,
            "propagation_speed_factor": propagation_speed_factor,
        }
        path = _save_state_file(_TUNING_PROFILES_FILENAME, state)
        return f"Tuning profile '{name}' saved to {path}."

    @mcp.tool()
    @headless_compatible
    def route_list_tuning_profiles() -> str:
        """List configured time-domain tuning profiles."""
        state = _load_state_file(_TUNING_PROFILES_FILENAME, {"profiles": {}})
        return json.dumps(state.get("profiles", {}), indent=2)

    @mcp.tool()
    @headless_compatible
    def route_apply_tuning_profile(net_pattern: str, profile_name: str) -> str:
        """Assign a named tuning profile to a net or wildcard net group."""
        profiles_state = _load_state_file(_TUNING_PROFILES_FILENAME, {"profiles": {}})
        profiles = cast(dict[str, dict[str, object]], profiles_state.get("profiles", {}))
        profile = profiles.get(profile_name)
        if profile is None:
            return f"Tuning profile '{profile_name}' was not found."

        assignments_state = _load_state_file(_TUNING_ASSIGNMENTS_FILENAME, {"assignments": {}})
        assignments = cast(dict[str, object], assignments_state.setdefault("assignments", {}))
        assignments[net_pattern] = {
            "profile_name": profile_name,
            "layer": profile.get("layer", ""),
        }
        path = _save_state_file(_TUNING_ASSIGNMENTS_FILENAME, assignments_state)
        return (
            f"Tuning profile '{profile_name}' assigned to '{net_pattern}'.\n"
            f"Assignments file: {path}"
        )

    @mcp.tool()
    @headless_compatible
    def route_tune_time_domain(
        net_or_group: str,
        target_delay_ps: float,
        tolerance_ps: float = 10.0,
        layer: str | None = None,
    ) -> str:
        """Create a KiCad 10-inspired time-domain tuning rule with a length fallback."""
        profiles_state = _load_state_file(_TUNING_PROFILES_FILENAME, {"profiles": {}})
        profiles = cast(dict[str, dict[str, object]], profiles_state.get("profiles", {}))
        propagation_speed_factor = 0.5
        profile_impedance_ohm = 50.0
        effective_er: float | None = None
        if layer:
            matching = next(
                (
                    item
                    for item in profiles.values()
                    if str(item.get("layer", "")).casefold() == layer.casefold()
                ),
                None,
            )
            if matching is not None:
                raw_factor = matching.get("propagation_speed_factor", propagation_speed_factor)
                if isinstance(raw_factor, int | float):
                    propagation_speed_factor = float(raw_factor)
                raw_impedance = matching.get("trace_impedance_ohm", profile_impedance_ohm)
                if isinstance(raw_impedance, int | float):
                    profile_impedance_ohm = float(raw_impedance)

        if layer:
            try:
                from ..utils.impedance import (
                    propagation_delay_ps_per_mm,
                    solve_width_for_impedance,
                    trace_impedance,
                )
                from .pcb import _current_stackup_specs, _impedance_context_for_layer

                specs = _current_stackup_specs()
                trace_type, height_mm, er, copper_oz = _impedance_context_for_layer(specs, layer)
                solved_width_mm = solve_width_for_impedance(
                    profile_impedance_ohm,
                    height_mm,
                    er,
                    trace_type=trace_type,
                    copper_oz=copper_oz,
                )
                _, effective_er = trace_impedance(
                    solved_width_mm,
                    height_mm,
                    er,
                    trace_type=trace_type,
                    copper_oz=copper_oz,
                )
                delay_ps_per_mm = propagation_delay_ps_per_mm(effective_er)
                target_mm = target_delay_ps / delay_ps_per_mm
                tolerance_mm = tolerance_ps / delay_ps_per_mm
            except ValueError:
                target_mm = _delay_to_length_mm(target_delay_ps, propagation_speed_factor)
                tolerance_mm = _delay_to_length_mm(tolerance_ps, propagation_speed_factor)
        else:
            target_mm = _delay_to_length_mm(target_delay_ps, propagation_speed_factor)
            tolerance_mm = _delay_to_length_mm(tolerance_ps, propagation_speed_factor)

        current_length = _current_track_length_for_pattern_mm(net_or_group)
        required_extension = target_mm - current_length
        rule_name = f"Time-domain tune {net_or_group}"
        condition = _net_pattern_condition(net_or_group)
        rule_body = "\n".join(
            [
                f"(rule {_sexpr_string(rule_name)}",
                f'  (condition "{condition}")',
                f"  (constraint length (min {_mm(max(target_mm - tolerance_mm, 0.0))}) "
                f"(opt {_mm(target_mm)}) (max {_mm(target_mm + tolerance_mm)}))",
                f"  (constraint delay (min {max(target_delay_ps - tolerance_ps, 0.0):.3f}ps) "
                f"(opt {target_delay_ps:.3f}ps) (max {target_delay_ps + tolerance_ps:.3f}ps))",
                ")",
            ]
        )
        try:
            path = _write_rule(rule_name, rule_body)
        except (OSError, ValueError) as exc:
            return f"Time-domain tuning rule update failed: {exc}"

        lines = [
            f"Time-domain tuning rule '{rule_name}' written to {path}.",
            f"Target delay: {target_delay_ps:.3f} ps",
            f"Tolerance: {tolerance_ps:.3f} ps",
            f"Current measured length: {current_length:.3f} mm",
            f"Computed target length: {target_mm:.3f} mm",
            f"Required extension: {required_extension:.3f} mm",
        ]
        if layer:
            lines.append(f"Layer: {layer}")
        if effective_er is not None:
            lines.append(f"Effective dielectric constant: {effective_er:.4f}")
        else:
            lines.append(f"Fallback target length: {target_mm:.3f} mm")
        return "\n".join(lines)

    @mcp.tool()
    @headless_compatible
    def tune_diff_pair_length(net_name_p: str, net_name_n: str, target_length_mm: float) -> str:
        """Write matched-length rules for both nets in a differential pair."""
        board_nets = _list_board_net_names()
        missing = [name for name in (net_name_p, net_name_n) if name not in board_nets]
        if missing:
            return (
                "Differential-pair length tuning rules were not written. "
                f"Missing nets: {', '.join(missing)}"
            )

        written_paths: list[str] = []
        for rule_name, rule_body in _diff_pair_length_rule_body(
            net_name_p,
            net_name_n,
            target_length_mm,
        ):
            try:
                path = _write_rule(rule_name, rule_body)
            except (OSError, ValueError) as exc:
                return f"Differential-pair length tuning failed: {exc}"
            written_paths.append(str(path))

        current_p = _current_track_length_mm(net_name_p)
        current_n = _current_track_length_mm(net_name_n)
        skew = abs(current_p - current_n)
        return (
            "Differential-pair length rules updated.\n"
            f"Rules file: {written_paths[-1]}\n"
            f"{net_name_p}: {current_p:.3f} mm\n"
            f"{net_name_n}: {current_n:.3f} mm\n"
            f"Current skew: {skew:.3f} mm\n"
            f"Target length: {target_length_mm:.3f} mm"
        )

    @mcp.tool()
    @headless_compatible
    def generate_board_constraints() -> ToolResult:
        """Generate .kicad_dru rules and net-class constraints from the project design intent.

        Reads power_rails and interfaces from the stored design intent
        (project_get_design_spec / import_design_spec) and synthesises:
        - Minimum trace widths from IPC-2221 current-capacity formula (power rails)
        - Net-class clearance + width + via rules (per-rail)
        - Differential-pair skew / length / impedance rules (per interface)
        - HV creepage/clearance rules for rails above 50 V

        Run drc_check_rule_conflicts() afterwards to surface any conflicts.
        """
        intent = _load_design_intent()
        generated: list[str] = []
        conflicts: list[str] = []
        rules_path: Path | None = None

        # IPC-2221 simplified trace width calculator (external, ΔT = 10 °C)
        def _ipc_width_mm(current_a: float) -> float:
            if current_a <= 0:
                return 0.127
            raw: float = current_a / (0.048 * float(10**0.44))
            width_mm: float = raw ** (1.0 / 0.725)
            return float(max(0.127, round(width_mm, 4)))

        for rail in intent.power_rails:
            rail_name: str = rail.name
            current_a: float = rail.current_max_a
            voltage_v: float = rail.voltage_v
            width_mm = _ipc_width_mm(current_a)
            clearance_mm = 0.2
            if voltage_v > 50:
                # Basic creepage: 0.5 mm per 100 V for basic insulation (IPC-2221 grade B1)
                clearance_mm = max(0.5, voltage_v / 100.0 * 0.5)
            via_dia = max(0.6, width_mm + 0.3)
            safe_name = re.sub(r"\W", "_", rail_name).strip("_") or "RAIL"
            rule_name = f"pwr_{safe_name}"
            rule_body = "\n".join(
                [
                    f"(rule {_sexpr_string(rule_name)}",
                    f"  (constraint track_width (min {_mm(width_mm)}) (opt {_mm(width_mm)}))",
                    f"  (constraint clearance (min {_mm(clearance_mm)}))",
                    f"  (constraint via_diameter (min {_mm(via_dia)}) (opt {_mm(via_dia)}))",
                    f"  (constraint via_drill (min {_mm(via_drill)}) (opt {_mm(via_drill)}))",
                    f'  (condition "A.NetClass == \\"{safe_name}\\"")',
                    ")",
                ]
            )
            try:
                rules_path = _write_rule(rule_name, rule_body)
                generated.append(
                    f"Rail '{rail_name}': width>={_mm(width_mm)} clearance>={_mm(clearance_mm)} "
                    f"via={_mm(via_dia)}/drill={_mm(via_drill)}"
                )
                if voltage_v > 50:
                    generated.append(
                        f"  HV note: {voltage_v}V rail; clearance derived from IPC-2221 creepage"
                    )
            except (OSError, ValueError) as exc:
                conflicts.append(f"Rail '{rail_name}': {exc}")

        # Interface-level differential-pair and impedance constraints
        for iface in intent.interfaces:
            kind: str = iface.kind
            net_prefix: str = iface.net_prefix
            if not net_prefix:
                continue
            dp_name = re.sub(r"\W", "_", net_prefix).strip("_") or "IFACE"
            if iface.differential and iface.impedance_target_ohm:
                imp = iface.impedance_target_ohm
                # Approximate differential-pair gap from impedance
                # 100 Ω diff → ~0.13 mm gap/0.18 mm width on FR4 2-layer
                gap_mm = round(imp / 750.0, 3)
                width_mm = round(gap_mm * 1.4, 3)
                skew_mm = (iface.diff_skew_max_ps or 10.0) * 0.06  # 0.06 mm/ps approx
                rule_name = f"dp_{dp_name}"
                rule_body = "\n".join(
                    [
                        f"(rule {_sexpr_string(rule_name)}",
                        f"  (constraint track_width (opt {_mm(max(0.1, width_mm))}))",
                        f"  (constraint diff_pair_gap (opt {_mm(max(0.1, gap_mm))}))",
                        "  (constraint diff_pair_max_uncoupled_length"
                        f" (max {_mm(max(0.5, skew_mm))}))",
                        f'  (condition "A.NetClass == \\"{dp_name}\\"")',
                        ")",
                    ]
                )
                try:
                    rules_path = _write_rule(rule_name, rule_body)
                    generated.append(
                        f"Interface '{kind}' ({net_prefix}): diff-pair "
                        f"width={_mm(max(0.1, width_mm))} gap={_mm(max(0.1, gap_mm))} "
                        f"skew<={_mm(max(0.5, skew_mm))}"
                    )
                except (OSError, ValueError) as exc:
                    conflicts.append(f"Interface '{kind}': {exc}")
            elif iface.length_target_mm:
                rule_name = f"len_{dp_name}"
                tol = iface.length_match_tolerance_mm
                rule_body = "\n".join(
                    [
                        f"(rule {_sexpr_string(rule_name)}",
                        f"  (constraint length (min {_mm(max(0, iface.length_target_mm - tol))}) "
                        f"(max {_mm(iface.length_target_mm + tol)}))",
                        f'  (condition "A.NetClass == \\"{dp_name}\\"")',
                        ")",
                    ]
                )
                try:
                    rules_path = _write_rule(rule_name, rule_body)
                    generated.append(
                        f"Interface '{kind}' ({net_prefix}): length "
                        f"{_mm(iface.length_target_mm)} ±{_mm(tol)}"
                    )
                except (OSError, ValueError) as exc:
                    conflicts.append(f"Interface '{kind}' length: {exc}")

        if not generated and not conflicts:
            return ToolResult.failure(
                "generate_board_constraints",
                "No power_rails or interfaces found in the design intent. "
                "Call import_design_spec() first to load your design requirements.",
            )

        lines = ["Generated constraints from design intent:"]
        lines.extend(f"  {item}" for item in generated)
        if conflicts:
            lines.append("Conflicts/errors (review manually):")
            lines.extend(f"  {item}" for item in conflicts)
        lines.append(
            "Run drc_check_rule_conflicts() to surface rule overlaps, "
            "then run run_drc() to verify all constraints are met."
        )
        return ToolResult.success(
            "generate_board_constraints",
            changed=True,
            artifacts=[ArtifactRef(path=str(rules_path), kind="dru")] if rules_path else [],
            state_delta=StateDelta(
                summary="\n".join(lines),
                changed_files=[str(rules_path)] if rules_path else [],
            ),
        )
