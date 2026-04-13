"""Advanced routing helpers, rule orchestration, and FreeRouting integration."""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import cast

import structlog
from kipy.board_types import Net, Track
from kipy.geometry import Vector2
from mcp.server.fastmcp import FastMCP

from ..config import get_config
from ..connection import board_transaction, get_board
from ..models.common import _PadLike
from ..models.pcb import AddTrackInput
from ..utils.freerouting import FreeRoutingRunner
from ..utils.layers import resolve_layer
from ..utils.sexpr import _extract_block, _sexpr_string
from ..utils.units import _coord_nm, mm_to_nm, nm_to_mm
from .export import _get_pcb_file

logger = structlog.get_logger(__name__)


def _find_pad(reference: str, pad_number: str) -> _PadLike | None:
    for pad in cast(list[_PadLike], get_board().get_pads()):
        if pad.parent.reference_field.text.value == reference and str(pad.number) == str(
            pad_number
        ):
            return pad
    return None


def _list_board_net_names() -> set[str]:
    return {
        str(net.name)
        for net in cast(list[Net], get_board().get_nets(netclass_filter=None))
        if getattr(net, "name", "")
    }


def _track_length_mm(track: Track) -> float:
    dx = _coord_nm(track.end, "x") - _coord_nm(track.start, "x")
    dy = _coord_nm(track.end, "y") - _coord_nm(track.start, "y")
    return nm_to_mm(int(round(math.hypot(dx, dy))))


def _current_track_length_mm(net_name: str) -> float:
    length = 0.0
    for track in cast(list[Track], get_board().get_tracks()):
        track_net = getattr(getattr(track, "net", None), "name", "")
        if track_net == net_name:
            length += _track_length_mm(track)
    return length


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


def _rules_file_path() -> Path:
    cfg = get_config()
    if cfg.project_dir is None:
        raise ValueError(
            "No project directory is configured. Call kicad_set_project() "
            "before editing routing rules."
        )

    existing = sorted(cfg.project_dir.glob("*.kicad_dru"))
    if existing:
        return existing[0]

    if cfg.project_file is not None:
        return cfg.project_dir / f"{cfg.project_file.stem}.kicad_dru"
    return cfg.project_dir / "design_rules.kicad_dru"


def _is_balanced(content: str) -> bool:
    depth = 0
    in_string = False
    escaped = False
    for char in content:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth < 0:
                return False
    return depth == 0 and not in_string


def _load_rules_content(path: Path) -> str:
    if not path.exists():
        return "(rules)\n"
    content = path.read_text(encoding="utf-8")
    if not content.strip():
        return "(rules)\n"
    if not _is_balanced(content):
        raise ValueError(
            "Refusing to write an invalid design rules file with unbalanced parentheses."
        )
    return content


def _upsert_rule(content: str, rule_name: str, rule_body: str) -> str:
    search = f'(rule {_sexpr_string(rule_name)}'
    index = content.find(search)
    if index >= 0:
        block, consumed = _extract_block(content, index)
        if not block or consumed == 0:
            raise ValueError(f"Could not replace existing rule block for {rule_name}.")
        updated = content[:index] + rule_body + content[index + consumed :]
    else:
        stripped = content.rstrip()
        insert_at = stripped.rfind(")")
        if insert_at < 0:
            raise ValueError("The design rules file does not contain a root '(rules ...)' form.")
        prefix = stripped[:insert_at].rstrip()
        suffix = stripped[insert_at:]
        updated = f"{prefix}\n{rule_body}\n{suffix}\n"
    if not _is_balanced(updated):
        raise ValueError(f"Refusing to write invalid design rules after updating {rule_name}.")
    return updated


def _write_rule(rule_name: str, rule_body: str) -> Path:
    path = _rules_file_path()
    content = _load_rules_content(path)
    updated = _upsert_rule(content, rule_name, rule_body)
    path.write_text(updated, encoding="utf-8")
    return path


