"""Thin FastMCP adapter for length-matching validation."""

# pyright: reportUnusedFunction=false

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, cast

from mcp.server.mcpserver import MCPServer as FastMCP

from ..connection import get_board
from ..models.signal_integrity import LengthMatchingInput
from ..pcb.board_access import board_tracks
from ..pcb.geometry import track_segment_length_mm
from ..signal_integrity.length_matching import SignalIntegrityLengthMatchingService

TrackLengthProvider = Callable[[], dict[str, float]]


class _TrackLike(Protocol):
    start: object
    end: object
    net: object


def _track_lengths_by_net() -> dict[str, float]:
    lengths: dict[str, float] = {}
    for track in cast(list[_TrackLike], board_tracks(get_board())):
        net_name = str(getattr(getattr(track, "net", None), "name", "") or "")
        if not net_name:
            continue
        lengths[net_name] = lengths.get(net_name, 0.0) + track_segment_length_mm(track)
    return lengths


@dataclass(frozen=True)
class SignalIntegrityLengthMatchingDependencies:
    service: SignalIntegrityLengthMatchingService
    track_length_provider: TrackLengthProvider


def _default_dependencies() -> SignalIntegrityLengthMatchingDependencies:
    return SignalIntegrityLengthMatchingDependencies(
        service=SignalIntegrityLengthMatchingService(),
        track_length_provider=_track_lengths_by_net,
    )


def register(
    mcp: FastMCP,
    dependencies: SignalIntegrityLengthMatchingDependencies | None = None,
) -> None:
    """Register length-matching validation tools."""
    deps = dependencies or _default_dependencies()

    @mcp.tool()
    def si_validate_length_matching(
        net_groups: list[list[str]],
        tolerance_mm: float = 2.0,
    ) -> str:
        """Validate that each net group is matched within the supplied tolerance."""
        payload = LengthMatchingInput(net_groups=net_groups, tolerance_mm=tolerance_mm)
        return deps.service.validate(
            net_groups=payload.net_groups,
            tolerance_mm=payload.tolerance_mm,
            lengths=deps.track_length_provider(),
        )
