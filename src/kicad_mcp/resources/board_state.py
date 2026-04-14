"""MCP resources exposing live KiCad state."""

from __future__ import annotations

from collections.abc import Iterable

from mcp.server.fastmcp import FastMCP

from ..config import get_config
from ..connection import KiCadConnectionError, get_board


def _queue_reason(details: Iterable[str], summary: str) -> str:
    ignored_prefixes = (
        "Footprints analysed:",
        "Board frame:",
        "Density:",
        "Connector checks:",
        "Decoupling pair checks:",
        "RF keepout checks:",
        "Power-tree refs checked:",
        "Analog refs checked:",
        "Digital refs checked:",
        "Sensor-cluster refs checked:",
        "Placement score:",
    )
    for detail in details:
        cleaned = detail.strip()
        if not cleaned or cleaned.startswith(ignored_prefixes):
            continue
        if cleaned.startswith("FAIL: "):
            return cleaned[6:]
        if cleaned.startswith("WARN: "):
            return cleaned[6:]
        return cleaned
    return summary


def _suggested_tool(name: str) -> str:
    return {
        "Schematic": "run_erc()",
        "Schematic connectivity": "schematic_connectivity_gate()",
        "PCB": "run_drc()",
        "Placement": "pcb_score_placement()",
        "PCB transfer": "pcb_transfer_quality_gate()",
        "Manufacturing": "manufacturing_quality_gate()",
        "Footprint parity": "validate_footprints_vs_schematic()",
    }.get(name, "project_quality_gate()")


def _render_fix_queue() -> str:
    from ..tools.validation import _evaluate_project_gate

    outcomes = _evaluate_project_gate()
    actionable = [
        (index, outcome)
        for index, outcome in enumerate(outcomes)
        if outcome.status != "PASS"
    ]
    if not actionable:
        return "\n".join(
            [
                "Project fix queue",
                "- No blocking issues. The full project quality gate is PASS.",
            ]
        )

    actionable.sort(key=lambda item: (0 if item[1].status == "BLOCKED" else 1, item[0]))
    lines = [
        "Project fix queue",
        f"- Blocking items: {len(actionable)}",
    ]
    for number, (_, outcome) in enumerate(actionable, start=1):
        severity = "critical" if outcome.status == "BLOCKED" else "high"
        reason = _queue_reason(outcome.details, outcome.summary)
        lines.append(
            f"{number}. [{severity}] {outcome.name}: {reason} "
            f"Suggested tool: {_suggested_tool(outcome.name)}"
        )
    return "\n".join(lines)


def _blocked_resource(title: str, exc: Exception) -> str:
    return f"{title}: BLOCKED\n- Could not evaluate this resource: {exc}"


def register(mcp: FastMCP) -> None:
    """Register board state resources."""

    @mcp.resource("kicad://board/summary")
    def board_summary_resource() -> str:
        """Live PCB board summary."""
        try:
            board = get_board()
        except KiCadConnectionError as exc:
            return f"KiCad is not connected: {exc}"

        tracks = board.get_tracks()
        footprints = board.get_footprints()
        vias = board.get_vias()
        nets = board.get_nets(netclass_filter=None)
        return (
            f"Board summary\n"
            f"- Tracks: {len(tracks)}\n"
            f"- Vias: {len(vias)}\n"
            f"- Footprints: {len(footprints)}\n"
            f"- Nets: {len(nets)}"
        )

    @mcp.resource("kicad://project/info")
    def project_info_resource() -> str:
        """Current project configuration."""
        cfg = get_config()
        return (
            f"Project directory: {cfg.project_dir}\n"
            f"Project file: {cfg.project_file}\n"
            f"PCB file: {cfg.pcb_file}\n"
            f"Schematic file: {cfg.sch_file}\n"
            f"Output directory: {cfg.output_dir}"
        )

    @mcp.resource("kicad://board/netlist")
    def board_netlist_resource() -> str:
        """Current board S-expression, bounded for safety."""
        cfg = get_config()
        try:
            board = get_board()
        except KiCadConnectionError as exc:
            return f"KiCad is not connected: {exc}"

        data = board.get_as_string()
        if len(data) > cfg.max_text_response_chars:
            return f"{data[: cfg.max_text_response_chars]}\n... [truncated]"
        return data

    @mcp.resource("kicad://project/quality_gate")
    def project_quality_gate_resource() -> str:
        """Latest full project quality gate report."""
        from ..tools.validation import _evaluate_project_gate, _render_project_gate_report

        try:
            return _render_project_gate_report(_evaluate_project_gate())
        except Exception as exc:
            return _blocked_resource("Project quality gate", exc)

    @mcp.resource("kicad://project/fix_queue")
    def project_fix_queue_resource() -> str:
        """Prioritized blocking issues derived from the project quality gate."""
        try:
            return _render_fix_queue()
        except Exception as exc:
            return f"Project fix queue\n- BLOCKED: {exc}"

    @mcp.resource("kicad://schematic/connectivity")
    def schematic_connectivity_resource() -> str:
        """Latest schematic connectivity gate report."""
        from ..tools.validation import _evaluate_schematic_connectivity_gate, _format_gate

        try:
            return _format_gate(_evaluate_schematic_connectivity_gate())
        except Exception as exc:
            return _blocked_resource("Schematic connectivity quality gate", exc)

    @mcp.resource("kicad://board/placement_quality")
    def board_placement_quality_resource() -> str:
        """Latest placement score and hard-fail placement findings."""
        from ..tools.validation import _format_placement_score, _placement_analysis

        try:
            analysis, blocked = _placement_analysis()
            if blocked is not None:
                return "\n".join(
                    [
                        "Placement score: BLOCKED",
                        f"- {blocked.summary}",
                        *[f"- {detail}" for detail in blocked.details],
                    ]
                )
            if analysis is None:
                return "Placement score: BLOCKED\n- Placement analysis returned no data."
            return _format_placement_score(analysis)
        except Exception as exc:
            return f"Placement score: BLOCKED\n- Could not evaluate this resource: {exc}"
