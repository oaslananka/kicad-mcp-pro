"""Manufacturer-specific DFM profile tools."""

from __future__ import annotations

import json
import re

# nosemgrep: python37-compatibility-importlib2
from importlib import resources
from pathlib import Path
from typing import Any, Protocol, cast

import structlog
from kipy.board_types import Track, Via
from kipy.proto.board.board_types_pb2 import BoardLayer
from mcp.server.mcpserver import MCPServer as FastMCP

from ..config import get_config
from ..connection import KiCadConnectionError, get_board
from ..discovery import get_cli_capabilities
from ..models.verdict import Verdict, VerdictReport
from ..utils.sexpr import _extract_block
from ..utils.units import nm_to_mm
from ..validation import drc_runner
from ..validation.drc_report import courtyard_violations, report_entries
from .export_support import _ensure_output_dir, _get_pcb_file, _run_cli_variants
from .metadata import headless_compatible
from .pth_annular_audit import audit_pth_annular_ring_lines

logger = structlog.get_logger(__name__)
DEFAULT_PROFILE = ("JLCPCB", "standard")
FLOAT_PATTERN = r"-?\d+(?:\.\d+)?"


class _BoardMetricsLike(Protocol):
    """Subset of board access used by the DFM profile helpers."""

    def get_enabled_layers(self) -> list[int]:
        raise NotImplementedError

    def get_tracks(self) -> list[Track]:
        raise NotImplementedError

    def get_vias(self) -> list[Via]:
        raise NotImplementedError


def _profile_resource_name(manufacturer: str, tier: str) -> str:
    return f"{manufacturer.strip().lower()}_{tier.strip().lower()}.json"


def _available_profile_names() -> list[str]:
    profile_root = resources.files("kicad_mcp.dfm_profiles")
    return sorted(
        entry.name[:-5] for entry in profile_root.iterdir() if entry.name.endswith(".json")
    )


def _load_profile(manufacturer: str, tier: str) -> dict[str, Any]:
    resource_name = _profile_resource_name(manufacturer, tier)
    resource_root = resources.files("kicad_mcp.dfm_profiles")
    resource = resource_root / resource_name
    if not resource.is_file():
        available = ", ".join(_available_profile_names())
        raise ValueError(
            f"Unknown DFM profile '{manufacturer}/{tier}'. Available profiles: {available}"
        )
    return cast(dict[str, Any], json.loads(resource.read_text(encoding="utf-8")))


def _active_profile_path() -> Path:
    return _ensure_output_dir() / "active_dfm_profile.json"


def _write_active_profile_selection(manufacturer: str, tier: str) -> Path:
    path = _active_profile_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"manufacturer": manufacturer, "tier": tier}, indent=2),
        encoding="utf-8",
    )
    return path


def _selected_profile() -> dict[str, Any]:
    path = _active_profile_path()
    if path.exists():
        selection = cast(dict[str, str], json.loads(path.read_text(encoding="utf-8")))
        return _load_profile(
            selection.get("manufacturer", DEFAULT_PROFILE[0]),
            selection.get("tier", DEFAULT_PROFILE[1]),
        )
    return _load_profile(*DEFAULT_PROFILE)


def _try_get_board() -> object | None:
    try:
        return get_board()
    except (KiCadConnectionError, OSError) as exc:
        logger.debug("dfm_board_runtime_unavailable", error=str(exc))
        return None


def _board_metrics() -> dict[str, float | int | None]:
    board = _try_get_board()
    if board is None:
        return {
            "copper_layers": None,
            "min_track_width_mm": None,
            "min_via_drill_mm": None,
            "min_via_diameter_mm": None,
            "via_count": None,
        }

    board_metrics = cast(_BoardMetricsLike, board)
    layers = [
        layer for layer in board_metrics.get_enabled_layers() if "_Cu" in BoardLayer.Name(layer)
    ]
    tracks = board_metrics.get_tracks()
    vias = board_metrics.get_vias()
    return {
        "copper_layers": len(layers),
        "min_track_width_mm": min(
            (nm_to_mm(track.width) for track in tracks),
            default=None,
        ),
        "min_via_drill_mm": min(
            (nm_to_mm(via.drill_diameter) for via in vias),
            default=None,
        ),
        "min_via_diameter_mm": min(
            (nm_to_mm(via.diameter) for via in vias),
            default=None,
        ),
        "via_count": len(vias),
    }


