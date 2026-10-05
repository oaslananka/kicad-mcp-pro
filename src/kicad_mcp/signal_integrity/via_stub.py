"""FastMCP-independent via-stub resonance analysis service."""

from __future__ import annotations

from dataclasses import dataclass

from ..models.signal_integrity import ViaStubInput
from ..utils.impedance import via_stub_resonance_ghz, via_stub_risk_level

_RESONANCE_MATCH_TOLERANCE = 0.10


@dataclass(frozen=True)
class ViaStubObservation:
    """Resolved board data needed for deterministic via-stub reporting."""

    net_name: str
    x_mm: float
    y_mm: float
    via_type_name: str
    drill_mm: float
    stub_mm: float


class SignalIntegrityViaStubService:
    """Render via-stub resonance and risk from resolved via observations."""

    def analyze(
        self,
        payload: ViaStubInput,
        board_thickness_mm: float,
        observations: list[ViaStubObservation],
        critical_frequencies_mhz: list[float],
        omitted_observations: int = 0,
    ) -> str:
        if not observations:
            return "No vias matched the supplied positions on the active board."

        lines = [
            f"Via stub analysis at {payload.frequency_ghz:.3f} GHz:",
            f"- Assumed board thickness: {board_thickness_mm:.3f} mm",
            f"- Effective dielectric constant: {payload.er:.3f}",
        ]
        for observation in observations:
            resonance_ghz = via_stub_resonance_ghz(observation.stub_mm, er=payload.er)
            resonance_mhz = resonance_ghz * 1_000.0
            risk = via_stub_risk_level(
                observation.stub_mm,
                payload.frequency_ghz,
                er=payload.er,
            )
            critical_matches = [
                frequency
                for frequency in critical_frequencies_mhz
                if abs(resonance_mhz - frequency) <= frequency * _RESONANCE_MATCH_TOLERANCE
            ]
            critical_note = (
                " | CRITICAL resonance near "
                + ", ".join(f"{frequency:.1f} MHz" for frequency in critical_matches)
                if critical_matches
                else ""
            )
            lines.append(
                f"- {observation.net_name} @ ({observation.x_mm:.3f}, "
                f"{observation.y_mm:.3f}) mm | type={observation.via_type_name} | "
                f"drill={observation.drill_mm:.3f} mm | stub={observation.stub_mm:.3f} mm | "
                f"quarter-wave resonance={resonance_ghz:.2f} GHz | risk={risk}"
                f"{critical_note}"
            )
        if omitted_observations:
            suffix = "via" if omitted_observations == 1 else "vias"
            lines.append(
                f"- WARNING: response limit omitted {omitted_observations} additional {suffix}; "
                "those vias were not checked."
            )
        return "\n".join(lines)