def _mm(value: float) -> str:
    return f"{value:.4f}mm"


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
            f'(rule {_sexpr_string(name)}',
            f'  (condition "A.NetClass == \'{net_class}\'")',
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
        f"  (constraint diff_pair_gap (min {_mm(gap_mm)}) "
        f"(opt {_mm(gap_mm)}) (max {_mm(gap_mm)}))"
    )
    name = f"Differential pair {net_p} {net_n}"
    body = "\n".join(
        [
            f'(rule {_sexpr_string(name)}',
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
            f'(rule {_sexpr_string(name)}',
            f'  (condition "A.NetName == \'{net_name}\'")',
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
            f'(rule {_sexpr_string(pair_rule_name)}',
            f'  (condition "A.NetName == \'{net_name_p}\' || A.NetName == \'{net_name_n}\'")',
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


def register(mcp: FastMCP) -> None:
    """Register routing tools."""

    @mcp.tool()
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

        start_x = nm_to_mm(_coord_nm(start_pad.position, "x"))
        start_y = nm_to_mm(_coord_nm(start_pad.position, "y"))
        end_x = nm_to_mm(_coord_nm(end_pad.position, "x"))
        end_y = nm_to_mm(_coord_nm(end_pad.position, "y"))
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
    def route_export_dsn(output_path: str = "output/routing/board.dsn") -> str:
        """Stage a Specctra DSN file for FreeRouting."""
        runner = FreeRoutingRunner()
        pcb_file = _get_pcb_file()
        try:
            dsn_path = runner.export_dsn(pcb_file, Path(output_path))
        except (RuntimeError, ValueError) as exc:
            return f"Specctra DSN export is unavailable: {exc}"
        return (
            f"Specctra DSN ready at {dsn_path}. "
            "You can route it with route_autoroute_freerouting()."
        )

    @mcp.tool()
    def route_import_ses(ses_path: str = "output/routing/board.ses") -> str:
        """Stage a Specctra SES file and explain the KiCad import step."""
        runner = FreeRoutingRunner()
        pcb_file = _get_pcb_file()
        try:
            resolved_ses = get_config().resolve_within_project(Path(ses_path))
            staged = runner.import_ses(pcb_file, resolved_ses)
        except (FileNotFoundError, RuntimeError, ValueError) as exc:
            return f"Specctra SES import is unavailable: {exc}"
        return (
            f"Specctra SES session staged at {staged}. "
            "KiCad 10 still requires importing the session from the PCB Editor UI."
        )

    @mcp.tool()
    def route_autoroute_freerouting(
        dsn_path: str = "output/routing/board.dsn",
        ses_path: str = "output/routing/board.ses",
        net_classes_to_ignore: list[str] | None = None,
        max_passes: int = 100,
        thread_count: int = 4,
        use_docker: bool = True,
        freerouting_jar_path: str | None = None,
    ) -> str:
        """Run FreeRouting on a Specctra DSN file and stage the resulting SES session."""
        cfg = get_config()
        runner = FreeRoutingRunner()
        pcb_file = _get_pcb_file()
        dsn_target = cfg.resolve_within_project(Path(dsn_path))
        ses_target = cfg.resolve_within_project(Path(ses_path))

        try:
            dsn_file = runner.export_dsn(pcb_file, dsn_target)
            result = runner.run_freerouting(
                dsn_file,
                ses_target,
                max_passes=max_passes,
                thread_count=thread_count,
                use_docker=use_docker,
                freerouting_jar_path=Path(freerouting_jar_path).expanduser()
                if freerouting_jar_path
                else None,
                net_classes_to_ignore=net_classes_to_ignore,
            )
            staged = runner.import_ses(pcb_file, result.output_ses)
        except (FileNotFoundError, RuntimeError, ValueError) as exc:
            return f"FreeRouting autoroute failed: {exc}"

        if result.returncode != 0:
            return (
                "FreeRouting autoroute failed.\n"
                f"Mode: {result.mode}\n"
                f"Command: {' '.join(result.command)}\n"
                f"stderr: {result.stderr or 'unknown error'}"
            )

        ignore_text = ", ".join(net_classes_to_ignore or []) or "none"
        return (
            "FreeRouting completed successfully.\n"
            f"Mode: {result.mode}\n"
            f"DSN: {_relative_project_path(dsn_file)}\n"
            f"SES: {_relative_project_path(staged)}\n"
            f"Ignored net classes: {ignore_text}\n"
            f"Thread count advisory: {thread_count}"
        )

    @mcp.tool()
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
    def tune_track_length(net_name: str, target_length_mm: float) -> str:
        """Backward-compatible alias for route_tune_length()."""
        logger.warning("deprecated_tune_track_length", replacement="route_tune_length")
        return str(route_tune_length(net_name, target_length_mm))

    @mcp.tool()
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
