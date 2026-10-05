"""Thin FastMCP adapter for differential-pair skew analysis."""

# pyright: reportUnusedFunction=false

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, cast

from mcp.server.mcpserver import MCPServer as FastMCP

from ..connection import get_board
from ..models.signal_integrity import DifferentialPairSkewInput
from ..models.verdict import VerdictReport
from ..pcb.board_access import board_tracks
from ..pcb.geometry import track_segment_length_mm
from ..signal_integrity.differential_pair_skew import (
    DielectricHeightProvider,
    SignalIntegrityDifferentialPairSkewService,
    SkewBudgetResolver,
    TrackWidthProvider,
)
from ..utils.units import nm_to_mm
from .design_intent_state import resolve_design_intent

TrackLengthProvider = Callable[[], dict[str, float]]

_DEFAULT_OUTER_DIELECTRIC_MM = 0.18
_DEFAULT_DIFF_SKEW_BUDGET_PS = 10.0


class _TrackLike(Protocol):
    start: object
    end: object
    width: int
    net: object


def _track_lengths_by_net() -> dict[str, float]:
    lengths: dict[str, float] = {}
    for track in cast(list[_TrackLike], board_tracks(get_board())):
        net_name = str(getattr(getattr(track, "net", None), "name", "") or "")
        if not net_name:
            continue
        lengths[net_name] = lengths.get(net_name, 0.0) + track_segment_length_mm(track)
    return lengths


def _track_width_mm(net_name: str) -> float | None:
    widths: list[float] = []
    for track in cast(list[_TrackLike], board_tracks(get_board())):
        track_net = str(getattr(getattr(track, "net", None), "name", "") or "")
        if track_net == net_name:
            widths.append(nm_to_mm(int(getattr(track, "width", 0))))
    if not widths:
        return None
    return sum(widths) / len(widths)


def _stackup_layers() -> list[object]:
    stackup = get_board().get_stackup()
    return list(getattr(stackup, "layers", []))


def _is_copper_layer(layer: object) -> bool:
    material = str(getattr(layer, "material_name", "") or "").casefold()
    if material == "copper":
        return True
    layer_name = str(getattr(layer, "layer", ""))
    return "Cu" in layer_name


def _outer_dielectric_height_mm() -> float:
    layers = _stackup_layers()
    seen_outer_copper = False
    for layer in layers:
        if _is_copper_layer(layer) and not seen_outer_copper:
            seen_outer_copper = True
            continue
        if seen_outer_copper and not _is_copper_layer(layer):
            thickness_nm = int(getattr(layer, "thickness", 0))
            if thickness_nm > 0:
                return nm_to_mm(thickness_nm)
    return _DEFAULT_OUTER_DIELECTRIC_MM


def _resolve_skew_budget_ps(net_p: str, net_n: str) -> tuple[float, str]:
    """Return the effective skew budget and its source."""
    resolution = resolve_design_intent()
    interfaces = getattr(resolution.resolved, "interfaces", []) or []
    matched: list[float] = []
    declared: list[float] = []
    for iface in interfaces:
        budget = getattr(iface, "diff_skew_max_ps", None)
        if not budget or budget <= 0:
            continue
        declared.append(budget)
        prefix = (getattr(iface, "net_prefix", "") or "").strip()
        if prefix and (net_p.startswith(prefix) or net_n.startswith(prefix)):
            matched.append(budget)
    if matched:
        value = min(matched)
        return value, f"design-intent interface budget {value:.1f} ps"
    if declared:
        value = min(declared)
        return value, f"tightest design-intent budget {value:.1f} ps (no net-prefix match)"
    return _DEFAULT_DIFF_SKEW_BUDGET_PS, (
        f"conservative default {_DEFAULT_DIFF_SKEW_BUDGET_PS:.1f} ps — no design intent; "
        "set diff_skew_max_ps via project_set_design_intent"
    )


@dataclass(frozen=True)
class SignalIntegrityDifferentialPairSkewDependencies:
    service: SignalIntegrityDifferentialPairSkewService
    track_length_provider: TrackLengthProvider
    track_width_provider: TrackWidthProvider
    dielectric_height_provider: DielectricHeightProvider
    budget_resolver: SkewBudgetResolver


def _default_dependencies() -> SignalIntegrityDifferentialPairSkewDependencies:
    return SignalIntegrityDifferentialPairSkewDependencies(
        service=SignalIntegrityDifferentialPairSkewService(),
        track_length_provider=lambda: _track_lengths_by_net(),
        track_width_provider=lambda net_name: _track_width_mm(net_name),
        dielectric_height_provider=lambda: _outer_dielectric_height_mm(),
        budget_resolver=lambda net_p, net_n: _resolve_skew_budget_ps(net_p, net_n),
    )


def register(
    mcp: FastMCP,
    dependencies: SignalIntegrityDifferentialPairSkewDependencies | None = None,
) -> None:
    """Register differential-pair skew analysis tools."""
    deps = dependencies or _default_dependencies()

    @mcp.tool()
    def si_check_differential_pair_skew(
        net_p: str,
        net_n: str,
        er: float = 4.2,
        trace_type: str = "microstrip",
        skew_budget_ps: float = 0.0,
    ) -> VerdictReport:
        """Estimate differential-pair length skew and delay mismatch from board tracks.

        Returns a PASS/WARN/FAIL verdict. The skew budget comes from ``skew_budget_ps``
        if > 0, otherwise from the matching design-intent interface, otherwise a
        conservative default. PASS within budget, WARN up to 2x budget, FAIL beyond.
        """
        payload = DifferentialPairSkewInput(
            net_p=net_p,
            net_n=net_n,
            er=er,
            trace_type=trace_type,
        )
        return deps.service.analyze(
            payload=payload,
            lengths=deps.track_length_provider(),
            skew_budget_ps=skew_budget_ps,
            track_width_provider=deps.track_width_provider,
            dielectric_height_provider=deps.dielectric_height_provider,
            budget_resolver=deps.budget_resolver,
        )
