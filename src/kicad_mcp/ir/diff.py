"""Semantic differ for the circuit IR.

The differ compares two ``IRCircuit`` states and reports what changed
in electrical / semantic terms — not in coordinates or UUIDs.

Example
-------
>>> from kicad_mcp.ir import parse_schematic_to_ir, circuit_diff, render_diff
>>> before = parse_schematic_to_ir("design_v1.kicad_sch")
>>> after  = parse_schematic_to_ir("design_v2.kicad_sch")
>>> for change in circuit_diff(before, after):
...     print(render_diff(change))
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from .circuit_ir import IRCircuit


class IRDiffKind(Enum):
    """Category of semantic change detected by the differ."""

    COMPONENT_ADDED = "component_added"
    COMPONENT_REMOVED = "component_removed"
    COMPONENT_CHANGED = "component_changed"
    NET_ADDED = "net_added"
    NET_REMOVED = "net_removed"
    NET_RENAMED = "net_renamed"
    CONNECTION_ADDED = "connection_added"
    CONNECTION_REMOVED = "connection_removed"
    RAIL_ADDED = "rail_added"
    RAIL_REMOVED = "rail_removed"
    RAIL_VOLTAGE_CHANGED = "rail_voltage_changed"
    INTERFACE_ADDED = "interface_added"
    INTERFACE_REMOVED = "interface_removed"
    INTERFACE_CHANGED = "interface_changed"
    PIN_ROLE_CHANGED = "pin_role_changed"


@dataclass(frozen=True)
class IRDiff:
    """A single semantic difference between two circuit IR states."""

    kind: IRDiffKind
    subject: str  # e.g. "R1", "VCC", "I2C1"
    detail: str = ""
    before: Any = None
    after: Any = None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _diff_components(before: IRCircuit, after: IRCircuit) -> list[IRDiff]:
    changes: list[IRDiff] = []
    before_refs = set(before.components)
    after_refs = set(after.components)

    for ref in sorted(after_refs - before_refs):
        comp = after.components[ref]
        changes.append(
            IRDiff(
                kind=IRDiffKind.COMPONENT_ADDED,
                subject=ref,
                detail=f"{comp.lib_id} ({comp.value})",
                after=comp,
            )
        )

    for ref in sorted(before_refs - after_refs):
        comp = before.components[ref]
        changes.append(
            IRDiff(
                kind=IRDiffKind.COMPONENT_REMOVED,
                subject=ref,
                detail=f"{comp.lib_id} ({comp.value})",
                before=comp,
            )
        )

    for ref in sorted(before_refs & after_refs):
        b = before.components[ref]
        a = after.components[ref]
        if b.lib_id != a.lib_id or b.value != a.value or b.footprint != a.footprint:
            changes.append(
                IRDiff(
                    kind=IRDiffKind.COMPONENT_CHANGED,
                    subject=ref,
                    detail=f"{b.lib_id}/{b.value} → {a.lib_id}/{a.value}",
                    before=b,
                    after=a,
                )
            )
    return changes


def _diff_nets(before: IRCircuit, after: IRCircuit) -> list[IRDiff]:
    changes: list[IRDiff] = []
    before_net_names = set(before.nets)
    after_net_names = set(after.nets)

    for name in sorted(after_net_names - before_net_names):
        changes.append(
            IRDiff(
                kind=IRDiffKind.NET_ADDED,
                subject=name,
                after=after.nets[name],
            )
        )

    for name in sorted(before_net_names - after_net_names):
        changes.append(
            IRDiff(
                kind=IRDiffKind.NET_REMOVED,
                subject=name,
                before=before.nets[name],
            )
        )

    for name in sorted(before_net_names & after_net_names):
        b_net = before.nets[name]
        a_net = after.nets[name]
        added = a_net.connections - b_net.connections
        removed = b_net.connections - a_net.connections
        for ref, pin in sorted(added):
            changes.append(
                IRDiff(
                    kind=IRDiffKind.CONNECTION_ADDED,
                    subject=name,
                    detail=f"{ref}.{pin}",
                    after=(ref, pin),
                )
            )
        for ref, pin in sorted(removed):
            changes.append(
                IRDiff(
                    kind=IRDiffKind.CONNECTION_REMOVED,
                    subject=name,
                    detail=f"{ref}.{pin}",
                    before=(ref, pin),
                )
            )
    return changes


def _diff_power_rails(before: IRCircuit, after: IRCircuit) -> list[IRDiff]:
    changes: list[IRDiff] = []
    before_rails = set(before.power_rails)
    after_rails = set(after.power_rails)

    for name in sorted(after_rails - before_rails):
        changes.append(
            IRDiff(
                kind=IRDiffKind.RAIL_ADDED,
                subject=name,
                after=after.power_rails[name],
            )
        )

    for name in sorted(before_rails - after_rails):
        changes.append(
            IRDiff(
                kind=IRDiffKind.RAIL_REMOVED,
                subject=name,
                before=before.power_rails[name],
            )
        )

    for name in sorted(before_rails & after_rails):
        b_rail = before.power_rails[name]
        a_rail = after.power_rails[name]
        if b_rail.voltage != a_rail.voltage:
            changes.append(
                IRDiff(
                    kind=IRDiffKind.RAIL_VOLTAGE_CHANGED,
                    subject=name,
                    detail=f"{b_rail.voltage}V → {a_rail.voltage}V",
                    before=b_rail,
                    after=a_rail,
                )
            )
    return changes


def _diff_interfaces(before: IRCircuit, after: IRCircuit) -> list[IRDiff]:
    changes: list[IRDiff] = []
    before_ifaces = set(before.interfaces)
    after_ifaces = set(after.interfaces)

    for name in sorted(after_ifaces - before_ifaces):
        changes.append(
            IRDiff(
                kind=IRDiffKind.INTERFACE_ADDED,
                subject=name,
                after=after.interfaces[name],
            )
        )

    for name in sorted(before_ifaces - after_ifaces):
        changes.append(
            IRDiff(
                kind=IRDiffKind.INTERFACE_REMOVED,
                subject=name,
                before=before.interfaces[name],
            )
        )

    for name in sorted(before_ifaces & after_ifaces):
        b_iface = before.interfaces[name]
        a_iface = after.interfaces[name]
        if b_iface.net_roles != a_iface.net_roles or b_iface.kind != a_iface.kind:
            changes.append(
                IRDiff(
                    kind=IRDiffKind.INTERFACE_CHANGED,
                    subject=name,
                    detail=f"{b_iface.kind}: roles changed",
                    before=b_iface,
                    after=a_iface,
                )
            )
    return changes


def circuit_diff(before: IRCircuit, after: IRCircuit) -> list[IRDiff]:
    """Compare two ``IRCircuit`` states and return the list of changes."""
    return [
        *_diff_components(before, after),
        *_diff_nets(before, after),
        *_diff_power_rails(before, after),
        *_diff_interfaces(before, after),
    ]


def render_diff(diff: IRDiff) -> str:
    """Render a single ``IRDiff`` as a human-readable string."""
    symbol = {
        IRDiffKind.COMPONENT_ADDED: "+",
        IRDiffKind.COMPONENT_REMOVED: "-",
        IRDiffKind.COMPONENT_CHANGED: "~",
        IRDiffKind.NET_ADDED: "+",
        IRDiffKind.NET_REMOVED: "-",
        IRDiffKind.NET_RENAMED: "~",
        IRDiffKind.CONNECTION_ADDED: "+",
        IRDiffKind.CONNECTION_REMOVED: "-",
        IRDiffKind.RAIL_ADDED: "+",
        IRDiffKind.RAIL_REMOVED: "-",
        IRDiffKind.RAIL_VOLTAGE_CHANGED: "~",
        IRDiffKind.INTERFACE_ADDED: "+",
        IRDiffKind.INTERFACE_REMOVED: "-",
        IRDiffKind.INTERFACE_CHANGED: "~",
        IRDiffKind.PIN_ROLE_CHANGED: "~",
    }.get(diff.kind, "?")

    kind_label = diff.kind.value.replace("_", " ")
    detail = f" — {diff.detail}" if diff.detail else ""
    return f"  {symbol} {kind_label}: {diff.subject}{detail}"


def render_diff_summary(changes: list[IRDiff]) -> str:
    """Render a full diff summary."""
    lines = [f"Semantic IR diff: {len(changes)} change(s)"]
    for change in changes:
        lines.append(render_diff(change))
    return "\n".join(lines)