def _run_drc_report(report_name: str) -> tuple[Path, dict[str, Any] | None, str | None]:
    cfg = get_config()
    result = drc_runner.run_drc_report(
        report_name,
        pcb_file=_get_pcb_file(),
        output_dir=_ensure_output_dir(),
        run_cli_variants=_run_cli_variants,
        capabilities=get_cli_capabilities(cfg.kicad_cli),
    )
    path, report, error = result.as_legacy_tuple()
    return path, cast(dict[str, Any] | None, report), error


def _outline_bounds_mm(content: str) -> tuple[float, float, float, float] | None:
    xs: list[float] = []
    ys: list[float] = []
    cursor = 0
    while cursor < len(content):
        next_line = content.find("(gr_line", cursor)
        next_rect = content.find("(gr_rect", cursor)
        indices = [index for index in (next_line, next_rect) if index != -1]
        if not indices:
            break
        start = min(indices)
        block, length = _extract_block(content, start)
        if not block:
            break
        cursor = start + length
        if '(layer "Edge.Cuts")' not in block:
            continue
        match = re.search(
            rf"\(start\s+({FLOAT_PATTERN})\s+({FLOAT_PATTERN})\).*?"
            rf"\(end\s+({FLOAT_PATTERN})\s+({FLOAT_PATTERN})\)",
            block,
            re.DOTALL,
        )
        if match is None:
            continue
        xs.extend([float(match.group(1)), float(match.group(3))])
        ys.extend([float(match.group(2)), float(match.group(4))])
    if not xs or not ys:
        return None
    return min(xs), min(ys), max(xs), max(ys)


def _board_outline_area_cm2() -> tuple[float | None, float | None, float | None]:
    pcb_text = _get_pcb_file().read_text(encoding="utf-8", errors="ignore")
    bounds = _outline_bounds_mm(pcb_text)
    if bounds is None:
        return None, None, None
    min_x_mm, min_y_mm, max_x_mm, max_y_mm = bounds
    width_mm = max_x_mm - min_x_mm
    height_mm = max_y_mm - min_y_mm
    return width_mm, height_mm, (width_mm * height_mm) / 100.0


def _format_status(status: str, message: str) -> str:
    return f"- {status}: {message}"


def _status_lines_verdict(lines: list[str]) -> Verdict:
    if any(line.startswith("- FAIL:") for line in lines):
        return "FAIL"
    if any(line.startswith("- WARN:") for line in lines):
        return "WARN"
    return "PASS"


def _dfm_verdict_report(lines: list[str]) -> VerdictReport:
    verdict = _status_lines_verdict(lines)
    text = "\n".join(lines)
    return VerdictReport.from_text_verdict(
        text=text,
        summary="DFM profile check passed."
        if verdict == "PASS"
        else "DFM profile check has actionable manufacturing findings.",
        verdict=verdict,
        source="dfm_run_manufacturer_check",
        evidence=[{"lines": lines}],
        remediation="Resolve FAIL/WARN DFM profile lines, then rerun dfm_run_manufacturer_check()."
        if verdict != "PASS"
        else "",
        next_action="Resolve DFM profile findings before manufacturing handoff."
        if verdict != "PASS"
        else "Proceed to manufacturing_quality_gate().",
        metadata={"profile_check": True},
    )


def _check_board_metrics_rules(
    metrics: dict[str, Any],
    rules: dict[str, float | int],
) -> tuple[list[str], int]:
    lines: list[str] = []
    checks = 0

    copper_layers = metrics["copper_layers"]
    if copper_layers is None:
        lines.append(
            _format_status("WARN", "Copper layer count unavailable without an active board.")
        )
    else:
        checks += 1
        status = "PASS" if copper_layers <= int(rules["max_layers"]) else "FAIL"
        lines.append(
            _format_status(
                status,
                f"Copper layers {copper_layers} <= max {int(rules['max_layers'])}",
            )
        )

    min_track_width_mm = metrics["min_track_width_mm"]
    if min_track_width_mm is None:
        lines.append(
            _format_status("WARN", "Minimum track width unavailable without an active board.")
        )
    else:
        checks += 1
        status = "PASS" if min_track_width_mm >= float(rules["min_trace_width_mm"]) else "FAIL"
        lines.append(
            _format_status(
                status,
                f"Minimum track width {min_track_width_mm:.3f} mm "
                f">= {float(rules['min_trace_width_mm']):.3f} mm",
            )
        )

    min_via_drill_mm = metrics["min_via_drill_mm"]
    if min_via_drill_mm is None:
        lines.append(
            _format_status("WARN", "Minimum via drill unavailable without an active board.")
        )
    else:
        checks += 1
        status = "PASS" if min_via_drill_mm >= float(rules["min_drill_mm"]) else "FAIL"
        lines.append(
            _format_status(
                status,
                f"Minimum via drill {min_via_drill_mm:.3f} mm "
                f">= {float(rules['min_drill_mm']):.3f} mm",
            )
        )

    return lines, checks


