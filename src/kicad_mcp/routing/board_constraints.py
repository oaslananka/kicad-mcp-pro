"""FastMCP-independent board-constraint generation service."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from ..models.tool_result import ArtifactRef, StateDelta, ToolResult
from ..utils.sexpr import _sexpr_string

DesignIntentLoader = Callable[[], Any]
RuleWriter = Callable[[str, str], Path]


class _PowerRailLike(Protocol):
    name: str
    current_max_a: float
    voltage_v: float


class _InterfaceLike(Protocol):
    kind: str
    net_prefix: str
    differential: bool
    impedance_target_ohm: float | None
    diff_skew_max_ps: float | None
    length_target_mm: float | None
    length_match_tolerance_mm: float


def _mm(value: float) -> str:
    return f"{value:.4f}mm"


def ipc_trace_width_mm(current_a: float) -> float:
    """Return the legacy simplified IPC-2221 external trace-width estimate."""
    if current_a <= 0:
        return 0.127
    raw: float = current_a / (0.048 * float(10**0.44))
    width_mm: float = raw ** (1.0 / 0.725)
    return float(max(0.127, round(width_mm, 4)))


def _safe_rule_name(value: str, fallback: str) -> str:
    return re.sub(r"\W", "_", value).strip("_") or fallback


def _generate_rail_rule(
    write_rule: RuleWriter, rail: _PowerRailLike
) -> tuple[Path | None, list[str], list[str]]:
    rail_name: str = rail.name
    current_a: float = rail.current_max_a
    voltage_v: float = rail.voltage_v
    width_mm = ipc_trace_width_mm(current_a)
    clearance_mm = max(0.5, voltage_v / 100.0 * 0.5) if voltage_v > 50 else 0.2
    via_dia = max(0.6, width_mm + 0.3)
    via_drill = max(0.3, via_dia * 0.6)
    safe_name = _safe_rule_name(rail_name, "RAIL")
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
    generated: list[str] = []
    conflicts: list[str] = []
    rules_path: Path | None = None
    try:
        rules_path = write_rule(rule_name, rule_body)
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
    return rules_path, generated, conflicts


def _generate_differential_rule(
    write_rule: RuleWriter, iface: _InterfaceLike, dp_name: str
) -> tuple[Path | None, list[str], list[str]]:
    kind = iface.kind
    net_prefix = iface.net_prefix
    imp = iface.impedance_target_ohm or 0.0
    gap_mm = round(imp / 750.0, 3)
    width_mm = round(gap_mm * 1.4, 3)
    skew_mm = (iface.diff_skew_max_ps or 10.0) * 0.06
    rule_name = f"dp_{dp_name}"
    rule_body = "\n".join(
        [
            f"(rule {_sexpr_string(rule_name)}",
            f"  (constraint track_width (opt {_mm(max(0.1, width_mm))}))",
            f"  (constraint diff_pair_gap (opt {_mm(max(0.1, gap_mm))}))",
            f"  (constraint diff_pair_max_uncoupled_length (max {_mm(max(0.5, skew_mm))}))",
            f'  (condition "A.NetClass == \\"{dp_name}\\"")',
            ")",
        ]
    )
    try:
        rules_path = write_rule(rule_name, rule_body)
        return (
            rules_path,
            [
                f"Interface '{kind}' ({net_prefix}): diff-pair "
                f"width={_mm(max(0.1, width_mm))} gap={_mm(max(0.1, gap_mm))} "
                f"skew<={_mm(max(0.5, skew_mm))}"
            ],
            [],
        )
    except (OSError, ValueError) as exc:
        return None, [], [f"Interface '{kind}': {exc}"]


def _generate_length_rule(
    write_rule: RuleWriter, iface: _InterfaceLike, dp_name: str
) -> tuple[Path | None, list[str], list[str]]:
    kind = iface.kind
    net_prefix = iface.net_prefix
    rule_name = f"len_{dp_name}"
    tol = iface.length_match_tolerance_mm
    target_mm = iface.length_target_mm or 0.0
    rule_body = "\n".join(
        [
            f"(rule {_sexpr_string(rule_name)}",
            f"  (constraint length (min {_mm(max(0, target_mm - tol))}) "
            f"(max {_mm(target_mm + tol)}))",
            f'  (condition "A.NetClass == \\"{dp_name}\\"")',
            ")",
        ]
    )
    try:
        rules_path = write_rule(rule_name, rule_body)
        return (
            rules_path,
            [f"Interface '{kind}' ({net_prefix}): length {_mm(target_mm)} ±{_mm(tol)}"],
            [],
        )
    except (OSError, ValueError) as exc:
        return None, [], [f"Interface '{kind}' length: {exc}"]


def _generate_interface_rule(
    write_rule: RuleWriter, iface: _InterfaceLike
) -> tuple[Path | None, list[str], list[str]]:
    net_prefix = iface.net_prefix
    if not net_prefix:
        return None, [], []
    dp_name = _safe_rule_name(net_prefix, "IFACE")
    if iface.differential and iface.impedance_target_ohm:
        return _generate_differential_rule(write_rule, iface, dp_name)
    if iface.length_target_mm:
        return _generate_length_rule(write_rule, iface, dp_name)
    return None, [], []


@dataclass(frozen=True)
class RoutingBoardConstraintsService:
    """Generate routing constraints from project design intent."""

    load_design_intent: DesignIntentLoader
    write_rule: RuleWriter

    def generate(self) -> ToolResult:
        intent = self.load_design_intent()
        generated: list[str] = []
        conflicts: list[str] = []
        rules_path: Path | None = None

        for rail in intent.power_rails:
            path, rail_gen, rail_conflicts = _generate_rail_rule(self.write_rule, rail)
            if path is not None:
                rules_path = path
            generated.extend(rail_gen)
            conflicts.extend(rail_conflicts)

        for iface in intent.interfaces:
            path, iface_gen, iface_conflicts = _generate_interface_rule(self.write_rule, iface)
            if path is not None:
                rules_path = path
            generated.extend(iface_gen)
            conflicts.extend(iface_conflicts)

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
