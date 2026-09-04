"""IR-invariant lint rules.

Lint rules check for electrical / semantic issues in the IR that are
independent of any particular design rule: floating rails, unused
interfaces, missing pin roles, domain crossings, etc.

These complement (and feed into) the existing
:mod:`kicad_mcp.utils.schematic_rules` module which operates at the
geometry/net-view level.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .circuit_ir import IRCircuit


class IRLintSeverity(Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass(frozen=True)
class IRLintFinding:
    """A single lint finding against the IR."""

    rule_id: str
    severity: IRLintSeverity
    message: str
    subject: str = ""  # e.g. "VCC", "I2C1", "R1"
    detail: str = ""


# ---------------------------------------------------------------------------
# Built-in lint rules
# ---------------------------------------------------------------------------

_LINT_RULES: list[tuple[str, str, str, str]] = [
    # (rule_id, severity_label, description, subject_field)
    ("ir-001", "warning", "Floating power rail: no components connected", "rail"),
    ("ir-002", "warning", "Unused interface: no nets routed", "interface"),
    ("ir-003", "info", "Single-net interface: may be incomplete", "interface"),
    ("ir-004", "warning", "Power rail without known voltage", "rail"),
    ("ir-005", "warning", "Net without any pin connections (dangling)", "net"),
    ("ir-006", "info", "Component without pin definitions", "component"),
    ("ir-007", "warning", "Rail with nets at different voltages", "rail"),
    ("ir-008", "info", "Large rail (>10 nets); verify domain assignment", "rail"),
]


def lint_circuit(ir: IRCircuit) -> list[IRLintFinding]:
    """Run all built-in lint rules on an IR circuit.

    Returns a sorted (by severity then rule_id) list of findings.
    """
    findings: list[IRLintFinding] = []
    _lint_floating_rails(ir, findings)
    _lint_unused_interfaces(ir, findings)
    _lint_single_net_interfaces(ir, findings)
    _lint_unknown_voltage_rails(ir, findings)
    _lint_dangling_nets(ir, findings)
    _lint_component_no_pins(ir, findings)
    _lint_voltage_conflicts(ir, findings)
    _lint_large_rails(ir, findings)

    findings.sort(key=lambda f: (_severity_order(f.severity), f.rule_id, f.subject))
    return findings


# ---------------------------------------------------------------------------
# Rule implementations
# ---------------------------------------------------------------------------


def _severity_order(s: IRLintSeverity) -> int:
    return {"error": 0, "warning": 1, "info": 2}.get(s.value, 99)


def _lint_floating_rails(ir: IRCircuit, findings: list[IRLintFinding]) -> None:
    """ir-001: Rails with no component connections beyond the rail itself."""
    for name, rail in ir.power_rails.items():
        connected_components: set[str] = set()
        for net_name in rail.net_names:
            net = ir.nets.get(net_name)
            if net is not None:
                for ref, _ in net.connections:
                    connected_components.add(ref)
        if not connected_components:
            findings.append(
                IRLintFinding(
                    rule_id="ir-001",
                    severity=IRLintSeverity.WARNING,
                    subject=name,
                    message="Floating power rail: no components connected",
                    detail=f"rail net(s): {', '.join(sorted(rail.net_names))}",
                )
            )


def _lint_unused_interfaces(ir: IRCircuit, findings: list[IRLintFinding]) -> None:
    """ir-002: Interfaces with no net roles defined."""
    for name, iface in ir.interfaces.items():
        if not iface.net_roles:
            findings.append(
                IRLintFinding(
                    rule_id="ir-002",
                    severity=IRLintSeverity.WARNING,
                    subject=name,
                    message="Unused interface: no nets routed",
                )
            )


def _lint_single_net_interfaces(ir: IRCircuit, findings: list[IRLintFinding]) -> None:
    """ir-003: Interfaces with only one net (likely incomplete)."""
    for name, iface in ir.interfaces.items():
        if len(iface.net_roles) == 1:
            findings.append(
                IRLintFinding(
                    rule_id="ir-003",
                    severity=IRLintSeverity.INFO,
                    subject=name,
                    message="Single-net interface: may be incomplete",
                    detail=f"only {next(iter(iface.net_roles.keys()))} mapped",
                )
            )


def _lint_unknown_voltage_rails(ir: IRCircuit, findings: list[IRLintFinding]) -> None:
    """ir-004: Rails without a known voltage (still at default 0.0)."""
    for name, rail in ir.power_rails.items():
        if not rail.voltage and name.upper() not in ("GND", "AGND", "DGND", "VSS"):
            findings.append(
                IRLintFinding(
                    rule_id="ir-004",
                    severity=IRLintSeverity.WARNING,
                    subject=name,
                    message="Power rail without known voltage",
                    detail=f"voltage={rail.voltage}V; specify via rail annotation",
                )
            )


def _lint_dangling_nets(ir: IRCircuit, findings: list[IRLintFinding]) -> None:
    """ir-005: Nets with no pin connections."""
    for name, net in ir.nets.items():
        if not net.connections:
            findings.append(
                IRLintFinding(
                    rule_id="ir-005",
                    severity=IRLintSeverity.WARNING,
                    subject=name,
                    message="Net without any pin connections (dangling)",
                )
            )


def _lint_component_no_pins(ir: IRCircuit, findings: list[IRLintFinding]) -> None:
    """ir-006: Components without any pin definitions in the IR."""
    for ref, comp in ir.components.items():
        if not comp.pins:
            findings.append(
                IRLintFinding(
                    rule_id="ir-006",
                    severity=IRLintSeverity.INFO,
                    subject=ref,
                    message="Component without pin definitions",
                    detail=f"library symbol not resolved for {comp.lib_id}",
                )
            )


def _lint_voltage_conflicts(ir: IRCircuit, findings: list[IRLintFinding]) -> None:
    """ir-007: A rail has nets at different voltages (conflict)."""
    for name, rail in ir.power_rails.items():
        if len(rail.net_names) > 1:
            voltages: set[float] = set()
            for net_name in rail.net_names:
                net = ir.nets.get(net_name)
                if net is not None and net.voltage is not None:
                    voltages.add(net.voltage)
            if len(voltages) > 1:
                findings.append(
                    IRLintFinding(
                        rule_id="ir-007",
                        severity=IRLintSeverity.WARNING,
                        subject=name,
                        message="Rail with nets at different voltages",
                        detail=f"voltages: {sorted(voltages)}",
                    )
                )


def _lint_large_rails(ir: IRCircuit, findings: list[IRLintFinding]) -> None:
    """ir-008: Rails with >10 nets; suggest checking domain assignment."""
    for name, rail in ir.power_rails.items():
        if len(rail.net_names) > 10:
            findings.append(
                IRLintFinding(
                    rule_id="ir-008",
                    severity=IRLintSeverity.INFO,
                    subject=name,
                    message="Large rail (>10 nets); verify domain assignment",
                    detail=f"{len(rail.net_names)} nets grouped under {name}",
                )
            )
