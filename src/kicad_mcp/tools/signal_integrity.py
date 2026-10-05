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
from ..models.signal_integrity import (
    DecouplingPlacementInput,
    DifferentialPairSkewInput,
    LengthMatchingInput,
    ViaStubInput,
)
from ..models.verdict import VerdictReport
from ..pcb.board_access import board_footprints, board_pads, board_tracks, board_vias
from ..pcb.geometry import point_xy_mm, track_segment_length_mm
from ..utils.impedance import (
    propagation_delay_ps_per_mm,
    recommended_decoupling_distance_mm,
    trace_impedance,
    via_stub_resonance_ghz,
    via_stub_risk_level,
)
from ..utils.units import nm_to_mm
from ..verdicts import three_level_verdict, warn_max_from
from .design_intent_state import resolve_design_intent

_ViaPosition = Annotated[list[float], Field(min_length=2, max_length=2)]
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
        payload = DifferentialPairSkewInput(net_p=net_p, net_n=net_n, er=er, trace_type=trace_type)
        lengths = _track_lengths_by_net()
        if payload.net_p not in lengths or payload.net_n not in lengths:
            message = (
                "Could not compute differential-pair skew because one or both nets "
                "have no routed track segments on the active board."
            )
            return VerdictReport.from_text_verdict(
                text=message,
                summary=message,
                verdict="WARN",
                source="si_check_differential_pair_skew",
                evidence=[
                    {"net_p": payload.net_p, "net_n": payload.net_n, "routed_lengths": lengths}
                ],
                remediation=(
                    "Route both differential-pair nets, then rerun "
                    "si_check_differential_pair_skew()."
                ),
                failure_mode="configuration",
                metadata={"domain": "signal_integrity"},
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

        lines = [
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
        return VerdictReport.from_text_verdict(
            text="\n".join(lines),
            summary=(
                f"Differential-pair skew is {skew_ps:.3f} ps against {budget_ps:.1f} ps budget."
            ),
            verdict=verdict,
            source="si_check_differential_pair_skew",
            evidence=[
                {
                    "net_p": payload.net_p,
                    "net_n": payload.net_n,
                    "length_p_mm": length_p,
                    "length_n_mm": length_n,
                    "skew_mm": skew_mm,
                    "skew_ps": skew_ps,
                    "budget_ps": budget_ps,
                    "budget_source": budget_source,
                }
            ],
            remediation="Tune pair lengths/routing, then rerun si_check_differential_pair_skew()."
            if verdict != "PASS"
            else "",
            metadata={"domain": "signal_integrity"},
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
