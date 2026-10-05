"""Signal-integrity helpers for trace impedance, skew, and placement heuristics.

These are first-order, closed-form estimates (IPC-2141/Wheeler-class formulas), not a
substitute for a 2D/3D field solver, EM simulation, or formal sign-off. Treat results as
a fast first-pass review; accuracy is typically ~5-10%. A field-solver mode is planned
(P3-T1/P3-T3).
"""

from __future__ import annotations

import math
from typing import Annotated, Protocol, cast

from kipy.proto.board.board_types_pb2 import ViaType
from mcp.server.mcpserver import MCPServer as FastMCP
from pydantic import Field

from ..config import get_config
from ..connection import get_board
from ..models.common import _FootprintLike, _PadLike
from ..models.signal_integrity import DecouplingPlacementInput, ViaStubInput
from ..pcb.board_access import board_footprints, board_pads, board_vias
from ..pcb.geometry import point_xy_mm
from ..utils.impedance import (
    recommended_decoupling_distance_mm,
    via_stub_resonance_ghz,
    via_stub_risk_level,
)
from ..utils.units import nm_to_mm
from ..verdicts import three_level_verdict, warn_max_from

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


def _is_copper_layer(layer: object) -> bool:
    material = str(getattr(layer, "material_name", "") or "").casefold()
    if material == "copper":
        return True
    layer_name = str(getattr(layer, "layer", ""))
    return "Cu" in layer_name


def _board_thickness_mm() -> float:
    thickness_nm = 0
    for layer in _stackup_layers():
        thickness_nm += int(getattr(layer, "thickness", 0))
    if thickness_nm <= 0:
        return _DEFAULT_BOARD_THICKNESS_MM
    return nm_to_mm(thickness_nm)


def _footprint_reference(footprint: _FootprintLike) -> str:
    return str(footprint.reference_field.text.value)


def _footprint_value(footprint: _FootprintLike) -> str:
    return str(footprint.value_field.text.value)


def _find_footprint(reference: str) -> _FootprintLike | None:
    for footprint in cast(list[_FootprintLike], board_footprints(get_board())):
        if _footprint_reference(footprint) == reference:
            return footprint
    return None


def _find_power_anchor(ic_ref: str, power_pin: str) -> tuple[float, float]:
    for pad in cast(list[_PadLike], board_pads(get_board())):
        if _footprint_reference(pad.parent) == ic_ref and str(pad.number) == power_pin:
            return point_xy_mm(pad.position)

    footprint = _find_footprint(ic_ref)
    if footprint is None:
        raise ValueError(f"Footprint '{ic_ref}' was not found on the active board.")
    return point_xy_mm(footprint.position)


def _nearest_capacitors(
    source_ref: str,
    source_x_mm: float,
    source_y_mm: float,
) -> list[tuple[str, float, str]]:
    matches: list[tuple[str, float, str]] = []
    for footprint in cast(list[_FootprintLike], board_footprints(get_board())):
        reference = _footprint_reference(footprint)
        if reference == source_ref or not reference.upper().startswith("C"):
            continue
        x_mm, y_mm = point_xy_mm(footprint.position)
        distance_mm = math.hypot(source_x_mm - x_mm, source_y_mm - y_mm)
        matches.append((reference, distance_mm, _footprint_value(footprint)))
    return sorted(matches, key=lambda item: item[1])


def _via_position_mm(via: _ViaLike) -> tuple[float, float]:
    position = via.position
    return point_xy_mm(position)


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


