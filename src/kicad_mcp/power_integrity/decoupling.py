"""FastMCP-independent PDN decoupling recommendation rendering."""

from __future__ import annotations

from dataclasses import dataclass

from ..models.power_integrity import DecouplingRecommendationInput

CapacitorCandidate = tuple[str, float, str]


@dataclass(frozen=True)
class PowerIntegrityDecouplingService:
    """Own deterministic PDN decoupling recommendation logic."""

    def recommend(
        self,
        *,
        payload: DecouplingRecommendationInput,
        references: list[str],
        recommendation_mm: float,
        nearby_by_ref: dict[str, list[CapacitorCandidate]],
    ) -> str:
        scale = max(0.5, min(5.0, 20.0 / payload.target_ripple_mv))
        bulk_uf = max(4.7, round(4.7 * len(payload.ic_refs) * scale, 1))

        lines = [
            f"Decoupling recommendation for {payload.vcc_net}:",
            f"- Supply voltage: {payload.supply_voltage_v:.3f} V",
            f"- Target ripple: {payload.target_ripple_mv:.2f} mV",
            "- Baseline local decoupler per IC: 100 nF X7R placed at the power pin",
            f"- Shared bulk recommendation near rail entry: {bulk_uf:.1f} uF low-ESR",
        ]
        for reference in references:
            nearby = nearby_by_ref.get(reference, [])
            if nearby:
                best_ref, best_distance_mm, best_value = nearby[0]
                verdict = "OK" if best_distance_mm <= recommendation_mm else "MOVE CLOSER"
                lines.append(
                    f"- {reference}: nearest capacitor is {best_ref} ({best_value or 'unknown'}) "
                    f"at {best_distance_mm:.3f} mm [{verdict}]"
                )
            else:
                lines.append(
                    f"- {reference}: add one 100 nF local cap within {recommendation_mm:.2f} mm"
                )
        return "\n".join(lines)