def _check_drc_report_lines(
    report: dict[str, Any] | None,
    report_status: str,
    classification_error: str | None,
) -> tuple[list[str], int]:
    if report is None:
        if report_status == "malformed":
            return [
                _format_status(
                    "WARN",
                    f"DRC report malformed ({classification_error or 'unknown schema error'}).",
                )
            ], 0
        return [
            _format_status(
                "WARN",
                f"DRC report unavailable ({classification_error or 'unknown error'}).",
            )
        ], 0

    violations = report_entries(report, "violations")
    unconnected = report_entries(report, "unconnected_items")
    courtyard = courtyard_violations(report)
    silk = [entry for entry in violations if "silk" in str(entry.get("description", "")).lower()]

    lines = [
        _format_status("PASS" if not violations else "FAIL", f"DRC violations: {len(violations)}"),
        _format_status(
            "PASS" if not unconnected else "FAIL", f"Unconnected items: {len(unconnected)}"
        ),
        _format_status("PASS" if not courtyard else "WARN", f"Courtyard issues: {len(courtyard)}"),
        _format_status("PASS" if not silk else "WARN", f"Silk overlap hints: {len(silk)}"),
    ]
    return lines, 4


def _check_jlcpcb_pth_2layer_process_lines(
    *,
    manufacturer: str,
    rules: dict[str, float | int],
    copper_layers: int | None,
) -> list[str]:
    """Require fab approval even when a partial nominal round-pad scan runs.

    Native metrics include vias and DRC, not individual finished PTH geometry.
    A separate source-only nominal circular-pad audit may follow when available.
    """
    if manufacturer.upper() != "JLCPCB" or copper_layers != 2:
        return []
    minimum = rules.get("min_pth_annular_ring_2layer_1oz_mm")
    if minimum is None:
        return [
            _format_status(
                "WARN",
                "JLCPCB 2-layer/1-oz PTH minimum is not configured; "
                "individual PTH annular lands require written CAM acceptance.",
            )
        ]
    preferred = rules.get("recommended_pth_annular_ring_2layer_1oz_mm")
    return [
        _format_status(
            "WARN",
            f"JLCPCB 2-layer/1-oz PTH annular ring absolute minimum "
            f"{float(minimum):.3f} mm"
            + (f", recommended {float(preferred):.3f} mm" if preferred is not None else "")
            + "; published values apply to 1-oz copper (actual copper weight "
            "is not checked). A separate source-board scan may measure simple "
            "nominal circular PTH rings only; noncircular PTH, plated slots and "
            "finished hole tolerances are not measured. Verify copper weight, "
            "real land/hole geometry and obtain written CAM signoff before fabrication.",
        )
    ]


