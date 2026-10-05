"""FastMCP-independent time-domain routing-tuning service."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ..utils.impedance import (
    TraceType,
    propagation_delay_ps_per_mm,
    solve_width_for_impedance,
    trace_impedance,
)
from ..utils.sexpr import _sexpr_string
from .tuning_profiles import load_tuning_profiles

ProjectDirProvider = Callable[[], Path | None]
PatternTrackLengthProvider = Callable[[str], float]
StackupContextProvider = Callable[[str], tuple[TraceType, float, float, float]]
RuleWriter = Callable[[str, str], Path]

_WILDCARD_UNSUPPORTED = (
    "Wildcard/group time-domain tuning is not supported because KiCad length "
    "constraints apply per net. Specify a single concrete net name."
)


def _mm(value: float) -> str:
    return f"{value:.4f}mm"


def delay_to_length_mm(delay_ps: float, propagation_speed_factor: float) -> float:
    """Convert propagation delay in ps to trace length in mm."""
    return delay_ps * 0.299792458 * propagation_speed_factor


def net_pattern_condition(net_pattern: str) -> str:
    """Render a KiCad rule condition for one concrete net."""
    if any(char in net_pattern for char in "*?"):
        raise ValueError(_WILDCARD_UNSUPPORTED)
    return f"A.NetName == '{net_pattern}'"


def build_time_domain_rule(
    net_or_group: str,
    target_delay_ps: float,
    tolerance_ps: float,
    target_mm: float,
    tolerance_mm: float,
) -> tuple[str, str]:
    """Build the legacy time-domain .kicad_dru rule body."""
    rule_name = f"Time-domain tune {net_or_group}"
    condition = net_pattern_condition(net_or_group)
    rule_body = "\n".join(
        [
            f"(rule {_sexpr_string(rule_name)}",
            f'  (condition "{condition}")',
            f"  (constraint length (min {_mm(max(target_mm - tolerance_mm, 0.0))}) "
            f"(opt {_mm(target_mm)}) (max {_mm(target_mm + tolerance_mm)}))",
            f"  (constraint delay (min {max(target_delay_ps - tolerance_ps, 0.0):.3f}ps) "
            f"(opt {target_delay_ps:.3f}ps) (max {target_delay_ps + tolerance_ps:.3f}ps))",
            ")",
        ]
    )
    return rule_name, rule_body


@dataclass(frozen=True)
class RoutingTimeDomainTuningService:
    """Write time-domain tuning constraints without depending on FastMCP."""

    get_project_dir: ProjectDirProvider
    current_track_length_for_pattern_mm: PatternTrackLengthProvider
    stackup_context_for_layer: StackupContextProvider
    write_rule: RuleWriter

    def tune(
        self,
        net_or_group: str,
        target_delay_ps: float,
        tolerance_ps: float = 10.0,
        layer: str | None = None,
    ) -> str:
        if any(char in net_or_group for char in "*?"):
            return _WILDCARD_UNSUPPORTED

        profiles = load_tuning_profiles(self.get_project_dir())
        propagation_speed_factor = 0.5
        profile_impedance_ohm = 50.0
        effective_er: float | None = None

        if layer:
            matching = next(
                (
                    item
                    for item in profiles.values()
                    if str(item.get("layer", "")).casefold() == layer.casefold()
                ),
                None,
            )
            if matching is not None:
                raw_factor = matching.get(
                    "propagation_speed_factor",
                    propagation_speed_factor,
                )
                if isinstance(raw_factor, int | float):
                    propagation_speed_factor = float(raw_factor)
                raw_impedance = matching.get(
                    "trace_impedance_ohm",
                    profile_impedance_ohm,
                )
                if isinstance(raw_impedance, int | float):
                    profile_impedance_ohm = float(raw_impedance)

        if layer:
            try:
                trace_type, height_mm, er, copper_oz = self.stackup_context_for_layer(layer)
                solved_width_mm = solve_width_for_impedance(
                    profile_impedance_ohm,
                    height_mm,
                    er,
                    trace_type=trace_type,
                    copper_oz=copper_oz,
                )
                _, effective_er = trace_impedance(
                    solved_width_mm,
                    height_mm,
                    er,
                    trace_type=trace_type,
                    copper_oz=copper_oz,
                )
                delay_ps_per_mm = propagation_delay_ps_per_mm(effective_er)
                target_mm = target_delay_ps / delay_ps_per_mm
                tolerance_mm = tolerance_ps / delay_ps_per_mm
            except ValueError:
                target_mm = delay_to_length_mm(
                    target_delay_ps,
                    propagation_speed_factor,
                )
                tolerance_mm = delay_to_length_mm(
                    tolerance_ps,
                    propagation_speed_factor,
                )
        else:
            target_mm = delay_to_length_mm(
                target_delay_ps,
                propagation_speed_factor,
            )
            tolerance_mm = delay_to_length_mm(
                tolerance_ps,
                propagation_speed_factor,
            )

        current_length = self.current_track_length_for_pattern_mm(net_or_group)
        required_extension = target_mm - current_length
        rule_name, rule_body = build_time_domain_rule(
            net_or_group,
            target_delay_ps,
            tolerance_ps,
            target_mm,
            tolerance_mm,
        )
        try:
            path = self.write_rule(rule_name, rule_body)
        except (OSError, ValueError) as exc:
            return f"Time-domain tuning rule update failed: {exc}"

        lines = [
            f"Time-domain tuning rule '{rule_name}' written to {path}.",
            f"Target delay: {target_delay_ps:.3f} ps",
            f"Tolerance: {tolerance_ps:.3f} ps",
            f"Current measured length: {current_length:.3f} mm",
            f"Computed target length: {target_mm:.3f} mm",
            f"Required extension: {required_extension:.3f} mm",
        ]
        if layer:
            lines.append(f"Layer: {layer}")
        if effective_er is not None:
            lines.append(f"Effective dielectric constant: {effective_er:.4f}")
        else:
            lines.append(f"Fallback target length: {target_mm:.3f} mm")
        return "\n".join(lines)