def register(mcp: FastMCP) -> None:
    """Register signal-integrity tools."""

    from . import signal_integrity_solver_capabilities

    signal_integrity_solver_capabilities.register(mcp)

    from . import signal_integrity_impedance

    signal_integrity_impedance.register(mcp)

    from . import signal_integrity_differential_pair_skew

    signal_integrity_differential_pair_skew.register(mcp)

    from . import signal_integrity_length_matching

    signal_integrity_length_matching.register(mcp)

    from . import signal_integrity_high_speed_channel

    signal_integrity_high_speed_channel.register(mcp)

    from . import signal_integrity_stackup_generation

    signal_integrity_stackup_generation.register(mcp)

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
        vias = _selected_vias(payload.via_positions)
        if not vias:
            return "No vias matched the supplied positions on the active board."

        board_thickness_mm = _board_thickness_mm()
        lines = [
            f"Via stub analysis at {payload.frequency_ghz:.3f} GHz:",
            f"- Assumed board thickness: {board_thickness_mm:.3f} mm",
            f"- Effective dielectric constant: {payload.er:.3f}",
        ]
        try:
            from .project import load_design_intent

            critical_frequencies_mhz = load_design_intent().critical_frequencies_mhz
        except ValueError:
            critical_frequencies_mhz = []
        for via in vias[: get_config().max_items_per_response]:
            x_mm, y_mm = _via_position_mm(via)
            stub_mm = _via_stub_length_mm(via)
            resonance_ghz = via_stub_resonance_ghz(stub_mm, er=payload.er)
            resonance_mhz = resonance_ghz * 1_000.0
            risk = via_stub_risk_level(stub_mm, payload.frequency_ghz, er=payload.er)
            net_name = str(getattr(getattr(via, "net", None), "name", "") or "(no net)")
            drill_mm = nm_to_mm(int(getattr(via, "drill_diameter", 0)))
            via_type_name = ViaType.Name(int(getattr(via, "type", ViaType.VT_THROUGH)))
            critical_matches = [
                frequency
                for frequency in critical_frequencies_mhz
                if abs(resonance_mhz - frequency) <= frequency * 0.10
            ]
            critical_note = (
                " | CRITICAL resonance near "
                + ", ".join(f"{frequency:.1f} MHz" for frequency in critical_matches)
                if critical_matches
                else ""
            )
            lines.append(
                f"- {net_name} @ ({x_mm:.3f}, {y_mm:.3f}) mm | type={via_type_name} | "
                f"drill={drill_mm:.3f} mm | stub={stub_mm:.3f} mm | "
                f"quarter-wave resonance={resonance_ghz:.2f} GHz | risk={risk}"
                f"{critical_note}"
            )
        return "\n".join(lines)

    @mcp.tool()
    def si_calculate_decoupling_placement(
        ic_ref: str,
        power_pin: str,
        target_freq_mhz: float,
    ) -> str:
        """Estimate decoupling placement quality around an IC power pin."""
        payload = DecouplingPlacementInput(
            ic_ref=ic_ref,
            power_pin=power_pin,
            target_freq_mhz=target_freq_mhz,
        )
        source_x_mm, source_y_mm = _find_power_anchor(payload.ic_ref, payload.power_pin)
        recommended_mm = recommended_decoupling_distance_mm(payload.target_freq_mhz)
        caps = _nearest_capacitors(payload.ic_ref, source_x_mm, source_y_mm)

        lines = [
            "Decoupling placement heuristic:",
            f"- IC reference: {payload.ic_ref}",
            f"- Power pin: {payload.power_pin}",
            f"- Anchor position: ({source_x_mm:.3f}, {source_y_mm:.3f}) mm",
            f"- Target frequency: {payload.target_freq_mhz:.3f} MHz",
            f"- Recommended maximum capacitor distance: {recommended_mm:.3f} mm",
        ]
        if not caps:
            lines.append("- No capacitor footprints were found on the active board.")
            lines.append("- Add a local decoupler as close as possible to the selected power pin.")
            return "\n".join(lines)

        best_ref, best_distance_mm, best_value = caps[0]
        fail_mm = warn_max_from(recommended_mm)
        verdict = three_level_verdict(best_distance_mm, pass_max=recommended_mm, warn_max=fail_mm)
        lines.append(
            f"- Nearest decoupler: {best_ref} ({best_value or 'value unknown'}) "
            f"at {best_distance_mm:.3f} mm ({verdict}; PASS <= {recommended_mm:.3f} mm, "
            f"WARN <= {fail_mm:.3f} mm, FAIL > {fail_mm:.3f} mm)"
        )
        lines.append("Nearest capacitors:")
        for reference, distance_mm, value in caps[: min(len(caps), 5)]:
            lines.append(f"- {reference}: {distance_mm:.3f} mm ({value or 'value unknown'})")
        lines.append(
            "- This is a placement heuristic; verify the actual current loop "
            "and return path in layout review."
        )
        return "\n".join(lines)

    from . import signal_integrity_dielectric_materials

    signal_integrity_dielectric_materials.register(mcp)

    from . import signal_integrity_stackup_synthesis

    signal_integrity_stackup_synthesis.register(mcp)

    from . import signal_integrity_net_class_binding

    signal_integrity_net_class_binding.register(mcp)
