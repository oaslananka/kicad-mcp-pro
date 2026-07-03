"""Signal-integrity helpers for trace impedance, skew, and placement heuristics.

These are first-order, closed-form estimates (IPC-2141/Wheeler-class formulas), not a
substitute for a 2D/3D field solver, EM simulation, or formal sign-off. Treat results as
a fast first-pass review; accuracy is typically ~5-10%. A field-solver mode is planned
(P3-T1/P3-T3).
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Protocol, cast

from kipy.proto.board.board_types_pb2 import ViaType
from mcp.server.fastmcp import FastMCP

from ..config import get_config
from ..connection import get_board
from ..models.common import _FootprintLike, _PadLike
from ..models.signal_integrity import (
    DecouplingPlacementInput,
    DifferentialPairSkewInput,
    HighSpeedChannelInput,
    LengthMatchingInput,
    StackupInput,
    TraceImpedanceInput,
    TraceWidthForImpedanceInput,
    ViaStubInput,
)
from ..utils.channel import (
    ChannelMetrics,
    ChannelSpec,
    closed_form_channel_metrics,
    simulate_channel_insertion_loss,
)
from ..utils.field_solver import impedance_method
from ..utils.impedance import (
    DIELECTRIC_LIBRARY,
    copper_thickness_mm,
    differential_impedance,
    get_dielectric,
    list_dielectric_materials,
    propagation_delay_ps_per_mm,
    recommend_dielectric_for_frequency,
    recommended_decoupling_distance_mm,
    solve_spacing_for_differential_impedance,
    solve_width_for_impedance,
    trace_impedance,
    via_stub_resonance_ghz,
    via_stub_risk_level,
)
from ..utils.ngspice import NgspiceRunner
from ..utils.solver_seams import (
    channel_method,
    emc_method,
    format_solver_verdict,
    ir_drop_method,
    pdn_mesh_method,
    thermal_fd_method,
    thermal_method,
)
from ..utils.units import _coord_nm, nm_to_mm
from ..verdicts import three_level_verdict, warn_max_from
from .design_intent_state import resolve_design_intent

_DEFAULT_OUTER_DIELECTRIC_MM = 0.18
_DEFAULT_BOARD_THICKNESS_MM = 1.6

# Conservative default differential-pair skew budget (ps) used only when neither an
# explicit budget nor a design-intent interface budget is available. Formerly an
# inline hardcoded ``10.0`` in the gate (work order K2).
_DEFAULT_DIFF_SKEW_BUDGET_PS = 10.0


def _resolve_skew_budget_ps(net_p: str, net_n: str) -> tuple[float, str]:
    """Return ``(budget_ps, source_note)`` for a differential pair.

    Prefers a design-intent interface ``diff_skew_max_ps`` whose ``net_prefix`` matches
    one of the nets; falls back to the tightest declared interface budget, then to a
    conservative default with an explicit "intent missing" note so a missing spec is
    never silently treated as a pass.
    """
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


def _write_nc_rule(
    net_class: str,
    clearance_mm: float,
    track_width_mm: float,
    diff_gap_mm: float | None,
) -> str:
    """Write a net-class rule to the project's .kicad_dru file and return the path."""
    from ..utils.sexpr import _sexpr_string
    from .routing import _mm, _write_rule  # local import avoids a module cycle

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


class _TrackLike(Protocol):
    start: object
    end: object
    width: int
    net: object


class _ViaLike(Protocol):
    position: object
    drill_diameter: int
    net: object
    type: int


def _track_length_mm(track: _TrackLike) -> float:
    dx = _coord_nm(track.end, "x") - _coord_nm(track.start, "x")
    dy = _coord_nm(track.end, "y") - _coord_nm(track.start, "y")
    return math.hypot(dx, dy) / 1_000_000.0


def _track_lengths_by_net() -> dict[str, float]:
    lengths: dict[str, float] = {}
    for track in cast(list[_TrackLike], list(get_board().get_tracks())):
        net_name = str(getattr(getattr(track, "net", None), "name", "") or "")
        if not net_name:
            continue
        lengths[net_name] = lengths.get(net_name, 0.0) + _track_length_mm(track)
    return lengths


def _track_width_mm(net_name: str) -> float | None:
    widths: list[float] = []
    for track in cast(list[_TrackLike], list(get_board().get_tracks())):
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


def _board_thickness_mm() -> float:
    thickness_nm = 0
    for layer in _stackup_layers():
        thickness_nm += int(getattr(layer, "thickness", 0))
    if thickness_nm <= 0:
        return _DEFAULT_BOARD_THICKNESS_MM
    return nm_to_mm(thickness_nm)


def _board_footprints() -> list[_FootprintLike]:
    return cast(list[_FootprintLike], list(get_board().get_footprints()))


def _board_pads() -> list[_PadLike]:
    return cast(list[_PadLike], list(get_board().get_pads()))


def _footprint_reference(footprint: _FootprintLike) -> str:
    return str(footprint.reference_field.text.value)


def _footprint_value(footprint: _FootprintLike) -> str:
    return str(footprint.value_field.text.value)


def _footprint_position_mm(footprint: _FootprintLike) -> tuple[float, float]:
    return (
        nm_to_mm(_coord_nm(footprint.position, "x")),
        nm_to_mm(_coord_nm(footprint.position, "y")),
    )


