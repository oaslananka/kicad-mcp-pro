"""FastMCP-independent semantic circuit IR summary services."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class SeverityLike(Protocol):
    value: str


class FindingLike(Protocol):
    severity: SeverityLike
    rule_id: str
    subject: str
    message: str
    detail: str


class ComponentLike(Protocol):
    lib_id: str
    value: str
    footprint: str
    pins: Sequence[object]
    dnp: bool
    in_bom: bool


class NetLike(Protocol):
    connections: Iterable[tuple[str, str]]
    is_power: bool
    voltage: float | None


class PowerRailLike(Protocol):
    voltage: float
    net_names: Iterable[str]
    source_ref: str | None
    source_pin: str | None


class InterfaceLike(Protocol):
    kind: str
    net_roles: Mapping[str, str]
    refs: Iterable[str]


class CircuitLike(Protocol):
    source_path: str | None
    source_uuid: str | None
    title: str
    components: Mapping[str, ComponentLike]
    nets: Mapping[str, NetLike]
    power_rails: Mapping[str, PowerRailLike]
    interfaces: Mapping[str, InterfaceLike]

    def component_count(self) -> int: ...

    def pin_count(self) -> int: ...

    def net_count(self) -> int: ...

    def interface_count(self) -> int: ...


@dataclass(frozen=True)
class SchematicSemanticIRService:
    """Parse and render a semantic circuit IR summary."""

    active_schematic_file: Callable[[], Path]
    parse_circuit: Callable[[Path], CircuitLike]
    lint_circuit: Callable[[CircuitLike], Iterable[FindingLike]]
    with_diagnostics: Callable[[str, Path], str]
    warn_parse_failure: Callable[[Exception], None]

    def get_summary(self) -> str:
        schematic_file = self.active_schematic_file()
        try:
            circuit = self.parse_circuit(schematic_file)
        except Exception as exc:
            self.warn_parse_failure(exc)
            return self.with_diagnostics(f"Could not parse IR: {exc}", schematic_file)

        lines = [
            f"# Semantic Circuit IR — {circuit.title}",
            f"Source: {circuit.source_path}",
            f"UUID: {circuit.source_uuid or 'N/A'}",
            "",
            f"**Summary:** {circuit.component_count()} components, "
            f"{circuit.pin_count()} pins, "
            f"{circuit.net_count()} nets, "
            f"{len(circuit.power_rails)} rails, "
            f"{circuit.interface_count()} interfaces",
        ]

        if circuit.components:
            lines += ["", f"## Components ({circuit.component_count()})"]
            for reference in sorted(circuit.components):
                component = circuit.components[reference]
                flags = ""
                if component.dnp:
                    flags += " [DNP]"
                if not component.in_bom:
                    flags += " [NoBOM]"
                lines.append(
                    f"- {reference}: {component.lib_id} = {component.value} "
                    f"({component.footprint}){flags}  ({len(component.pins)} pins)"
                )

        if circuit.nets:
            power_nets = sum(1 for net in circuit.nets.values() if net.is_power)
            signal_nets = circuit.net_count() - power_nets
            lines += [
                "",
                f"## Nets ({circuit.net_count()} total: {signal_nets} signal, {power_nets} power)",
            ]
            for name in sorted(circuit.nets):
                net = circuit.nets[name]
                pin_count = len(tuple(net.connections))
                power_tag = " [POWER]" if net.is_power else ""
                voltage_tag = f" {net.voltage}V" if net.voltage is not None else ""
                lines.append(f"- `{name}`{power_tag}{voltage_tag} ({pin_count} connections)")

        if circuit.power_rails:
            lines += ["", f"## Power Rails ({len(circuit.power_rails)})"]
            for name in sorted(circuit.power_rails):
                rail = circuit.power_rails[name]
                net_names = sorted(rail.net_names)
                nets_text = ", ".join(net_names[:5])
                if len(net_names) > 5:
                    nets_text += f" … (+{len(net_names) - 5} more)"
                source = f" from {rail.source_ref}.{rail.source_pin}" if rail.source_ref else ""
                lines.append(f"- {name}: {rail.voltage}V{source}  nets=[{nets_text}]")

        if circuit.interfaces:
            lines += ["", f"## Interfaces ({circuit.interface_count()})"]
            for name in sorted(circuit.interfaces):
                interface = circuit.interfaces[name]
                refs = ", ".join(sorted(interface.refs)[:3])
                roles = ", ".join(
                    f"{role}={net_name}" for role, net_name in interface.net_roles.items()
                )
                lines.append(f"- {name} ({interface.kind}): [{roles}]  refs=[{refs}]")

        findings = list(self.lint_circuit(circuit))
        if findings:
            lines += ["", f"## IR Lint Findings ({len(findings)})"]
            for finding in findings:
                subject_tag = f" ({finding.subject})" if finding.subject else ""
                detail_tag = f" — {finding.detail}" if finding.detail else ""
                lines.append(
                    f"- [{finding.severity.value.upper()}] {finding.rule_id}"
                    f"{subject_tag}: {finding.message}{detail_tag}"
                )

        return "\n".join(lines)
