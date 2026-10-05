"""FastMCP-independent net-class routing-rule service."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ..utils.sexpr import _sexpr_string

RuleWriter = Callable[[str, str], Path]


def _mm(value: float) -> str:
    return f"{value:.4f}mm"


def _expression_string(value: str) -> str:
    """Quote a string for KiCad's rule-expression language."""
    escaped = value.replace("\\", "\\\\").replace("'", "\\'")
    return f"'{escaped}'"


def build_net_class_rule(
    net_class: str,
    width_mm: float,
    clearance_mm: float,
    via_diameter_mm: float,
    via_drill_mm: float,
) -> tuple[str, str]:
    """Build the legacy net-class .kicad_dru rule body."""
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
    condition = f"A.NetClass == {_expression_string(net_class)}"
    body = "\n".join(
        [
            f"(rule {_sexpr_string(name)}",
            f"  (condition {_sexpr_string(condition)})",
            track_width_constraint,
            f"  (constraint clearance (min {_mm(clearance_mm)}))",
            via_diameter_constraint,
            via_drill_constraint,
            ")",
        ]
    )
    return name, body


@dataclass(frozen=True)
class RoutingNetClassRuleService:
    """Write net-class routing constraints without depending on FastMCP."""

    write_rule: RuleWriter

    def set_rules(
        self,
        net_class: str,
        width_mm: float,
        clearance_mm: float,
        via_diameter_mm: float,
        via_drill_mm: float,
    ) -> str:
        rule_name, rule_body = build_net_class_rule(
            net_class,
            width_mm,
            clearance_mm,
            via_diameter_mm,
            via_drill_mm,
        )
        try:
            path = self.write_rule(rule_name, rule_body)
        except (OSError, ValueError) as exc:
            return f"Net-class rule update failed: {exc}"
        return (
            f"Net-class routing rule '{rule_name}' written to {path}.\n"
            f"Track width: {_mm(width_mm)}, clearance: {_mm(clearance_mm)}, "
            f"via: {_mm(via_diameter_mm)} / drill {_mm(via_drill_mm)}."
        )
