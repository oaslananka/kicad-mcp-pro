"""FastMCP-independent thermal copper-pour review."""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..models.power_integrity import ThermalPourInput
from ..models.verdict import Verdict, VerdictReport


@dataclass(frozen=True)
class CopperPourObservation:
    """Normalized copper-pour facts needed by the thermal review service."""

    name: str
    layers: tuple[str, ...]


@dataclass(frozen=True)
class PowerIntegrityThermalPourService:
    """Own thermal copper-pour verdict logic and rendering."""

    def analyze(
        self,
        payload: ThermalPourInput,
        pours: list[CopperPourObservation],
        *,
        max_items: int,
    ) -> VerdictReport:
        if not pours:
            message = (
                f"No copper pours were found for net '{payload.net_name}'. "
                "Add a pour or plane for thermal spreading before release."
            )
            return VerdictReport.from_text_verdict(
                text=message,
                summary=message,
                verdict="WARN",
                source="thermal_check_copper_pour",
                evidence=[
                    {
                        "net_name": payload.net_name,
                        "expected_power_w": payload.expected_power_w,
                        "matching_pours": 0,
                    }
                ],
                remediation=(
                    "Add a copper pour or plane for thermal spreading, then rerun "
                    "thermal_check_copper_pour()."
                ),
                failure_mode="configuration",
                metadata={"domain": "thermal"},
            )

        verdict: Verdict = (
            "PASS" if len(pours) >= max(1, math.ceil(payload.expected_power_w)) else "WARN"
        )
        lines = [
            f"Thermal copper-pour review for {payload.net_name} ({verdict}):",
            f"- Expected dissipation: {payload.expected_power_w:.3f} W",
            f"- Matching pours / planes: {len(pours)}",
        ]
        for pour in pours[:max_items]:
            zone_layers = ",".join(pour.layers)
            lines.append(f"- {pour.name or '(unnamed)'} on {zone_layers or '(unknown layers)'}")
        if verdict == "WARN":
            lines.append("- Consider a wider pour, more copper area, and stitched thermal vias.")
        return VerdictReport.from_text_verdict(
            text="\n".join(lines),
            summary=f"Thermal copper support has {len(pours)} matching pour(s)/plane(s).",
            verdict=verdict,
            source="thermal_check_copper_pour",
            evidence=[
                {
                    "net_name": payload.net_name,
                    "expected_power_w": payload.expected_power_w,
                    "matching_pours": len(pours),
                }
            ],
            remediation=(
                "Increase thermal copper area and stitching, then rerun "
                "thermal_check_copper_pour()."
            )
            if verdict != "PASS"
            else "",
            metadata={"domain": "thermal"},
        )
