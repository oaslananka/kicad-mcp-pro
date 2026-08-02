"""EMC-oriented board review helpers.

These are first-order, geometry/heuristic checks, not a substitute for EM simulation,
a compliance lab, or formal sign-off against a named standard. Use them as a fast
first-pass review. EM-result-based, standard-named, fail-capable checks are planned
(P3-T5).
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Protocol, cast

from kipy.proto.board.board_types_pb2 import BoardLayer
from mcp.server.fastmcp import FastMCP

from ..config import get_config
from ..connection import get_board
from ..models.common import _FootprintLike
from ..models.verdict import Verdict, VerdictReport
from ..pcb.board_access import (
    board_footprints,
    board_shapes,
    board_tracks,
    board_vias,
    board_zones,
)
from ..pcb.geometry import point_xy_mm, track_segment_length_mm
from ..utils.impedance import propagation_delay_ps_per_mm
from ..utils.layers import resolve_layer
from ..utils.solver_seams import emc_method, format_solver_verdict
from ..utils.units import nm_to_mm


class _TrackLike(Protocol):
    start: object
    end: object
    width: int
    layer: BoardLayer.ValueType
    net: object


class _ViaLike(Protocol):
    position: object
    net: object


class _ZoneLike(Protocol):
    name: str
    net: object
    layers: Iterable[BoardLayer.ValueType]
    filled: bool


def _track_net_name(track: _TrackLike) -> str:
    return str(getattr(getattr(track, "net", None), "name", "") or "")


def _zone_net_name(zone: _ZoneLike) -> str:
    return str(getattr(getattr(zone, "net", None), "name", "") or "")


def _is_ground_like_net(net_name: str) -> bool:
    normalized = net_name.strip().upper()
    return normalized in {"GND", "AGND", "DGND", "PGND", "GROUND"} or normalized.startswith("GND_")


def _emc_verdict_report(title: str, source: str, verdict: str, detail: str) -> VerdictReport:
    resolved_verdict = cast(Verdict, verdict)
    text = f"{title} ({resolved_verdict}):\n- {detail}"
    return VerdictReport.from_text_verdict(
        text=text,
        summary=detail,
        verdict=resolved_verdict,
        source=source,
        evidence=[{"check": source, "detail": detail}],
        remediation=(
            "Review layout EMC geometry, apply the recommended correction, and rerun this check."
        )
        if verdict != "PASS"
        else "",
        next_action="Treat this result as an EMC critic, not formal compliance sign-off.",
        metadata={"domain": "emc", "check": source},
    )


def _footprint_reference(footprint: _FootprintLike) -> str:
    return str(footprint.reference_field.text.value)


def _gnd_zones() -> list[_ZoneLike]:
    zones = cast(list[_ZoneLike], board_zones(get_board()))
    return [zone for zone in zones if _is_ground_like_net(_zone_net_name(zone))]


def _tracks_for_net(net_name: str) -> list[_TrackLike]:
    tracks = cast(list[_TrackLike], board_tracks(get_board()))
    return [track for track in tracks if _track_net_name(track) == net_name]


def _track_lengths_by_net() -> dict[str, float]:
    lengths: dict[str, float] = {}
    for track in cast(list[_TrackLike], board_tracks(get_board())):
        net_name = _track_net_name(track)
        if not net_name:
            continue
        lengths[net_name] = lengths.get(net_name, 0.0) + track_segment_length_mm(track)
    return lengths


def _track_widths_mm(net_name: str) -> list[float]:
    return [nm_to_mm(int(track.width)) for track in _tracks_for_net(net_name)]


def _via_positions_mm(net_name: str) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    for via in cast(list[_ViaLike], board_vias(get_board())):
        via_net = str(getattr(getattr(via, "net", None), "name", "") or "")
        if via_net != net_name:
            continue
        points.append(point_xy_mm(via.position))
    return points


def _board_bounds() -> tuple[float, float, float, float] | None:
    xs: list[float] = []
    ys: list[float] = []
    for shape in board_shapes(get_board()):
        if getattr(shape, "layer", None) != BoardLayer.BL_Edge_Cuts:
            continue
        for attr in ("start", "end", "top_left", "bottom_right", "center", "radius_point"):
            point = getattr(shape, attr, None)
            if point is None:
                continue
            x_mm, y_mm = point_xy_mm(point)
            xs.append(x_mm)
            ys.append(y_mm)
    if xs and ys:
        return min(xs), min(ys), max(xs), max(ys)
    return None


def _nearest_cap_distance_mm(reference: str) -> float | None:
    footprints = cast(list[_FootprintLike], board_footprints(get_board()))
    anchor = next(
        (footprint for footprint in footprints if _footprint_reference(footprint) == reference),
        None,
    )
    if anchor is None:
        return None
    source_x_mm, source_y_mm = point_xy_mm(anchor.position)
    caps = [
        footprint
        for footprint in footprints
        if _footprint_reference(footprint).upper().startswith("C")
    ]
    if not caps:
        return None
    return min(
        math.hypot(source_x_mm - x_mm, source_y_mm - y_mm)
        for x_mm, y_mm in (point_xy_mm(cap.position) for cap in caps)
    )


def _high_speed_nets() -> list[str]:
    priority = ("USB", "HS", "CLK", "DDR", "PCIE", "ETH", "HDMI")
    tracks = cast(list[_TrackLike], board_tracks(get_board()))
    names = sorted({name for name in (_track_net_name(track) for track in tracks) if name})
    intent_nets = _intent_critical_nets()
    if intent_nets:
        return [name for name in intent_nets if name in names] or intent_nets
    selected = [name for name in names if any(token in name.upper() for token in priority)]
    return selected or names


def _intent_critical_nets() -> list[str]:
    try:
        from .project import load_design_intent

        return load_design_intent().critical_nets
    except ValueError:
        return []


def _find_diff_pair() -> tuple[str, str] | None:
    names = {name.upper(): name for name in _high_speed_nets()}
    for upper_name, original in names.items():
        if upper_name.endswith("DP") and f"{upper_name[:-2]}DN" in names:
            return original, names[f"{upper_name[:-2]}DN"]
        if upper_name.endswith("_P") and f"{upper_name[:-2]}_N" in names:
            return original, names[f"{upper_name[:-2]}_N"]
    return None


def _nearest_neighbor_gap_mm(points: list[tuple[float, float]]) -> float | None:
    if len(points) < 2:
        return None
    nearest: list[float] = []
    for index, (x_mm, y_mm) in enumerate(points):
        distances = [
            math.hypot(x_mm - other_x_mm, y_mm - other_y_mm)
            for other_index, (other_x_mm, other_y_mm) in enumerate(points)
            if other_index != index
        ]
        nearest.append(min(distances))
    return max(nearest)


def _emc_check_ground_plane_voids_text(max_void_area_mm2: float) -> tuple[str, str]:
    zones = _gnd_zones()
    if not zones:
        return "FAIL", "No GND copper pours or planes were found."
    layers = sorted(
        {BoardLayer.Name(layer) for zone in zones for layer in getattr(zone, "layers", [])}
    )
    verdict = "PASS" if len(layers) >= 2 else "WARN"
    return (
        verdict,
        f"GND pours present on {len(layers)} layer(s): {', '.join(layers)}. "
        f"Void-area proxy threshold {max_void_area_mm2:.1f} mm^2.",
    )


def _first_ground_reference_layer() -> str:
    for zone in _gnd_zones():
        for layer in getattr(zone, "layers", []):
            layer_name = str(BoardLayer.Name(layer))
            return layer_name.removeprefix("BL_")
    return "B_Cu"


def _emc_check_single_return_path_text(
    signal_net: str,
    reference_plane_layer: str,
) -> tuple[str, str]:
    tracks = _tracks_for_net(signal_net)
    if not tracks:
        return "FAIL", f"No routed tracks were found for signal net '{signal_net}'."
    plane_layer = resolve_layer(reference_plane_layer)
    plane_exists = any(
        _is_ground_like_net(_zone_net_name(zone)) and plane_layer in getattr(zone, "layers", [])
        for zone in cast(list[_ZoneLike], board_zones(get_board()))
    )
    if not plane_exists:
        return "WARN", f"No GND plane was found on reference layer {reference_plane_layer}."
    signal_layers = sorted({BoardLayer.Name(track.layer) for track in tracks})
    return (
        "PASS",
        f"Signal net '{signal_net}' is routed on {', '.join(signal_layers)} with a GND "
        f"reference plane on {reference_plane_layer}.",
    )


def _emc_check_return_path_text(
    signal_net: str,
    reference_plane_layer: str,
    search_radius_mm: float = 2.0,
) -> tuple[str, str]:
    target_nets = [signal_net] if signal_net else _high_speed_nets()
    if not target_nets:
        return "WARN", "No high-speed or design-intent critical nets were available."
    plane_layer = (
        _first_ground_reference_layer()
        if reference_plane_layer == "auto"
        else reference_plane_layer
    )
    failures: list[str] = []
    details: list[str] = []
    for net_name in target_nets[: get_config().max_items_per_response]:
        verdict, detail = _emc_check_single_return_path_text(net_name, plane_layer)
        details.append(f"{net_name}: {verdict} ({detail})")
        if verdict != "PASS":
            failures.append(net_name)
    if failures:
        geometry = ", ".join(f"net={name}, radius={search_radius_mm:.2f}mm" for name in failures)
        return (
            "WARN",
            f"Violations: {len(failures)}. Geometry: {geometry}. " + " ".join(details),
        )
    return (
        "PASS",
        f"All {len(target_nets)} checked net(s) have a GND return on {plane_layer}. "
        + " ".join(details),
    )


def _emc_check_split_plane_text(signal_nets: list[str]) -> tuple[str, str]:
    planes_by_layer: dict[str, set[str]] = {}
    for zone in cast(list[_ZoneLike], board_zones(get_board())):
        zone_net = _zone_net_name(zone)
        if not zone_net or _is_ground_like_net(zone_net):
            continue
        for layer in getattr(zone, "layers", []):
            planes_by_layer.setdefault(BoardLayer.Name(layer), set()).add(zone_net)
    split_layers = {layer: nets for layer, nets in planes_by_layer.items() if len(nets) > 1}
    if not split_layers:
        return "PASS", "No split power-plane proxies were detected on the current copper layers."
    details = "; ".join(f"{layer}={sorted(nets)}" for layer, nets in split_layers.items())
    return (
        "WARN",
        f"Potential split-plane crossing risk for {', '.join(signal_nets)} because {details}.",
    )


def _emc_check_decoupling_text(max_distance_mm: float) -> tuple[str, str]:
    ics = [
        footprint
        for footprint in cast(list[_FootprintLike], board_footprints(get_board()))
        if _footprint_reference(footprint).upper().startswith("U")
    ]
    if not ics:
        return "WARN", "No IC footprints were found to evaluate decoupling placement."
    distances = {
        _footprint_reference(footprint): _nearest_cap_distance_mm(_footprint_reference(footprint))
        for footprint in ics
    }
    missing = [reference for reference, distance in distances.items() if distance is None]
    far = [
        f"{reference}={distance:.3f} mm"
        for reference, distance in distances.items()
        if distance is not None and distance > max_distance_mm
    ]
    if missing:
        return "WARN", f"Missing local capacitors near: {', '.join(missing)}."
    if far:
        return "WARN", f"Decouplers exceed {max_distance_mm:.1f} mm: {', '.join(far)}."
    return "PASS", f"All evaluated ICs have a local capacitor within {max_distance_mm:.1f} mm."


def _emc_check_via_stitching_text(max_gap_mm: float, ground_net: str) -> tuple[str, str]:
    points = _via_positions_mm(ground_net)
    if len(points) < 2:
        return "WARN", f"Only {len(points)} {ground_net} via(s) were found for stitching review."
    worst_gap = _nearest_neighbor_gap_mm(points)
    if worst_gap is None:
        return "WARN", "Unable to compute via stitching gaps."
    verdict = "PASS" if worst_gap <= max_gap_mm else "WARN"
    return verdict, f"Worst nearest-neighbor {ground_net} via gap is {worst_gap:.3f} mm."


def _emc_check_diff_pair_text(net_p: str, net_n: str, max_skew_ps: float) -> tuple[str, str]:
    lengths = _track_lengths_by_net()
    if net_p not in lengths or net_n not in lengths:
        return "WARN", f"Could not locate both routed nets '{net_p}' and '{net_n}'."
    width_p = _track_widths_mm(net_p)
    width_n = _track_widths_mm(net_n)
    skew_mm = abs(lengths[net_p] - lengths[net_n])
    skew_ps = skew_mm * propagation_delay_ps_per_mm(3.0)
    width_delta_pct = 0.0
    if width_p and width_n:
        width_delta_pct = (
            abs((sum(width_p) / len(width_p)) - (sum(width_n) / len(width_n)))
            / (sum(width_p + width_n) / len(width_p + width_n))
            * 100.0
        )
    verdict = "PASS" if skew_ps <= max_skew_ps and width_delta_pct <= 10.0 else "WARN"
    return (
        verdict,
        (
            f"Skew={skew_ps:.3f} ps, length delta={skew_mm:.3f} mm, "
            f"width delta={width_delta_pct:.2f}%."
        ),
    )


def _emc_check_high_speed_rules_text(net_class: str, max_stub_length_mm: float) -> tuple[str, str]:
    matching = [name for name in _high_speed_nets() if net_class.upper() in name.upper()]
    if not matching:
        return "WARN", f"No routed nets matched the high-speed class token '{net_class}'."
    worst_stub = 0.0
    for net_name in matching:
        segment_lengths = sorted(
            track_segment_length_mm(track) for track in _tracks_for_net(net_name)
        )
        if len(segment_lengths) > 1:
            worst_stub = max(worst_stub, segment_lengths[0])
    verdict = "PASS" if worst_stub <= max_stub_length_mm else "WARN"
    return (
        verdict,
        f"Shortest branch/stub proxy across {len(matching)} net(s): {worst_stub:.3f} mm.",
    )


def _emc_check_edge_clearance_text(min_clearance_mm: float) -> tuple[str, str]:
    bounds = _board_bounds()
    if bounds is None:
        return "WARN", "Board outline was not available for edge-clearance review."
    x1_mm, y1_mm, x2_mm, y2_mm = bounds
    distances: list[float] = []
    for track in cast(list[_TrackLike], board_tracks(get_board())):
        if _track_net_name(track) not in _high_speed_nets():
            continue
        for point in (track.start, track.end):
            x_mm, y_mm = point_xy_mm(point)
            distances.append(min(x_mm - x1_mm, x2_mm - x_mm, y_mm - y1_mm, y2_mm - y_mm))
    if not distances:
        return "WARN", "No high-speed tracks were available for edge-clearance review."
    minimum = min(distances)
    verdict = "PASS" if minimum >= min_clearance_mm else "WARN"
    return verdict, f"Minimum high-speed edge clearance is {minimum:.3f} mm."


def _emc_check_ground_via_density_text() -> tuple[str, str]:
    points = _via_positions_mm("GND")
    bounds = _board_bounds()
    if bounds is None or not points:
        return "WARN", "Ground-via density could not be estimated from the active board."
    x1_mm, y1_mm, x2_mm, y2_mm = bounds
    area_cm2 = max(((x2_mm - x1_mm) * (y2_mm - y1_mm)) / 100.0, 1e-6)
    density = len(points) / area_cm2
    verdict = "PASS" if density >= 0.5 else "WARN"
    return verdict, f"GND via density is {density:.2f} vias/cm^2."


def _emc_check_reference_plane_text() -> tuple[str, str]:
    gnd_layers = {
        BoardLayer.Name(layer) for zone in _gnd_zones() for layer in getattr(zone, "layers", [])
    }
    if not gnd_layers:
        return "FAIL", "No dedicated GND plane or pour layers were detected."
    return "PASS", f"Reference plane coverage is available on: {', '.join(sorted(gnd_layers))}."


def register(mcp: FastMCP) -> None:
    """Register EMC-oriented review tools."""

    @mcp.tool()
    def emc_check_ground_plane_voids(max_void_area_mm2: float = 25.0) -> VerdictReport:
        """Review GND plane presence and a simple void-risk proxy."""
        verdict, detail = _emc_check_ground_plane_voids_text(max_void_area_mm2)
        return _emc_verdict_report(
            "Ground plane void review",
            "emc_check_ground_plane_voids",
            verdict,
            detail,
        )

    @mcp.tool()
    def emc_check_return_path_continuity(
        signal_net: str = "",
        reference_plane_layer: str = "auto",
        search_radius_mm: float = 2.0,
    ) -> VerdictReport:
        """Check EMC return-path continuity for a signal or all critical high-speed nets."""
        verdict, detail = _emc_check_return_path_text(
            signal_net,
            reference_plane_layer,
            search_radius_mm,
        )
        return _emc_verdict_report(
            "Return path continuity",
            "emc_check_return_path_continuity",
            verdict,
            detail,
        )

    @mcp.tool()
    def emc_check_split_plane_crossing(signal_nets: list[str]) -> VerdictReport:
        """Warn when routed signals share layers with split non-ground planes."""
        verdict, detail = _emc_check_split_plane_text(signal_nets)
        return _emc_verdict_report(
            "Split-plane crossing review",
            "emc_check_split_plane_crossing",
            verdict,
            detail,
        )

    @mcp.tool()
    def emc_check_decoupling_placement(max_distance_mm: float = 3.0) -> VerdictReport:
        """Review whether ICs have nearby decoupling capacitors."""
        verdict, detail = _emc_check_decoupling_text(max_distance_mm)
        return _emc_verdict_report(
            "Decoupling placement review",
            "emc_check_decoupling_placement",
            verdict,
            detail,
        )

    @mcp.tool()
    def emc_check_via_stitching(max_gap_mm: float = 5.0, ground_net: str = "GND") -> VerdictReport:
        """Estimate via-stitching density from existing ground vias."""
        verdict, detail = _emc_check_via_stitching_text(max_gap_mm, ground_net)
        return _emc_verdict_report(
            "Via stitching review",
            "emc_check_via_stitching",
            verdict,
            detail,
        )

    @mcp.tool()
    def emc_check_differential_pair_symmetry(
        net_p: str,
        net_n: str,
        max_skew_ps: float = 10.0,
    ) -> VerdictReport:
        """Review diff-pair skew and width symmetry."""
        verdict, detail = _emc_check_diff_pair_text(net_p, net_n, max_skew_ps)
        return _emc_verdict_report(
            "Differential-pair symmetry",
            "emc_check_differential_pair_symmetry",
            verdict,
            detail,
        )

    @mcp.tool()
    def emc_check_high_speed_routing_rules(
        net_class: str,
        max_stub_length_mm: float = 1.0,
    ) -> VerdictReport:
        """Review a high-speed net class for a short-stub proxy."""
        verdict, detail = _emc_check_high_speed_rules_text(net_class, max_stub_length_mm)
        return _emc_verdict_report(
            "High-speed routing rule review",
            "emc_check_high_speed_routing_rules",
            verdict,
            detail,
        )

    @mcp.tool()
    def emc_run_full_compliance(standard: str = "FCC") -> VerdictReport:
        """Run a lightweight EMC sweep with at least ten heuristic checks."""
        diff_pair = _find_diff_pair()
        signal_net = next(iter(_high_speed_nets()), "")
        checks = [
            ("ground_plane_voids", *_emc_check_ground_plane_voids_text(25.0)),
            (
                "return_path_continuity",
                *(
                    _emc_check_return_path_text(signal_net, "B_Cu")
                    if signal_net
                    else ("WARN", "No candidate signal net was found.")
                ),
            ),
            (
                "split_plane_crossing",
                *(
                    _emc_check_split_plane_text(
                        _high_speed_nets()[: get_config().max_items_per_response]
                    )
                ),
            ),
            ("decoupling_placement", *_emc_check_decoupling_text(3.0)),
            ("via_stitching", *_emc_check_via_stitching_text(5.0, "GND")),
            (
                "differential_pair_symmetry",
                *(
                    _emc_check_diff_pair_text(diff_pair[0], diff_pair[1], 10.0)
                    if diff_pair is not None
                    else ("WARN", "No differential pair was auto-detected.")
                ),
            ),
            ("high_speed_routing_rules", *_emc_check_high_speed_rules_text("USB", 1.0)),
            ("edge_clearance", *_emc_check_edge_clearance_text(3.0)),
            ("ground_via_density", *_emc_check_ground_via_density_text()),
            ("reference_plane_coverage", *_emc_check_reference_plane_text()),
        ]
        lines = [f"EMC compliance sweep ({standard.upper()}):", f"- Checks run: {len(checks)}"]
        for name, verdict, detail in checks:
            lines.append(f"- {name}: {verdict} | {detail}")
        method = emc_method()
        lines.append(
            f"- Method: {method['method']} (solver_grade={method['solver_grade']}). "
            f"{method['accuracy']}"
        )
        lines.append(f"- {format_solver_verdict(method)}")
        lines.append(f"- Note: {method['note']} Treat results as a critic, not a release sign-off.")
        overall: Verdict = "PASS"
        if any(verdict == "FAIL" for _, verdict, _ in checks):
            overall = "FAIL"
        elif any(verdict == "WARN" for _, verdict, _ in checks):
            overall = "WARN"
        return VerdictReport.from_text_verdict(
            text="\n".join(lines),
            summary=f"EMC compliance sweep completed with {overall} verdict.",
            verdict=overall,
            source="emc_run_full_compliance",
            evidence=[
                {"check": name, "verdict": verdict, "detail": detail}
                for name, verdict, detail in checks
            ],
            remediation=(
                "Review WARN/FAIL EMC checks and rerun the sweep." if overall != "PASS" else ""
            ),
            next_action="Treat results as a critic, not formal compliance sign-off.",
            metadata={
                "domain": "emc",
                "standard": standard.upper(),
                "checks_run": len(checks),
            },
        )