def _find_footprint(reference: str) -> _FootprintLike | None:
    for footprint in _board_footprints():
        if _footprint_reference(footprint) == reference:
            return footprint
    return None


def _find_power_anchor(ic_ref: str, power_pin: str) -> tuple[float, float]:
    for pad in _board_pads():
        if _footprint_reference(pad.parent) == ic_ref and str(pad.number) == power_pin:
            return (
                nm_to_mm(_coord_nm(pad.position, "x")),
                nm_to_mm(_coord_nm(pad.position, "y")),
            )

    footprint = _find_footprint(ic_ref)
    if footprint is None:
        raise ValueError(f"Footprint '{ic_ref}' was not found on the active board.")
    return _footprint_position_mm(footprint)


def _nearest_capacitors(
    source_ref: str,
    source_x_mm: float,
    source_y_mm: float,
) -> list[tuple[str, float, str]]:
    matches: list[tuple[str, float, str]] = []
    for footprint in _board_footprints():
        reference = _footprint_reference(footprint)
        if reference == source_ref or not reference.upper().startswith("C"):
            continue
        x_mm, y_mm = _footprint_position_mm(footprint)
        distance_mm = math.hypot(source_x_mm - x_mm, source_y_mm - y_mm)
        matches.append((reference, distance_mm, _footprint_value(footprint)))
    return sorted(matches, key=lambda item: item[1])


def _via_position_mm(via: _ViaLike) -> tuple[float, float]:
    position = via.position
    return (
        nm_to_mm(_coord_nm(position, "x")),
        nm_to_mm(_coord_nm(position, "y")),
    )


def _selected_vias(via_positions: list[tuple[float, float]]) -> list[_ViaLike]:
    vias: list[_ViaLike] = cast(list[_ViaLike], list(get_board().get_vias()))
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


def _format_impedance_result(
    *,
    title: str,
    trace_type: str,
    width_mm: float,
    height_mm: float,
    er: float,
    copper_oz: float,
    impedance_ohm: float,
    effective_er: float,
    spacing_mm: float | None = None,
    differential_ohm: float | None = None,
) -> str:
    lines = [
        title,
        f"- Trace type: {trace_type}",
        f"- Width: {width_mm:.4f} mm",
        f"- Dielectric height: {height_mm:.4f} mm",
        f"- Copper: {copper_oz:.2f} oz ({copper_thickness_mm(copper_oz):.4f} mm)",
        f"- Relative permittivity (Er): {er:.3f}",
        f"- Effective permittivity: {effective_er:.3f}",
        f"- Estimated single-ended impedance: {impedance_ohm:.2f} ohm",
    ]
    if spacing_mm is not None:
        lines.append(f"- Gap / spacing: {spacing_mm:.4f} mm")
    if differential_ohm is not None:
        lines.append(f"- Estimated differential impedance: {differential_ohm:.2f} ohm")
    method = impedance_method()
    lines.append(f"- Method: {method['method']} — {method['accuracy']}")
    lines.append(f"- {format_solver_verdict(method)}")
    if not method["solver_grade"]:
        lines.append(f"- Note: {method['note']}")
    return "\n".join(lines)


def _channel_output_dir() -> Path:
    return get_config().ensure_output_dir("channel")


def _ghz(freq_hz: float) -> str:
    return f"{freq_hz / 1e9:.3f} GHz"


def _format_channel_result(metrics: ChannelMetrics, max_insertion_loss_db: float) -> str:
    fail_il_db = warn_max_from(max_insertion_loss_db)
    verdict = three_level_verdict(
        metrics.insertion_loss_nyquist_db, pass_max=max_insertion_loss_db, warn_max=fail_il_db
    )
    lines = [
        "High-speed channel analysis:",
        f"- Nyquist frequency: {_ghz(metrics.nyquist_hz)}",
        f"- Insertion loss at Nyquist: {metrics.insertion_loss_nyquist_db:.2f} dB "
        f"({verdict}; PASS <= {max_insertion_loss_db:.1f} dB, WARN <= {fail_il_db:.1f} dB, "
        f"FAIL > {fail_il_db:.1f} dB)",
        f"- -3 dB bandwidth: {_ghz(metrics.bandwidth_3db_hz)}",
        f"- Eye height: {metrics.eye_height_v:.4f} V "
        f"({metrics.eye_height_ratio * 100.0:.1f}% of drive amplitude)",
    ]
    method = channel_method(metrics.source == "ngspice")
    lines.append(f"- Method: {method['method']} — {method['accuracy']}")
    lines.append(f"- {format_solver_verdict(method)}")
    lines.extend(f"- {note}" for note in metrics.notes)
    if not method["solver_grade"]:
        lines.append(f"- Note: {method['note']}")
    return "\n".join(lines)


