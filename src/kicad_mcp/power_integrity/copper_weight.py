"""FastMCP-independent routed-copper current-capacity analysis."""

from __future__ import annotations

from dataclasses import dataclass

from ..models.power_integrity import CopperWeightCheckInput
from ..models.verdict import Verdict, VerdictReport
from ..utils.units import mm_to_mil


@dataclass(frozen=True)
class CopperTrackObservation:
    """Normalized routed-track facts needed by the copper-weight service."""

    width_mm: float
    length_mm: float
    copper_thickness_mm: float
    external: bool


def ipc_current_capacity_a(
    width_mm: float,
    copper_thickness_mm_value: float,
    *,
    external: bool,
    max_temp_rise_c: float,
) -> float:
    """Estimate conservative IPC-style current capacity for one trace cross-section."""
    area_mil_sq = mm_to_mil(width_mm) * mm_to_mil(copper_thickness_mm_value)
    k = 0.048 if external else 0.024
    return float(k * (max_temp_rise_c**0.44) * (area_mil_sq**0.725))


def required_width_mm(
    expected_current_a: float,
    copper_thickness_mm_value: float,
    *,
    external: bool,
    max_temp_rise_c: float,
) -> float:
    """Estimate required trace width for the requested current and temperature rise."""
    k = 0.048 if external else 0.024
    area_mil_sq = (expected_current_a / (k * (max_temp_rise_c**0.44))) ** (1.0 / 0.725)
    return float(area_mil_sq / mm_to_mil(copper_thickness_mm_value) * 0.0254)


@dataclass(frozen=True)
class PowerIntegrityCopperWeightService:
    """Own routed-copper current-capacity analysis and verdict rendering."""

    def analyze(
        self,
        payload: CopperWeightCheckInput,
        tracks: list[CopperTrackObservation],
    ) -> VerdictReport:
        if not tracks:
            message = f"No routed tracks were found for net '{payload.net_name}'."
            return VerdictReport.from_text_verdict(
                text=message,
                summary=message,
                verdict="WARN",
                source="pdn_check_copper_weight",
                evidence=[{"net_name": payload.net_name, "track_count": 0}],
                remediation="Route copper for this net, then rerun pdn_check_copper_weight().",
                failure_mode="configuration",
                metadata={"domain": "power_integrity"},
            )

        min_width_mm = min(track.width_mm for track in tracks)
        avg_width_mm = sum(track.width_mm for track in tracks) / len(tracks)
        capacities = [
            ipc_current_capacity_a(
                track.width_mm,
                track.copper_thickness_mm,
                external=track.external,
                max_temp_rise_c=payload.max_temp_rise_c,
            )
            for track in tracks
        ]
        bottleneck_index = min(range(len(tracks)), key=capacities.__getitem__)
        bottleneck = tracks[bottleneck_index]
        capacity_a = capacities[bottleneck_index]
        width_required_mm = max(
            required_width_mm(
                payload.expected_current_a,
                track.copper_thickness_mm,
                external=track.external,
                max_temp_rise_c=payload.max_temp_rise_c,
            )
            for track in tracks
        )
        verdict: Verdict = "PASS" if capacity_a >= payload.expected_current_a else "WARN"

        lines = [
            f"Copper weight check for {payload.net_name} ({verdict}):",
            f"- Routed track count: {len(tracks)}",
            f"- Minimum width: {min_width_mm:.3f} mm",
            f"- Average width: {avg_width_mm:.3f} mm",
            f"- Bottleneck width: {bottleneck.width_mm:.3f} mm",
            f"- Bottleneck copper thickness: {bottleneck.copper_thickness_mm:.4f} mm",
            f"- Bottleneck layer class: {'external' if bottleneck.external else 'internal'}",
            f"- Assumed temperature rise limit: {payload.max_temp_rise_c:.1f} C",
            f"- Estimated conservative current capacity: {capacity_a:.3f} A",
            f"- Expected current: {payload.expected_current_a:.3f} A",
            f"- Recommended minimum width: {width_required_mm:.3f} mm",
            "- Uses a conservative IPC-style current-carrying estimate for quick review.",
        ]
        return VerdictReport.from_text_verdict(
            text="\n".join(lines),
            summary=(
                f"Copper capacity is {capacity_a:.3f} A for "
                f"{payload.expected_current_a:.3f} A expected."
            ),
            verdict=verdict,
            source="pdn_check_copper_weight",
            evidence=[
                {
                    "net_name": payload.net_name,
                    "track_count": len(tracks),
                    "min_width_mm": min_width_mm,
                    "bottleneck_width_mm": bottleneck.width_mm,
                    "bottleneck_copper_thickness_mm": bottleneck.copper_thickness_mm,
                    "bottleneck_external": bottleneck.external,
                    "capacity_a": capacity_a,
                    "expected_current_a": payload.expected_current_a,
                    "required_width_mm": width_required_mm,
                }
            ],
            remediation=(
                "Increase copper width/weight or reduce current, then rerun "
                "pdn_check_copper_weight()."
            )
            if verdict != "PASS"
            else "",
            metadata={"domain": "power_integrity"},
        )