def _dfm_check_lines(
    profile: dict[str, Any],
    *,
    heading: str | None = None,
) -> list[str]:
    rules = cast(dict[str, float | int], profile["rules"])
    metrics = _board_metrics()
    try:
        _, report, error = _run_drc_report("dfm_profile_check.json")
    except (ValueError, OSError):
        # A missing/unreadable project board cannot be a DFM PASS. Keep the
        # saved-PTH review reachable and report unavailable native DRC.
        report, error = None, "saved PCB source unavailable"
    report_status, classification_error = drc_runner.classify_legacy_drc_result(report, error)
    if report_status in {"unavailable", "malformed"}:
        report = None

    metric_lines, metric_checks = _check_board_metrics_rules(metrics, rules)
    drc_lines, drc_checks = _check_drc_report_lines(report, report_status, classification_error)
    pth_process_lines = _check_jlcpcb_pth_2layer_process_lines(
        manufacturer=str(profile["manufacturer"]),
        rules=rules,
        copper_layers=int(metrics["copper_layers"])
        if metrics["copper_layers"] is not None
        else None,
    )

    # Source-only circular PTH scan; no claim that the installed KiCad board,
    # fabricated copper weight or CAM finished drill tolerances are qualified.
    if str(profile["manufacturer"]).upper() == "JLCPCB" and metrics["copper_layers"] == 2:
        minimum = rules.get("min_pth_annular_ring_2layer_1oz_mm")
        if minimum is not None:
            try:
                pth_process_lines.extend(
                    audit_pth_annular_ring_lines(
                        _get_pcb_file().read_text(encoding="utf-8"), float(minimum)
                    )
                )
            except (OSError, ValueError):
                pth_process_lines.append(
                    _format_status(
                        "WARN",
                        "Saved PCB PTH geometry unavailable; "
                        "individual pads/slots remain unverified for written CAM approval.",
                    )
                )

    lines = [
        heading or "DFM profile check:",
        f"- Profile: {profile['manufacturer']} / {profile['tier']}",
        *metric_lines,
        *drc_lines,
        *pth_process_lines,
        _format_status(
            "WARN",
            "Manual review: annular ring, copper-to-edge, and silkscreen text size "
            f"against {profile['manufacturer']} {profile['tier']} fab notes.",
        ),
    ]
    lines.insert(2, f"- Checks run: {metric_checks + drc_checks}")
    return lines


def _cost_lines(
    profile: dict[str, Any],
    quantity: int,
) -> list[str]:
    pricing = cast(dict[str, float], profile["pricing"])
    width_mm, height_mm, area_cm2 = _board_outline_area_cm2()
    metrics = _board_metrics()
    copper_layers = int(metrics["copper_layers"] or 2)
    via_count = int(metrics["via_count"] or 0)
    if area_cm2 is None:
        area_cm2 = 25.0

    layer_multiplier = 1.0 + (max(copper_layers - 2, 0) * float(pricing["extra_layer_multiplier"]))
    setup_cost = float(pricing["setup_usd"])
    area_cost = quantity * area_cm2 * float(pricing["per_sq_cm_usd"]) * layer_multiplier
    drill_cost = quantity * via_count * float(pricing["per_drill_usd"])
    total_cost = setup_cost + area_cost + drill_cost

    lines = [
        "Manufacturing cost estimate:",
        f"- Profile: {profile['manufacturer']} / {profile['tier']}",
        f"- Quantity: {quantity}",
    ]
    if width_mm is not None and height_mm is not None:
        lines.append(f"- Board size: {width_mm:.2f} x {height_mm:.2f} mm")
    else:
        lines.append("- Board size: unavailable, using a conservative 25.00 cm^2 estimate")
    lines.extend(
        [
            f"- Board area: {area_cm2:.2f} cm^2",
            f"- Copper layers: {copper_layers}",
            f"- Via count estimate: {via_count}",
            f"- Setup: ${setup_cost:.2f}",
            f"- Area cost: ${area_cost:.2f}",
            f"- Drill cost: ${drill_cost:.2f}",
            f"- Total: ${total_cost:.2f}",
        ]
    )
    return lines


def register(mcp: FastMCP) -> None:
    """Register DFM tools."""

    @mcp.tool()
    @headless_compatible
    def dfm_load_manufacturer_profile(
        manufacturer: str = "JLCPCB",
        tier: str = "standard",
    ) -> str:
        """Load a bundled manufacturer DFM profile for subsequent checks."""
        profile = _load_profile(manufacturer, tier)
        state_path = _write_active_profile_selection(
            str(profile["manufacturer"]),
            str(profile["tier"]),
        )
        return "\n".join(
            [
                "DFM profile loaded.",
                f"- Active profile: {profile['manufacturer']} / {profile['tier']}",
                f"- State file: {state_path}",
            ]
        )

    @mcp.tool()
    @headless_compatible
    def dfm_run_manufacturer_check() -> VerdictReport:
        """Run a manufacturer-aware DFM review using the active bundled profile."""
        profile = _selected_profile()
        return _dfm_verdict_report(_dfm_check_lines(profile))

    @mcp.tool()
    @headless_compatible
    def dfm_calculate_manufacturing_cost(
        quantity: int = 10,
        manufacturer: str = "JLCPCB",
        tier: str = "standard",
    ) -> str:
        """Estimate fabrication cost from board area, layers, and via count."""
        if quantity < 1:
            raise ValueError("Quantity must be at least 1.")
        profile = _load_profile(manufacturer, tier)
        return "\n".join(_cost_lines(profile, quantity))