def _stackup_templates(manufacturer: str, layer_count: int) -> list[dict[str, str | float]]:
    normalized = manufacturer.casefold()
    if normalized == "pcbway":
        templates: dict[int, list[dict[str, str | float]]] = {
            2: [
                {"name": "F.Cu", "role": "signal", "material": "Copper", "thickness_mm": 0.035},
                {"name": "Core", "role": "dielectric", "material": "FR4", "thickness_mm": 1.53},
                {"name": "B.Cu", "role": "signal", "material": "Copper", "thickness_mm": 0.035},
            ],
            4: [
                {"name": "F.Cu", "role": "signal", "material": "Copper", "thickness_mm": 0.035},
                {"name": "Prepreg", "role": "dielectric", "material": "FR4", "thickness_mm": 0.17},
                {
                    "name": "In1.Cu",
                    "role": "ground plane",
                    "material": "Copper",
                    "thickness_mm": 0.018,
                },
                {"name": "Core", "role": "dielectric", "material": "FR4", "thickness_mm": 1.124},
                {
                    "name": "In2.Cu",
                    "role": "power / signal",
                    "material": "Copper",
                    "thickness_mm": 0.018,
                },
                {"name": "Prepreg", "role": "dielectric", "material": "FR4", "thickness_mm": 0.17},
                {"name": "B.Cu", "role": "signal", "material": "Copper", "thickness_mm": 0.035},
            ],
            6: [
                {"name": "F.Cu", "role": "signal", "material": "Copper", "thickness_mm": 0.035},
                {"name": "Prepreg", "role": "dielectric", "material": "FR4", "thickness_mm": 0.11},
                {
                    "name": "In1.Cu",
                    "role": "ground plane",
                    "material": "Copper",
                    "thickness_mm": 0.018,
                },
                {"name": "Core", "role": "dielectric", "material": "FR4", "thickness_mm": 0.35},
                {"name": "In2.Cu", "role": "signal", "material": "Copper", "thickness_mm": 0.018},
                {"name": "Core", "role": "dielectric", "material": "FR4", "thickness_mm": 0.65},
                {
                    "name": "In3.Cu",
                    "role": "power plane",
                    "material": "Copper",
                    "thickness_mm": 0.018,
                },
                {"name": "Core", "role": "dielectric", "material": "FR4", "thickness_mm": 0.35},
                {
                    "name": "In4.Cu",
                    "role": "ground plane",
                    "material": "Copper",
                    "thickness_mm": 0.018,
                },
                {"name": "Prepreg", "role": "dielectric", "material": "FR4", "thickness_mm": 0.11},
                {"name": "B.Cu", "role": "signal", "material": "Copper", "thickness_mm": 0.035},
            ],
        }
        return templates[layer_count]

    templates = {
        2: [
            {"name": "F.Cu", "role": "signal", "material": "Copper", "thickness_mm": 0.035},
            {"name": "Core", "role": "dielectric", "material": "FR4", "thickness_mm": 1.53},
            {"name": "B.Cu", "role": "signal", "material": "Copper", "thickness_mm": 0.035},
        ],
        4: [
            {"name": "F.Cu", "role": "signal", "material": "Copper", "thickness_mm": 0.035},
            {"name": "Prepreg", "role": "dielectric", "material": "FR4", "thickness_mm": 0.18},
            {
                "name": "In1.Cu",
                "role": "solid GND plane",
                "material": "Copper",
                "thickness_mm": 0.018,
            },
            {"name": "Core", "role": "dielectric", "material": "FR4", "thickness_mm": 1.114},
            {
                "name": "In2.Cu",
                "role": "power / signal",
                "material": "Copper",
                "thickness_mm": 0.018,
            },
            {"name": "Prepreg", "role": "dielectric", "material": "FR4", "thickness_mm": 0.18},
            {"name": "B.Cu", "role": "signal", "material": "Copper", "thickness_mm": 0.035},
        ],
        6: [
            {"name": "F.Cu", "role": "signal", "material": "Copper", "thickness_mm": 0.035},
            {"name": "Prepreg", "role": "dielectric", "material": "FR4", "thickness_mm": 0.11},
            {
                "name": "In1.Cu",
                "role": "solid GND plane",
                "material": "Copper",
                "thickness_mm": 0.018,
            },
            {"name": "Core", "role": "dielectric", "material": "FR4", "thickness_mm": 0.33},
            {
                "name": "In2.Cu",
                "role": "high-speed signal",
                "material": "Copper",
                "thickness_mm": 0.018,
            },
            {"name": "Core", "role": "dielectric", "material": "FR4", "thickness_mm": 0.62},
            {
                "name": "In3.Cu",
                "role": "power plane",
                "material": "Copper",
                "thickness_mm": 0.018,
            },
            {"name": "Core", "role": "dielectric", "material": "FR4", "thickness_mm": 0.33},
            {
                "name": "In4.Cu",
                "role": "solid GND plane",
                "material": "Copper",
                "thickness_mm": 0.018,
            },
            {"name": "Prepreg", "role": "dielectric", "material": "FR4", "thickness_mm": 0.11},
            {"name": "B.Cu", "role": "signal", "material": "Copper", "thickness_mm": 0.035},
        ],
    }
    return templates[layer_count]


