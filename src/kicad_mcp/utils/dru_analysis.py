"""Conflict / sanity analysis for KiCad ``.kicad_dru`` rule trees (issue #202).

Constraint generation can emit a custom ``.kicad_dru`` from many sources (net
classes, interface binders, manufacturer profiles). Once several writers touch
one file it is easy to end up with rules that silently fight: a duplicated rule
name (KiCad keeps only the last), two scoped rules setting different minimums for
the same constraint and condition, or a structurally impossible bound. This pure
module reads the parsed rule tree (see :mod:`kicad_mcp.utils.dru`) and reports
those issues so the constraint set can be reconciled to one truth.

It has no KiCad dependency and is fully unit-testable.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field

from .dru import SExprNode, iter_rule_nodes, rule_name

# Constraints whose value is a physical dimension and must never be negative.
_DIMENSIONAL_CONSTRAINTS = frozenset(
    {
        "clearance",
        "track_width",
        "via_diameter",
        "hole_to_hole",
        "hole_size",
        "annular_width",
        "edge_clearance",
        "silk_clearance",
        "courtyard_clearance",
        "physical_clearance",
        "physical_hole_clearance",
    }
)

_UNIT_TO_MM = {
    "": 1.0,
    "mm": 1.0,
    "cm": 10.0,
    "um": 0.001,
    "nm": 1e-6,
    "mil": 0.0254,
    "in": 25.4,
}
_DIMENSION_RE = re.compile(
    r"^([-+]?(?:\d+(?:\.\d+)?|\.\d+))\s*+(mm|cm|um|nm|mil|in)?$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class RuleConflict:
    """A single design-rule conflict or sanity issue."""

    kind: str  # duplicate_name | contradictory_constraint | inverted_bounds | negative_dimension
    severity: str  # "error" | "warning"
    message: str
    rules: tuple[str, ...] = field(default_factory=tuple)

    def sort_key(self) -> tuple[int, str, str]:
        return (0 if self.severity == "error" else 1, self.kind, self.message)


def parse_dimension_mm(value: str) -> float | None:
    """Parse a KiCad dimension atom (``0.2mm``, ``5mil``, ``0.01in``) to millimetres."""
    match = _DIMENSION_RE.match(value.strip())
    if match is None:
        return None
    number = float(match.group(1))
    unit = (match.group(2) or "").lower()
    return number * _UNIT_TO_MM[unit]


def _normalize_condition(condition: str) -> str:
    return re.sub(r"\s+", " ", condition.replace('"', "'")).strip()


def _rule_condition(rule: SExprNode) -> str:
    for child in rule[2:]:
        if (
            isinstance(child, list)
            and len(child) > 1
            and child[0] == "condition"
            and not isinstance(child[1], list)
        ):
            return _normalize_condition(child[1])
    return ""  # no condition → applies to everything


def _rule_constraints(rule: SExprNode) -> list[tuple[str, dict[str, float | None]]]:
    constraints: list[tuple[str, dict[str, float | None]]] = []
    for child in rule[2:]:
        if not (
            isinstance(child, list)
            and len(child) >= 2
            and child[0] == "constraint"
            and not isinstance(child[1], list)
        ):
            continue
        ctype = child[1]
        bounds: dict[str, float | None] = {}
        for sub in child[2:]:
            if (
                isinstance(sub, list)
                and len(sub) >= 2
                and sub[0] in {"min", "max", "opt"}
                and not isinstance(sub[1], list)
            ):
                bounds[sub[0]] = parse_dimension_mm(sub[1])
        constraints.append((ctype, bounds))
    return constraints


def _check_duplicate_rule_names(rules: list[SExprNode]) -> list[RuleConflict]:
    name_counts: dict[str, int] = defaultdict(int)
    for rule in rules:
        try:
            name_counts[rule_name(rule)] += 1
        except ValueError:
            continue
    conflicts: list[RuleConflict] = []
    for name, count in name_counts.items():
        if count > 1:
            conflicts.append(
                RuleConflict(
                    kind="duplicate_name",
                    severity="error",
                    message=(
                        f"Rule name '{name}' is defined {count} times; KiCad keeps only the "
                        "last, so the earlier definitions are silently ignored."
                    ),
                    rules=(name,),
                )
            )
    return conflicts


def _validate_single_constraint(
    name: str,
    ctype: str,
    bounds: dict[str, float | None],
) -> list[RuleConflict]:
    conflicts: list[RuleConflict] = []
    minimum, maximum = bounds.get("min"), bounds.get("max")
    if minimum is not None and maximum is not None and minimum > maximum:
        conflicts.append(
            RuleConflict(
                kind="inverted_bounds",
                severity="error",
                message=(
                    f"Rule '{name}' constraint '{ctype}' has min ({minimum:g}mm) greater "
                    f"than max ({maximum:g}mm); no value can satisfy it."
                ),
                rules=(name,),
            )
        )
    if ctype in _DIMENSIONAL_CONSTRAINTS:
        for key in ("min", "max", "opt"):
            value = bounds.get(key)
            if value is not None and value < 0:
                conflicts.append(
                    RuleConflict(
                        kind="negative_dimension",
                        severity="error",
                        message=(
                            f"Rule '{name}' constraint '{ctype}' has a negative {key} "
                            f"({value:g}mm)."
                        ),
                        rules=(name,),
                    )
                )
    return conflicts


def _check_rule_constraint_bounds(
    rules: list[SExprNode],
) -> tuple[list[RuleConflict], dict[tuple[str, str], list[tuple[str, float]]]]:
    conflicts: list[RuleConflict] = []
    scoped: dict[tuple[str, str], list[tuple[str, float]]] = defaultdict(list)
    for rule in rules:
        try:
            name = rule_name(rule)
        except ValueError:
            continue
        condition = _rule_condition(rule)
        for ctype, bounds in _rule_constraints(rule):
            conflicts.extend(_validate_single_constraint(name, ctype, bounds))
            minimum = bounds.get("min")
            if condition and minimum is not None:
                scoped[(ctype, condition)].append((name, round(minimum, 6)))
    return conflicts, scoped


def _check_contradictory_constraints(
    scoped: dict[tuple[str, str], list[tuple[str, float]]],
) -> list[RuleConflict]:
    conflicts: list[RuleConflict] = []
    for (ctype, condition), entries in scoped.items():
        by_value: dict[float, set[str]] = defaultdict(set)
        for name, minimum in entries:
            by_value[minimum].add(name)
        if len(by_value) > 1:
            described = ", ".join(
                f"{value:g}mm ({', '.join(sorted(names))})"
                for value, names in sorted(by_value.items())
            )
            involved = tuple(sorted({name for names in by_value.values() for name in names}))
            conflicts.append(
                RuleConflict(
                    kind="contradictory_constraint",
                    severity="warning",
                    message=(
                        f"Constraint '{ctype}' for condition \"{condition}\" has conflicting min "
                        f"values: {described}. KiCad applies the most restrictive; consolidate "
                        "these into one rule."
                    ),
                    rules=involved,
                )
            )
    return conflicts


def analyze_rule_conflicts(root: SExprNode) -> list[RuleConflict]:
    """Return every conflict / sanity issue in a parsed ``(rules ...)`` tree."""
    rules = iter_rule_nodes(root)
    conflicts = _check_duplicate_rule_names(rules)
    bound_conflicts, scoped = _check_rule_constraint_bounds(rules)
    conflicts.extend(bound_conflicts)
    conflicts.extend(_check_contradictory_constraints(scoped))
    conflicts.sort(key=RuleConflict.sort_key)
    return conflicts
