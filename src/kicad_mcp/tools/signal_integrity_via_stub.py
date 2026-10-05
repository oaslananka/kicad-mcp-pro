"""Thin FastMCP adapter for via-stub resonance analysis."""

# pyright: reportUnusedFunction=false

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Annotated, Protocol, cast

from kipy.proto.board.board_types_pb2 import ViaType
from mcp.server.mcpserver import MCPServer as FastMCP
from pydantic import Field

from ..config import get_config
from ..connection import get_board
from ..models.signal_integrity import ViaStubInput
from ..pcb.board_access import board_vias
from ..pcb.geometry import point_xy_mm
from ..signal_integrity.via_stub import SignalIntegrityViaStubService, ViaStubObservation
from ..utils.units import nm_to_mm

_ViaPosition = Annotated[list[float], Field(min_length=2, max_length=2)]
_DEFAULT_BOARD_THICKNESS_MM = 1.6


class _ViaLike(Protocol):
    position: object
    drill_diameter: int
    net: object
    type: int


def _stackup_layers() -> list[object]:
    stackup = get_board().get_stackup()
    return list(getattr(stackup, "layers", []))


def _board_thickness_mm() -> float:
    thickness_nm = 0
    for layer in _stackup_layers():
        thickness_nm += int(getattr(layer, "thickness", 0))
    if thickness_nm <= 0:
        return _DEFAULT_BOARD_THICKNESS_MM
    return nm_to_mm(thickness_nm)


def _via_position_mm(via: _ViaLike) -> tuple[float, float]:
    return point_xy_mm(via.position)


def _selected_vias(via_positions: list[tuple[float, float]]) -> list[_ViaLike]:
    vias: list[_ViaLike] = cast(list[_ViaLike], board_vias(get_board()))
    if not via_positions:
        return list(vias)

    selected: list[_ViaLike] = []
    for via in vias:
        x_mm, y_mm = _via_position_mm(via)
        for target_x_mm, target_y_mm in via_positions:
            if math.hypot(x_mm - target_x_mm, y_mm - target_y_mm) <= 0.5:
                selected.append(via)
                break
    return selected


def _via_stub_length_mm(via: _ViaLike) -> float:
    via_type = int(getattr(via, "type", ViaType.VT_THROUGH))
    board_thickness_mm = _board_thickness_mm()
    if via_type == ViaType.VT_MICRO:
        return board_thickness_mm * 0.2
    if via_type == ViaType.VT_BLIND_BURIED:
        return board_thickness_mm * 0.5
    return board_thickness_mm


def _via_observation(via: _ViaLike) -> ViaStubObservation:
    x_mm, y_mm = _via_position_mm(via)
    net_name = str(getattr(getattr(via, "net", None), "name", "") or "(no net)")
    drill_mm = nm_to_mm(int(getattr(via, "drill_diameter", 0)))
    via_type_name = ViaType.Name(int(getattr(via, "type", ViaType.VT_THROUGH)))
    return ViaStubObservation(
        net_name=net_name,
        x_mm=x_mm,
        y_mm=y_mm,
        via_type_name=via_type_name,
        drill_mm=drill_mm,
        stub_mm=_via_stub_length_mm(via),
    )


def _critical_frequencies_mhz() -> list[float]:
    try:
        from .project import load_design_intent

        return list(load_design_intent().critical_frequencies_mhz)
    except ValueError:
        return []


def _response_limit() -> int:
    return get_config().max_items_per_response


@dataclass(frozen=True)
class SignalIntegrityViaStubDependencies:
    service: SignalIntegrityViaStubService


def _default_dependencies() -> SignalIntegrityViaStubDependencies:
    return SignalIntegrityViaStubDependencies(service=SignalIntegrityViaStubService())


def _analyze_vias(
    payload: ViaStubInput,
    deps: SignalIntegrityViaStubDependencies,
) -> str:
    vias = _selected_vias(payload.via_positions)
    if not vias:
        return "No vias matched the supplied positions on the active board."

    limit = _response_limit()
    visible_vias = vias[:limit]
    observations = [_via_observation(via) for via in visible_vias]
    return deps.service.analyze(
        payload=payload,
        board_thickness_mm=_board_thickness_mm(),
        observations=observations,
        critical_frequencies_mhz=_critical_frequencies_mhz(),
        omitted_observations=max(0, len(vias) - len(visible_vias)),
    )


def register(
    mcp: FastMCP,
    dependencies: SignalIntegrityViaStubDependencies | None = None,
) -> None:
    """Register via-stub resonance analysis tools."""
    deps = dependencies or _default_dependencies()

    @mcp.tool()
    def si_check_via_stub(
        frequency_ghz: float,
        via_positions: list[_ViaPosition] | None = None,
        er: float = 4.0,
    ) -> str:
        """Estimate via-stub resonance and risk for selected vias on the active board.

        ``via_positions`` are ``[x_mm, y_mm]`` two-element arrays.
        """
        payload = ViaStubInput(
            via_positions=[(position[0], position[1]) for position in via_positions or []],
            frequency_ghz=frequency_ghz,
            er=er,
        )
        return _analyze_vias(payload, deps)
