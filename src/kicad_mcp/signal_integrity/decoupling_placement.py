"""FastMCP-independent decoupling placement analysis service."""

from __future__ import annotations

from ..models.signal_integrity import DecouplingPlacementInput
from ..verdicts import three_level_verdict, warn_max_from

CapacitorCandidate = tuple[str, float, str]


class SignalIntegrityDecouplingPlacementService:
    """Render decoupling placement guidance from resolved board geometry."""

    def analyze(
        self,
        payload: DecouplingPlacementInput,
        source_x_mm: float,
        source_y_mm: float,
        recommended_mm: float,
        capacitors: list[CapacitorCandidate],
        *,
        is_pad_verified: bool = True,
        is_same_rail: bool = True,
    ) -> str:
        lines = [
            "Decoupling placement heuristic:",
            f"- IC reference: {payload.ic_ref}",
            f"- Power pin: {payload.power_pin}",
            f"- Anchor position: ({source_x_mm:.3f}, {source_y_mm:.3f}) mm",
            f"- Target frequency: {payload.target_freq_mhz:.3f} MHz",
            f"- Recommended maximum capacitor distance: {recommended_mm:.3f} mm",
        ]
        if not is_pad_verified:
            lines.append(
                f"- Note: Power pin '{payload.power_pin}' could not be resolved on "
                f"'{payload.ic_ref}'. Center proxy is preliminary advisory only; "
                "cannot confirm electrical PASS."
            )
        if not capacitors:
            lines.append("- No capacitor footprints were found on the active board.")
            lines.append("- Add a local decoupler as close as possible to the selected power pin.")
            return "\n".join(lines)

        best_ref, best_distance_mm, best_value = capacitors[0]
        fail_mm = warn_max_from(recommended_mm)
        verdict: str = three_level_verdict(
            best_distance_mm,
            pass_max=recommended_mm,
            warn_max=fail_mm,
        )
        if not is_pad_verified:
            verdict = "NOT_ASSESSED"
        elif not is_same_rail:
            verdict = "WARN"

        lines.append(
            f"- Nearest decoupler: {best_ref} ({best_value or 'value unknown'}) "
            f"at {best_distance_mm:.3f} mm ({verdict}; PASS <= {recommended_mm:.3f} mm, "
            f"WARN <= {fail_mm:.3f} mm, FAIL > {fail_mm:.3f} mm)"
        )
        lines.append("Nearest capacitors:")
        for reference, distance_mm, value in capacitors[: min(len(capacitors), 5)]:
            lines.append(f"- {reference}: {distance_mm:.3f} mm ({value or 'value unknown'})")
        lines.append(
            "- Distance-only heuristic: preliminary advisory guidance only; "
            "verify the actual current loop, same-rail connectivity and "
            "return path in layout review."
        )
        return "\n".join(lines)
