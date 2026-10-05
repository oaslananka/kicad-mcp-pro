"""Thin FastMCP adapter for interface-to-net-class binding."""

# pyright: reportUnusedFunction=false

from __future__ import annotations

from dataclasses import dataclass

from mcp.server.mcpserver import MCPServer as FastMCP

from ..signal_integrity.net_class_binding import (
    NetClassRuleWriter,
    SignalIntegrityNetClassBindingService,
)


def _write_nc_rule(
    net_class: str,
    clearance_mm: float,
    track_width_mm: float,
    diff_gap_mm: float | None,
) -> str:
    """Write one net-class rule to the project's .kicad_dru file and return the path."""
    from ..utils.sexpr import _sexpr_string
    from .routing import _mm, _write_rule

    via_d = max(0.4, clearance_mm * 2 + track_width_mm)
    via_drill = via_d * 0.55
    name = f"Net class {net_class}"
    constraints = [
        f"  (constraint track_width (min {_mm(track_width_mm)}) "
        f"(opt {_mm(track_width_mm)}) (max {_mm(track_width_mm)}))",
        f"  (constraint clearance (min {_mm(clearance_mm)}))",
        f"  (constraint via_diameter (min {_mm(via_d)}) (opt {_mm(via_d)}))",
        f"  (constraint via_drill (min {_mm(via_drill)}) (opt {_mm(via_drill)}))",
    ]
    if diff_gap_mm is not None:
        constraints.append(
            f"  (constraint diff_pair_gap (min {_mm(diff_gap_mm)}) (opt {_mm(diff_gap_mm)}))"
        )
    body = "\n".join(
        [
            f"(rule {_sexpr_string(name)}",
            f"  (condition \"A.NetClass == '{net_class}'\")",
            *constraints,
            ")",
        ]
    )
    return str(_write_rule(name, body))


@dataclass(frozen=True)
class SignalIntegrityNetClassBindingDependencies:
    service: SignalIntegrityNetClassBindingService
    rule_writer: NetClassRuleWriter


def _default_dependencies() -> SignalIntegrityNetClassBindingDependencies:
    return SignalIntegrityNetClassBindingDependencies(
        service=SignalIntegrityNetClassBindingService(),
        rule_writer=_write_nc_rule,
    )


def register(
    mcp: FastMCP,
    dependencies: SignalIntegrityNetClassBindingDependencies | None = None,
) -> None:
    """Register interface-to-net-class binding tools."""
    deps = dependencies or _default_dependencies()

    @mcp.tool()
    def si_bind_interfaces_to_net_classes(
        interfaces: list[dict[str, object]],
        dry_run: bool = True,
    ) -> str:
        """Map interface specs from the project design intent to KiCad net classes.

        For each interface with an impedance target, this tool generates the
        pcb_set_net_class() calls needed to enforce clearance and diff-pair rules.
        When ``dry_run=True`` (default), only returns the plan without executing it.

        Args:
            interfaces: List of InterfaceSpec dicts from project_get_design_spec().
            dry_run: If True, return the mapping plan without modifying the project.
                Set to False to have the tool call pcb_set_net_class() for each class.

        Returns:
            Net class plan or confirmation of changes applied.
        """
        return deps.service.bind(
            interfaces=interfaces,
            dry_run=dry_run,
            rule_writer=deps.rule_writer,
        )
