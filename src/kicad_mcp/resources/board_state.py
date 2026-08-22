"""MCP resources exposing live KiCad state."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from pathlib import Path

from kipy.proto.board.board_types_pb2 import BoardLayer
from mcp.server.fastmcp import FastMCP

from ..config import get_config
from ..connection import KiCadConnectionError, get_board
from ..pcb.board_access import (
    BoardAccessError,
    board_footprints,
    board_nets_filtered,
    board_tracks,
    board_vias,
    board_zones,
)
from ..validation.drc_report import courtyard_violations, report_entries


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
        (index, outcome) for index, outcome in enumerate(outcomes) if outcome.status != "PASS"
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


def _blocked_json(resource: str, exc: Exception) -> str:
    return json.dumps(
        {"resource": resource, "status": "blocked", "error": str(exc)},
        indent=2,
        sort_keys=True,
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_kicad_owned_file(path: Path) -> bool:
    return path.suffix in {
        ".kicad_pro",
        ".kicad_pcb",
        ".kicad_sch",
        ".kicad_sym",
        ".kicad_dru",
        ".kicad_mod",
    }


def _manifest_json() -> str:
    cfg = get_config()
    root = cfg.project_root
    files = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if not _is_kicad_owned_file(path):
            continue
        files.append(
            {
                "path": path.relative_to(root).as_posix(),
                "size_bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
    return json.dumps(
        {"project_dir": str(root), "file_count": len(files), "files": files},
        indent=2,
        sort_keys=True,
    )


def _gate_history_json() -> str:
    from ..tools.validation import _evaluate_project_gate
    from .gate_history import GateHistory

    outcomes = _evaluate_project_gate()
    history = GateHistory.for_active_project()
    for outcome in outcomes:
        history.record(outcome)
    return json.dumps(
        {
            "history": history.latest(10),
            "latest": history.latest(10),
            "regressions": history.regression_check(),
            "current": [
                {
                    "name": outcome.name,
                    "status": outcome.status,
                    "summary": outcome.summary,
                    "details": outcome.details,
                }
                for outcome in outcomes
            ],
        },
        indent=2,
        sort_keys=True,
    )


def _layer_coverage_json() -> str:
    board = get_board()
    zone_counts: dict[str, int] = {}
    for zone in board_zones(board):
        for layer in getattr(zone, "layers", []):
            name = str(BoardLayer.Name(layer)).removeprefix("BL_")
            zone_counts[name] = zone_counts.get(name, 0) + 1
    layers = [
        {
            "layer": layer,
            "coverage_pct": 100.0 if count > 0 else 0.0,
            "zone_count": count,
        }
        for layer, count in sorted(zone_counts.items())
    ]
    return json.dumps({"layers": layers}, indent=2, sort_keys=True)


def _design_intent_json() -> str:
    from ..tools.project import load_design_intent

    return load_design_intent().model_dump_json(indent=2)


def register(mcp: FastMCP) -> None:
    """Register board state resources."""

    @mcp.resource("kicad://board/summary")
    def board_summary_resource() -> str:
        """Live PCB board summary."""
        try:
            board = get_board()
            tracks = board_tracks(board)
            footprints = board_footprints(board)
            vias = board_vias(board)
            nets = board_nets_filtered(board, netclass_filter=None)
        except KiCadConnectionError as exc:
            return f"KiCad is not connected: {exc}"
        except BoardAccessError as exc:
            return f"Board data is unavailable: {exc}"
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

    @mcp.resource("kicad://project/manifest")
    def project_manifest_resource() -> str:
        """JSON manifest of KiCad-owned project files and hashes."""
        try:
            return _manifest_json()
        except Exception as exc:
            return _blocked_json("kicad://project/manifest", exc)

    @mcp.resource("kicad://project/spec")
    def project_spec_resource() -> str:
        """Resolved project design spec including explicit and inferred fields."""
        from ..tools.project import _render_project_spec_resolution, resolve_design_intent

        try:
            return _render_project_spec_resolution(resolve_design_intent())
        except Exception as exc:
            return _blocked_resource("Project design spec", exc)

    @mcp.resource("kicad://project/design_intent")
    def project_design_intent_resource() -> str:
        """Structured JSON view of the persisted project design intent."""
        try:
            return _design_intent_json()
        except Exception as exc:
            return _blocked_json("kicad://project/design_intent", exc)

    @mcp.resource("kicad://project/next_action")
    def project_next_action_resource() -> str:
        """Server-recommended next action derived from the fix queue."""
        from ..project.next_action import ProjectNextActionService
        from ..tools.validation import _evaluate_project_gate

        try:
            return (
                ProjectNextActionService(evaluate_project_gate=_evaluate_project_gate)
                .next_action()
                .text
            )
        except Exception as exc:
            return _blocked_resource("Project next action", exc)

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

    @mcp.resource("kicad://project/gate_history")
    def project_gate_history_resource() -> str:
        """JSON history snapshot of recent project quality gate outcomes."""
        try:
            return _gate_history_json()
        except Exception as exc:
            return _blocked_json("kicad://project/gate_history", exc)

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

    @mcp.resource("kicad://board/layer_coverage")
    def board_layer_coverage_resource() -> str:
        """JSON per-layer copper coverage proxy from zone presence."""
        try:
            return _layer_coverage_json()
        except Exception as exc:
            return _blocked_json("kicad://board/layer_coverage", exc)

    @mcp.resource("kicad://gate/{gate_name}")
    def named_gate_resource(gate_name: str) -> str:
        """Read a specific gate report by name."""
        from ..tools.validation import render_gate_by_name

        try:
            return render_gate_by_name(gate_name)
        except Exception as exc:
            return _blocked_resource(f"Gate '{gate_name}'", exc)

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

    @mcp.resource("kicad://drc/latest")
    def drc_latest_resource() -> str:
        """Latest DRC (design rule check) results from the most recent kicad-cli run."""
        try:
            from ..tools.validation import _run_drc_report

            path, report, error = _run_drc_report("drc_report.json")
            if report is None:
                msg = error or "Run run_drc(save_report=True) to generate a report."
                return f"DRC: No recent report\n- {msg}"
            violations = report_entries(report, "violations")
            unconnected = report_entries(report, "unconnected_items")
            courtyard = courtyard_violations(report)
            lines = [
                "DRC latest results:",
                f"- Violations: {len(violations)}",
                f"- Unconnected items: {len(unconnected)}",
                f"- Courtyard issues: {len(courtyard)}",
                f"- Report file: {path}",
            ]
            if violations:
                for v in violations[:20]:
                    msg = str(v.get("message", v.get("msg", "")))
                    if msg:
                        lines.append(f"  - {msg}")
                if len(violations) > 20:
                    lines.append(f"  ... and {len(violations) - 20} more violations")
            return "\n".join(lines)
        except Exception as exc:
            return f"DRC latest: BLOCKED\n- {exc}"

    @mcp.resource("kicad://erc/latest")
    def erc_latest_resource() -> str:
        """Latest ERC (electrical rule check) results from the most recent kicad-cli run."""
        try:
            from ..tools.validation import _run_erc_report

            path, report, error = _run_erc_report("erc_report.json")
            if report is None:
                msg = error or "Run run_erc(save_report=True) to generate a report."
                return f"ERC: No recent report\n- {msg}"
            violations_raw = report.get("violations")
            violations = list(violations_raw) if isinstance(violations_raw, list) else []
            lines = [
                "ERC latest results:",
                f"- Violations: {len(violations)}",
                f"- Report file: {path}",
            ]
            if violations:
                for v in violations[:20]:
                    msg = str(v.get("message", v.get("msg", "")))
                    if msg:
                        lines.append(f"  - {msg}")
                if len(violations) > 20:
                    lines.append(f"  ... and {len(violations) - 20} more violations")
            return "\n".join(lines)
        except Exception as exc:
            return f"ERC latest: BLOCKED\n- {exc}"

    @mcp.resource("kicad://manufacturing/checklist")
    def manufacturing_checklist_resource() -> str:
        """Manufacturing release checklist for fab-ready handoff."""
        try:
            return "\n".join(
                [
                    "# Manufacturing Release Checklist",
                    "",
                    "## Pre-Release Gates (must all PASS)",
                    "- [ ] project_quality_gate() == PASS",
                    "- [ ] pcb_transfer_quality_gate() == PASS",
                    "- [ ] run_drc() — zero violations",
                    "- [ ] run_erc() — zero violations",
                    "- [ ] check_design_for_manufacture(profile=target_fab) — PASS",
                    "- [ ] validate_footprints_vs_schematic() — all matched",
                    "",
                    "## Gerber & Drill Export",
                    "- [ ] export_gerber() — all copper, mask, silk, paste layers",
                    "- [ ] export_drill() — NC drill + map files",
                    "- [ ] export_pick_and_place() — CPL file",
                    "- [ ] export_bom() — BOM file",
                    "",
                    "## 3D & Documentation",
                    "- [ ] export_3d_step() — STEP model",
                    "- [ ] export_pcb_pdf() — fabrication drawing",
                    "",
                    "## Final Release",
                    "- [ ] export_manufacturing_package() — complete release zip",
                    "- [ ] vcs_tag_release(tag, message) — git tag the release",
                    "",
                    "## Verification",
                    "- [ ] mfg_check_import_support() — import compatibility verified",
                    "- [ ] mfg_correct_cpl_rotations() — CPL rotations corrected",
                    "- [ ] Read kicad://project/manifest — all files tracked",
                    "- [ ] Read kicad://project/gate_history — no regressions",
                ]
            )
        except Exception as exc:
            return f"Manufacturing checklist: BLOCKED\n- {exc}"
