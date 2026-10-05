"""FastMCP-independent differential-pair skew analysis service."""

from __future__ import annotations

from collections.abc import Callable, Mapping

from ..models.signal_integrity import DifferentialPairSkewInput
from ..models.verdict import VerdictReport
from ..utils.impedance import propagation_delay_ps_per_mm, trace_impedance
from ..verdicts import three_level_verdict, warn_max_from

TrackWidthProvider = Callable[[str], float | None]
DielectricHeightProvider = Callable[[], float]
SkewBudgetResolver = Callable[[str, str], tuple[float, str]]


class SignalIntegrityDifferentialPairSkewService:
    """Analyze differential-pair routed-length skew and delay mismatch."""

    def analyze(
        self,
        payload: DifferentialPairSkewInput,
        lengths: Mapping[str, float],
        skew_budget_ps: float,
        track_width_provider: TrackWidthProvider,
        dielectric_height_provider: DielectricHeightProvider,
        budget_resolver: SkewBudgetResolver,
    ) -> VerdictReport:
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
                    {
                        "net_p": payload.net_p,
                        "net_n": payload.net_n,
                        "routed_lengths": dict(lengths),
                    }
                ],
                remediation=(
                    "Route both differential-pair nets, then rerun "
                    "si_check_differential_pair_skew()."
                ),
                failure_mode="configuration",
                metadata={"domain": "signal_integrity"},
            )

        height_mm = dielectric_height_provider()
        width_mm = track_width_provider(payload.net_p) or track_width_provider(payload.net_n) or 0.2
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
            budget_ps = skew_budget_ps
            budget_source = f"explicit budget {skew_budget_ps:.1f} ps"
        else:
            budget_ps, budget_source = budget_resolver(payload.net_p, payload.net_n)

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
