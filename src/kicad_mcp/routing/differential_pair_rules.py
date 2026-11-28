"""FastMCP-independent differential-pair routing-rule service."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ..utils.sexpr import _sexpr_string

NetNamesProvider = Callable[[], set[str]]
RuleWriter = Callable[[str, str], Path]


def _mm(value: float) -> str:
    return f"{value:.4f}mm"


def infer_diff_pair_base(net_p: str, net_n: str) -> str | None:
    """Match KiCad's native polarity suffix, including trailing digits/underscores."""
    match = re.fullmatch(r"(.+)([P+])([0-9_]*)", net_p)
    if match is None:
        return None
    base, polarity, suffix = match.groups()
    complement = "N" if polarity == "P" else "-"
    return base if net_n == f"{base}{complement}{suffix}" else None


PAIR_NAME_GUIDANCE = (
    "Differential pair requires matching positive/negative net names recognized by KiCad. "
    "Use matching P/N or +/- suffixes (including matching trailing digits); "
    "rename unsupported nets in the schematic and update the PCB before retrying."
)


def _literal_pair_name(name: str) -> bool:
    """Allow plain rule literals only; KiCad equality interprets wildcard patterns."""
    return name.isprintable() and not any(char in name for char in "*?[]\\\"'")


def build_differential_pair_rule(
    net_p: str,
    net_n: str,
    width_mm: float,
    gap_mm: float,
    length_tolerance_mm: float,
) -> tuple[str, str]:
    """Build a native rule for two names, after checking board ambiguity in the service."""
    if infer_diff_pair_base(net_p, net_n) is None or not all(
        _literal_pair_name(name) for name in (net_p, net_n)
    ):
        raise ValueError(PAIR_NAME_GUIDANCE)
    condition = f"A.NetName == '{net_p}' || A.NetName == '{net_n}'"
    track_width_constraint = (
        f"  (constraint track_width (min {_mm(width_mm)}) "
        f"(opt {_mm(width_mm)}) (max {_mm(width_mm)}))"
    )
    gap_constraint = (
        f"  (constraint diff_pair_gap (min {_mm(gap_mm)}) (opt {_mm(gap_mm)}) (max {_mm(gap_mm)}))"
    )
    name = f"Differential pair {net_p} {net_n}"
    body = "\n".join(
        [
            f"(rule {_sexpr_string(name)}",
            f'  (condition "{condition}")',
            track_width_constraint,
            gap_constraint,
            f"  (constraint skew (max {_mm(length_tolerance_mm)}))",
            ")",
        ]
    )
    return name, body


def _ambiguous_pair_names(board_nets: set[str], net_p: str, net_n: str) -> bool:
    """KiCad DRC string matching is case-insensitive; refuse colliding board nets."""
    pair = {net_p, net_n}
    folded = {name.casefold() for name in pair}
    return any(name.casefold() in folded for name in board_nets - pair)


@dataclass(frozen=True)
class RoutingDifferentialPairService:
    """Write differential-pair constraints without depending on FastMCP."""

    list_board_net_names: NetNamesProvider
    write_rule: RuleWriter

    def set_pair(
        self,
        net_p: str,
        net_n: str,
        layer: str = "F_Cu",
        width_mm: float = 0.2,
        gap_mm: float = 0.2,
        length_tolerance_mm: float = 0.1,
    ) -> str:
        board_nets = self.list_board_net_names()
        missing = [name for name in (net_p, net_n) if name not in board_nets]
        if missing:
            return (
                "Differential-pair routing rule was not written. "
                f"Missing nets: {', '.join(missing)}"
            )
        if _ambiguous_pair_names(board_nets, net_p, net_n):
            return (
                "Differential-pair routing rule was not written. KiCad rule matching is "
                "case-insensitive and other board net names collide with this pair. "
                "Rename ambiguous nets in the schematic and update the PCB before retrying."
            )
        try:
            rule_name, rule_body = build_differential_pair_rule(
                net_p, net_n, width_mm, gap_mm, length_tolerance_mm
            )
        except ValueError as exc:
            return f"Differential-pair routing rule was not written. {exc}"
        try:
            path = self.write_rule(rule_name, rule_body)
        except (OSError, ValueError) as exc:
            return f"Differential-pair rule update failed: {exc}"
        return (
            f"Differential-pair routing rule '{rule_name}' written to {path}.\n"
            f"Layer intent: {layer}, width: {_mm(width_mm)}, gap: {_mm(gap_mm)}, "
            f"max skew: {_mm(length_tolerance_mm)}."
        )