def register(mcp: FastMCP) -> None:
    """Register signal-integrity tools."""

    @mcp.tool()
    def si_get_solver_capabilities() -> str:
        """Report configured solver-grade analysis capabilities and unavailable seams."""
        capabilities = {
            "trace_impedance_field_solver": impedance_method(),
            "dc_ir_drop_field_solver": ir_drop_method(),
            "pdn_mesh_solver": pdn_mesh_method(),
            "thermal_closed_form": thermal_method(),
            "thermal_plane_fd_solver": thermal_fd_method(),
            "emc_full_wave_solver": emc_method(),
            "high_speed_channel_closed_form": channel_method(measured=False),
        }
        return json.dumps(
            {
                "solver_capabilities": capabilities,
                "policy": {
                    "solver_unavailable_mode": True,
                    "release_signoff_requires_solver_grade": True,
                    "closed_form_results_are_critic_only": True,
                },
            },
            indent=2,
            sort_keys=True,
        )

    @mcp.tool()
    def si_calculate_trace_impedance(
        width_mm: float,
        height_mm: float,
        er: float = 4.2,
        trace_type: str = "microstrip",
        copper_oz: float = 1.0,
        spacing_mm: float = 0.2,
    ) -> str:
        """Estimate PCB trace impedance using quasi-static interconnect formulas."""
        payload = TraceImpedanceInput(
            width_mm=width_mm,
            height_mm=height_mm,
            er=er,
            trace_type=trace_type,
            copper_oz=copper_oz,
            spacing_mm=spacing_mm,
        )
        impedance_ohm, effective_er = trace_impedance(
            payload.width_mm,
            payload.height_mm,
            payload.er,
            trace_type=payload.trace_type,
            copper_oz=payload.copper_oz,
            spacing_mm=payload.spacing_mm,
        )
        differential_ohm, _ = differential_impedance(
            payload.width_mm,
            payload.height_mm,
            payload.spacing_mm,
            payload.er,
            trace_type=payload.trace_type,
            copper_oz=payload.copper_oz,
        )
        return _format_impedance_result(
            title="Trace impedance estimate:",
            trace_type=payload.trace_type,
            width_mm=payload.width_mm,
            height_mm=payload.height_mm,
            er=payload.er,
            copper_oz=payload.copper_oz,
            impedance_ohm=impedance_ohm,
            effective_er=effective_er,
            spacing_mm=payload.spacing_mm,
            differential_ohm=differential_ohm,
        )

    @mcp.tool()
    def si_calculate_trace_width_for_impedance(
        target_ohm: float,
        height_mm: float,
        er: float = 4.2,
        trace_type: str = "microstrip",
        copper_oz: float = 1.0,
        spacing_mm: float = 0.2,
    ) -> str:
        """Solve for a trace width that meets the requested impedance target."""
        payload = TraceWidthForImpedanceInput(
            target_ohm=target_ohm,
            height_mm=height_mm,
            er=er,
            trace_type=trace_type,
            copper_oz=copper_oz,
            spacing_mm=spacing_mm,
        )
        solved_width_mm = solve_width_for_impedance(
            payload.target_ohm,
            payload.height_mm,
            payload.er,
            trace_type=payload.trace_type,
            copper_oz=payload.copper_oz,
            spacing_mm=payload.spacing_mm,
        )
        impedance_ohm, effective_er = trace_impedance(
            solved_width_mm,
            payload.height_mm,
            payload.er,
            trace_type=payload.trace_type,
            copper_oz=payload.copper_oz,
            spacing_mm=payload.spacing_mm,
        )
        return _format_impedance_result(
            title=f"Width synthesis for {payload.target_ohm:.2f} ohm:",
            trace_type=payload.trace_type,
            width_mm=solved_width_mm,
            height_mm=payload.height_mm,
            er=payload.er,
            copper_oz=payload.copper_oz,
            impedance_ohm=impedance_ohm,
            effective_er=effective_er,
            spacing_mm=payload.spacing_mm,
        )

    @mcp.tool()
    def si_check_differential_pair_skew(
        net_p: str,
        net_n: str,
        er: float = 4.2,
        trace_type: str = "microstrip",
        skew_budget_ps: float = 0.0,
    ) -> str:
        """Estimate differential-pair length skew and delay mismatch from board tracks.

        Returns a PASS/WARN/FAIL verdict. The skew budget comes from ``skew_budget_ps``
        if > 0, otherwise from the matching design-intent interface, otherwise a
        conservative default. PASS within budget, WARN up to 2x budget, FAIL beyond.
        """
        payload = DifferentialPairSkewInput(net_p=net_p, net_n=net_n, er=er, trace_type=trace_type)
        lengths = _track_lengths_by_net()
        if payload.net_p not in lengths or payload.net_n not in lengths:
            return (
                "Could not compute differential-pair skew because one or both nets "
                "have no routed track segments on the active board."
            )

        height_mm = _outer_dielectric_height_mm()
        width_mm = _track_width_mm(payload.net_p) or _track_width_mm(payload.net_n) or 0.2
        _, effective_er = trace_impedance(
            width_mm,
            height_mm,
            payload.er,
            trace_type=payload.trace_type,
            spacing_mm=0.2,
        )
        delay_ps_per_mm = propagation_delay_ps_per_mm(effective_er)
        length_p = lengths[payload.net_p]
        length_n = lengths[payload.net_n]
        skew_mm = abs(length_p - length_n)
        skew_ps = skew_mm * delay_ps_per_mm

        if skew_budget_ps > 0:
            budget_ps, budget_source = skew_budget_ps, f"explicit budget {skew_budget_ps:.1f} ps"
        else:
            budget_ps, budget_source = _resolve_skew_budget_ps(payload.net_p, payload.net_n)
        fail_ps = warn_max_from(budget_ps)
        verdict = three_level_verdict(skew_ps, pass_max=budget_ps, warn_max=fail_ps)

        return "\n".join(
            [
                f"Differential-pair skew analysis ({verdict}):",
                f"- Net P: {payload.net_p} length={length_p:.3f} mm",
                f"- Net N: {payload.net_n} length={length_n:.3f} mm",
                f"- Skew: {skew_mm:.3f} mm",
                f"- Estimated delay mismatch: {skew_ps:.3f} ps",
                f"- Effective permittivity used: {effective_er:.3f}",
                f"- Assumed outer dielectric height: {height_mm:.3f} mm",
                f"- Skew budget: {budget_ps:.1f} ps (source: {budget_source})",
                f"- Thresholds: PASS <= {budget_ps:.1f} ps, WARN <= {fail_ps:.1f} ps, "
                f"FAIL > {fail_ps:.1f} ps.",
            ]
        )

    @mcp.tool()
    def si_validate_length_matching(net_groups: list[list[str]], tolerance_mm: float = 2.0) -> str:
        """Validate that each net group is matched within the supplied tolerance."""
        payload = LengthMatchingInput(net_groups=net_groups, tolerance_mm=tolerance_mm)
        lengths = _track_lengths_by_net()

        fail_mm = warn_max_from(payload.tolerance_mm)
        lines = [
            f"Length-matching validation (tolerance {payload.tolerance_mm:.3f} mm; "
            f"PASS <= {payload.tolerance_mm:.3f} mm, WARN <= {fail_mm:.3f} mm, "
            f"FAIL > {fail_mm:.3f} mm):"
        ]
        for index, group in enumerate(payload.net_groups, start=1):
            unique_group = [net for net in group if net]
            if not unique_group:
                lines.append(f"- Group {index}: skipped empty group")
                continue
            missing = [net for net in unique_group if net not in lengths]
            if missing:
                lines.append(f"- Group {index}: missing routed tracks for {', '.join(missing)}")
                continue

            samples = [(net, lengths[net]) for net in unique_group]
            shortest_net, shortest_mm = min(samples, key=lambda item: item[1])
            longest_net, longest_mm = max(samples, key=lambda item: item[1])
            spread_mm = longest_mm - shortest_mm
            verdict = three_level_verdict(
                spread_mm, pass_max=payload.tolerance_mm, warn_max=fail_mm
            )
            lines.append(
                f"- Group {index} ({verdict}): shortest {shortest_net}={shortest_mm:.3f} mm, "
                f"longest {longest_net}={longest_mm:.3f} mm, spread={spread_mm:.3f} mm"
            )
        return "\n".join(lines)

    @mcp.tool()
    def si_analyze_high_speed_channel(
        length_mm: float,
        data_rate_gbps: float,
        z0_ohm: float = 50.0,
        eps_eff: float = 3.8,
        loss_tangent: float = 0.02,
        trace_width_mm: float = 0.2,
        amplitude_v: float = 1.0,
        max_insertion_loss_db: float = 10.0,
    ) -> str:
        """Estimate high-speed channel insertion loss and eye opening for a lossy trace.

        Sums conductor skin-effect and dielectric (tan-delta) loss to get insertion loss
        at the Nyquist rate, then a first-order loss-limited eye height, with a
        PASS/WARN/FAIL verdict against ``max_insertion_loss_db``. When an ngspice CLI is
        available the insertion loss is measured from an RLGC-ladder AC sweep; otherwise a
        closed-form estimate is used. The method label states which path produced the
        numbers.
        """
        payload = HighSpeedChannelInput(
            length_mm=length_mm,
            z0_ohm=z0_ohm,
            data_rate_gbps=data_rate_gbps,
            eps_eff=eps_eff,
            loss_tangent=loss_tangent,
            trace_width_mm=trace_width_mm,
            amplitude_v=amplitude_v,
            max_insertion_loss_db=max_insertion_loss_db,
        )
        spec = ChannelSpec(
            length_mm=payload.length_mm,
            z0_ohm=payload.z0_ohm,
            data_rate_gbps=payload.data_rate_gbps,
            eps_eff=payload.eps_eff,
            loss_tangent=payload.loss_tangent,
            trace_width_mm=payload.trace_width_mm,
            amplitude_v=payload.amplitude_v,
        )
        metrics = closed_form_channel_metrics(spec)
        cfg = get_config()
        measured = simulate_channel_insertion_loss(
            spec,
            NgspiceRunner(cfg.ngspice_cli, cfg.cli_timeout),
            _channel_output_dir(),
        )
        if measured is not None:
            metrics = measured
        return _format_channel_result(metrics, payload.max_insertion_loss_db)

    @mcp.tool()
    def si_generate_stackup(
        layer_count: int = 4,
        target_impedance_ohm: float = 50.0,
        manufacturer: str = "JLCPCB",
        er: float = 4.2,
        copper_oz: float = 1.0,
    ) -> str:
        """Generate a practical board stackup recommendation and target trace geometry."""
        payload = StackupInput(
            layer_count=layer_count,
            target_impedance_ohm=target_impedance_ohm,
            manufacturer=manufacturer,
            er=er,
            copper_oz=copper_oz,
        )
        template = _stackup_templates(payload.manufacturer, payload.layer_count)
        outer_dielectric_mm = next(
            float(layer["thickness_mm"])
            for layer in template
            if str(layer["role"]).startswith("dielectric")
        )
        width_mm = solve_width_for_impedance(
            payload.target_impedance_ohm,
            outer_dielectric_mm,
            payload.er,
            trace_type="microstrip",
            copper_oz=payload.copper_oz,
        )
        impedance_ohm, effective_er = trace_impedance(
            width_mm,
            outer_dielectric_mm,
            payload.er,
            trace_type="microstrip",
            copper_oz=payload.copper_oz,
        )
        diff_gap_mm = solve_spacing_for_differential_impedance(
            100.0,
            width_mm * 0.55,
            outer_dielectric_mm,
            payload.er,
            trace_type="microstrip",
            copper_oz=payload.copper_oz,
        )
        diff_ohm, _ = differential_impedance(
            width_mm * 0.55,
            outer_dielectric_mm,
            diff_gap_mm,
            payload.er,
            trace_type="microstrip",
            copper_oz=payload.copper_oz,
        )

        lines = [
            f"Recommended {payload.layer_count}-layer {payload.manufacturer} stackup:",
            f"- Target outer-layer impedance: {payload.target_impedance_ohm:.2f} ohm",
            f"- Solved outer microstrip width: {width_mm:.3f} mm",
            f"- Rechecked impedance: {impedance_ohm:.2f} ohm",
            f"- Effective permittivity: {effective_er:.3f}",
            (
                f"- Approximate 100 ohm differential pair starting point: "
                f"width {width_mm * 0.55:.3f} mm / gap {diff_gap_mm:.3f} mm "
                f"(estimate {diff_ohm:.2f} ohm)"
            ),
            "Layers:",
        ]
        for index, layer in enumerate(template, start=1):
            lines.append(
                f"- {index}. {layer['name']} | {layer['role']} | "
                f"{layer['material']} | {float(layer['thickness_mm']):.3f} mm"
            )
        lines.append(
            "- Review with your fabricator's published stackup table "
            "before freezing impedance rules."
        )
        return "\n".join(lines)

    @mcp.tool()
    def si_check_via_stub(
        frequency_ghz: float,
        via_positions: list[tuple[float, float]] | None = None,
        er: float = 4.0,
    ) -> str:
        """Estimate via-stub resonance and risk for selected vias on the active board."""
        payload = ViaStubInput(
            via_positions=via_positions or [],
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

    @mcp.tool()
    def si_list_dielectric_materials() -> str:
        """List all built-in dielectric materials with Er, loss tangent, and frequency range.

        Use the returned material keys with si_synthesize_stackup_for_interfaces()
        to select the appropriate laminate for your design.
        """
        materials = list_dielectric_materials()
        lines = [f"Available dielectric materials ({len(materials)} total):", ""]
        for m in materials:
            lines.append(f"  [{m['key']}] {m['name']}  Er={m['er']}  tan_d={m['loss_tangent']}")
            lines.append(f"    {m['description']}")
            lines.append("")
        lines.append("Use key string with si_synthesize_stackup_for_interfaces().")
        return "\n".join(lines)

    @mcp.tool()
    def si_synthesize_stackup_for_interfaces(
        interfaces: list[dict[str, object]],
        cost_tier: str = "standard",
        board_thickness_mm: float = 1.6,
    ) -> str:
        """Synthesise a PCB stackup that meets the impedance requirements of the given interfaces.

        Analyses each InterfaceSpec dict and recommends:
        - Layer count
        - Dielectric material
        - Copper weight per layer
        - Outer dielectric thickness for target impedance
        - Net class settings (impedance, clearance, diff-pair gap)

        Args:
            interfaces: List of InterfaceSpec dicts (matching project_set_design_intent
                interface format). Each must have at least ``kind`` and optionally
                ``impedance_target_ohm``, ``differential``, ``diff_skew_max_ps``.
            cost_tier: ``"standard"`` (FR4), ``"midloss"`` (FR4 mid/low-loss),
                ``"highspeed"`` (Rogers/Megtron). Overrides material selection.
            board_thickness_mm: Target board thickness in mm (1.0, 1.6, 2.0, 3.2).

        Returns:
            Recommended stackup specification and net class table in human-readable
            markdown, ready to pass to pcb_set_stackup() and pcb_set_net_class().
        """
        # Map cost tier to dielectric preference
        tier_material = {
            "standard": "fr4_standard",
            "midloss": "fr4_midloss",
            "lowloss": "fr4_lowloss",
            "highspeed": "ro4350b",
            "rf": "ro4003c",
            "ultralow": "megtron6",
        }.get(cost_tier.lower(), "fr4_standard")

        # Determine maximum frequency from interface kinds
        interface_freq_ghz: dict[str, float] = {
            "usb2": 0.48,
            "usb3": 2.5,
            "usb3_gen2": 5.0,
            "pcie_g1": 1.25,
            "pcie_g2": 2.5,
            "pcie_g3": 4.0,
            "pcie_g4": 8.0,
            "ethernet_100": 0.1,
            "ethernet_1000": 0.625,
            "ethernet_2500": 1.25,
            "ethernet_10000": 5.0,
            "hdmi_1x": 1.65,
            "hdmi_2x": 3.4,
            "displayport": 2.7,
            "mipi_csi2": 1.5,
            "mipi_dsi": 1.5,
            "ddr3": 0.8,
            "ddr4": 1.6,
            "ddr5": 3.2,
            "lpddr4": 2.1,
            "lpddr5": 3.2,
            "can": 0.004,
            "canfd": 0.008,
            "rs485": 0.01,
            "spi_hs": 0.05,
            "i2c": 0.001,
            "i3c": 0.025,
            "uart": 0.001,
            "jtag": 0.03,
            "swd": 0.05,
            "lvds": 0.625,
            "sgmii": 0.625,
        }

        max_freq_ghz = 0.0
        has_differential = False
        has_highspeed = False
        iface_summaries: list[str] = []

        for raw in interfaces:
            kind = str(raw.get("kind", "")).lower()
            freq = interface_freq_ghz.get(kind, 0.0)
            max_freq_ghz = max(max_freq_ghz, freq)
            diff = bool(raw.get("differential", False))
            impedance = raw.get("impedance_target_ohm")
            if diff or kind in {
                "usb2",
                "usb3",
                "usb3_gen2",
                "pcie_g1",
                "pcie_g2",
                "pcie_g3",
                "pcie_g4",
                "ethernet_1000",
                "ethernet_2500",
                "ethernet_10000",
                "hdmi_1x",
                "hdmi_2x",
                "displayport",
                "lvds",
                "sgmii",
            }:
                has_differential = True
            if freq >= 1.0:
                has_highspeed = True
            iface_summaries.append(
                f"  {kind}: {freq:.2f} GHz"
                + (
                    f", {impedance}ohm diff"
                    if impedance and diff
                    else f", {impedance}ohm SE"
                    if impedance
                    else ""
                )
            )

        # Override material if frequency mandates it
        freq_material = recommend_dielectric_for_frequency(max_freq_ghz)
        # Choose the better of cost_tier and freq recommendation
        tier_er = DIELECTRIC_LIBRARY[tier_material][1]
        freq_er = DIELECTRIC_LIBRARY[freq_material][1]
        if freq_er < tier_er:
            material_key = freq_material  # frequency wins
        else:
            material_key = tier_material

        mat_name, er, loss_tan, mat_desc = get_dielectric(material_key)

        # Determine layer count
        if not has_highspeed and not has_differential:
            layer_count = 2
        elif max_freq_ghz < 1.0:
            layer_count = 4
        elif max_freq_ghz < 5.0:
            layer_count = 4 if not has_highspeed else 6
        else:
            layer_count = 8

        # Calculate outer dielectric thickness for 50ohm microstrip (1 oz Cu)
        outer_h_mm = 0.18  # starting guess
        target_ohm = 50.0
        width_50ohm = solve_width_for_impedance(target_ohm, outer_h_mm, er, copper_oz=1.0)
        actual_z, _ = trace_impedance(width_50ohm, outer_h_mm, er, copper_oz=1.0)

        # Diff pair gap for 90ohm differential (USB standard)
        gap_90ohm = solve_spacing_for_differential_impedance(
            90.0, width_50ohm * 0.8, outer_h_mm, er, copper_oz=1.0
        )

        lines = [
            "# Stackup Synthesis Report",
            "",
            "## Interface Analysis",
            *iface_summaries,
            "",
            f"Max interface frequency: {max_freq_ghz:.2f} GHz",
            f"Has differential pairs: {has_differential}",
            f"Has high-speed signals (&gt;=1 GHz): {has_highspeed}",
            "",
            "## Recommended Stackup",
            f"- Layer count: **{layer_count}**",
            f"- Dielectric: **{mat_name}** (Er={er}, tan_d={loss_tan})",
            f"- Outer prepreg thickness: ~{outer_h_mm:.2f} mm",
            f"- Board thickness: {board_thickness_mm:.1f} mm",
            "- Outer copper weight: 1 oz (0.035 mm)",
            "- Inner copper weight: 0.5 oz (recommended for dense routing)",
            "",
            "## Trace Width Targets (50ohm SE microstrip on outer layers)",
            f"- 50ohm trace width: **{width_50ohm:.3f} mm** (actual Z={actual_z:.1f}ohm)",
            f"- 90ohm diff-pair gap: **{gap_90ohm:.3f} mm** (USB 2.0 / USB 3.x)",
            "",
            "## Net Class Configuration",
            "| Net class | Clearance (mm) | Track width (mm) | Diff gap (mm) |",
            "|-----------|---------------|-----------------|--------------|",
            "| Default   | 0.20          | 0.20            | —            |",
            f"| 50R_SE    | 0.20          | {width_50ohm:.3f}         | —            |",
            f"| 90R_DIFF  | 0.15          | {width_50ohm * 0.8:.3f}     | {gap_90ohm:.3f}      |",
            f"| 100R_DIFF | 0.15          | {width_50ohm * 0.75:.3f}    |              |",
            "",
            "## Next Steps",
            "1. Call pcb_set_stackup() with layer_count and dielectric params above.",
            "2. Call pcb_set_net_class() for each high-speed net class.",
            "3. Route differential pairs with si_validate_length_matching().",
            "",
            f"Material note: {mat_desc}",
        ]
        return "\n".join(lines)

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
        net_class_templates: dict[str, dict[str, object]] = {
            "usb2": {"clearance": 0.15, "track_width": 0.20, "diff_gap": 0.20},
            "usb3": {"clearance": 0.12, "track_width": 0.18, "diff_gap": 0.15},
            "usb3_gen2": {"clearance": 0.10, "track_width": 0.15, "diff_gap": 0.12},
            "pcie_g1": {"clearance": 0.12, "track_width": 0.18, "diff_gap": 0.18},
            "pcie_g2": {"clearance": 0.10, "track_width": 0.15, "diff_gap": 0.15},
            "pcie_g3": {"clearance": 0.10, "track_width": 0.15, "diff_gap": 0.12},
            "pcie_g4": {"clearance": 0.08, "track_width": 0.12, "diff_gap": 0.10},
            "ethernet_100": {"clearance": 0.20, "track_width": 0.25, "diff_gap": 0.20},
            "ethernet_1000": {"clearance": 0.15, "track_width": 0.20, "diff_gap": 0.15},
            "ethernet_2500": {"clearance": 0.12, "track_width": 0.18, "diff_gap": 0.12},
            "ethernet_10000": {"clearance": 0.10, "track_width": 0.15, "diff_gap": 0.10},
            "hdmi_1x": {"clearance": 0.12, "track_width": 0.15, "diff_gap": 0.15},
            "hdmi_2x": {"clearance": 0.10, "track_width": 0.12, "diff_gap": 0.12},
            "ddr3": {"clearance": 0.12, "track_width": 0.15, "diff_gap": 0.15},
            "ddr4": {"clearance": 0.10, "track_width": 0.12, "diff_gap": 0.12},
            "ddr5": {"clearance": 0.08, "track_width": 0.10, "diff_gap": 0.10},
            "lvds": {"clearance": 0.10, "track_width": 0.15, "diff_gap": 0.15},
            "can": {"clearance": 0.20, "track_width": 0.25, "diff_gap": 0.25},
            "canfd": {"clearance": 0.20, "track_width": 0.25, "diff_gap": 0.25},
        }

        plan: list[dict[str, object]] = []
        for raw in interfaces:
            kind = str(raw.get("kind", "")).lower()
            template = net_class_templates.get(kind)
            if template is None:
                continue  # Skip low-speed / non-critical interfaces
            impedance = raw.get("impedance_target_ohm")
            differential = bool(raw.get("differential", False))
            net_prefix = str(raw.get("net_prefix", ""))
            nc_name = f"{kind.upper().replace('_', '_')}"
            plan.append(
                {
                    "net_class": nc_name,
                    "clearance_mm": template["clearance"],
                    "track_width_mm": template["track_width"],
                    "diff_pair_gap_mm": template.get("diff_gap") if differential else None,
                    "impedance_target_ohm": impedance,
                    "net_prefix": net_prefix,
                }
            )

        if not plan:
            return "No high-speed interfaces found that require custom net classes."

        lines = ["## Net Class Binding Plan", ""]
        for entry in plan:
            lines.append(f"### {entry['net_class']}")
            lines.append(f"- Clearance: {entry['clearance_mm']} mm")
            lines.append(f"- Track width: {entry['track_width_mm']} mm")
            if entry.get("diff_pair_gap_mm") is not None:
                lines.append(f"- Diff-pair gap: {entry['diff_pair_gap_mm']} mm")
            if entry.get("impedance_target_ohm") is not None:
                lines.append(f"- Impedance target: {entry['impedance_target_ohm']} ohm")
            if entry.get("net_prefix"):
                lines.append(f"- Net prefix filter: {entry['net_prefix']}")
            lines.append(
                f"  → Call: pcb_set_net_class(net_class={entry['net_class']!r}, "
                f"clearance={entry['clearance_mm']}, "
                f"track_width={entry['track_width_mm']})"
            )
            lines.append("")

        if dry_run:
            lines.append(
                "_Dry-run mode: no changes applied. "
                "Set dry_run=False to write all net class rules to the .kicad_dru file._"
            )
        else:
            # Actually write each net class rule to the design rules file.
            written: list[str] = []
            errors: list[str] = []
            rules_file: str = ""
            for entry in plan:
                nc = str(entry["net_class"])
                cl = float(entry["clearance_mm"])  # type: ignore[arg-type]
                tw = float(entry["track_width_mm"])  # type: ignore[arg-type]
                dg = (
                    float(entry["diff_pair_gap_mm"])  # type: ignore[arg-type]
                    if entry.get("diff_pair_gap_mm") is not None
                    else None
                )
                try:
                    rules_file = _write_nc_rule(nc, cl, tw, dg)
                    written.append(nc)
                except Exception as exc:
                    errors.append(f"{nc}: {exc}")

            if written:
                lines.append(f"\n**Applied** {len(written)} net class rule(s) to `{rules_file}`:")
                for nc in written:
                    lines.append(f"  - {nc}")
            if errors:
                lines.append(f"\n**Errors** ({len(errors)}):")
                for e in errors:
                    lines.append(f"  - {e}")
            if not written and not errors:
                lines.append("No net class rules were written (empty plan).")

        return "\n".join(lines)
