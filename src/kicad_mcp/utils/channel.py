"""High-speed channel (insertion-loss / eye) analysis helpers (work order P3-T3).

Models a high-speed serial channel as a lossy transmission line. The closed-form path
sums the two physical attenuation mechanisms of a PCB trace -- conductor skin-effect loss
(grows as sqrt(f)) and dielectric loss (grows ~linearly with f) -- to get insertion loss
versus frequency, then derives a first-order loss-limited eye height at the Nyquist rate.

When an ngspice CLI is available, :func:`simulate_channel_insertion_loss` builds an RLGC
ladder of the same line and measures insertion loss with a real AC sweep, cross-checking
the closed-form figure. The honest method label (closed-form vs ngspice-measured) is
attached by the caller via the solver seam.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .ngspice import NgspiceRunner

C0_M_PER_S = 2.99792458e8
MU0_H_PER_M = 4.0e-7 * math.pi
COPPER_CONDUCTIVITY_S_PER_M = 5.8e7
NEPER_TO_DB = 8.685889638065035


@dataclass(frozen=True)
class ChannelSpec:
    """Physical description of a single-ended high-speed channel."""

    length_mm: float
    z0_ohm: float
    data_rate_gbps: float
    eps_eff: float = 3.8
    loss_tangent: float = 0.02
    trace_width_mm: float = 0.2
    conductivity_s_per_m: float = COPPER_CONDUCTIVITY_S_PER_M
    amplitude_v: float = 1.0

    def validate(self) -> None:
        """Raise ``ValueError`` if any physical parameter is non-physical."""
        if self.length_mm <= 0:
            raise ValueError("length_mm must be positive.")
        if self.z0_ohm <= 0:
            raise ValueError("z0_ohm must be positive.")
        if self.data_rate_gbps <= 0:
            raise ValueError("data_rate_gbps must be positive.")
        if self.eps_eff < 1.0:
            raise ValueError("eps_eff must be >= 1.0.")
        if self.loss_tangent < 0:
            raise ValueError("loss_tangent must be non-negative.")
        if self.trace_width_mm <= 0:
            raise ValueError("trace_width_mm must be positive.")
        if self.conductivity_s_per_m <= 0:
            raise ValueError("conductivity_s_per_m must be positive.")


@dataclass(frozen=True)
class ChannelMetrics:
    """Insertion-loss / eye metrics for a channel, with the method that produced them."""

    nyquist_hz: float
    insertion_loss_nyquist_db: float
    eye_height_v: float
    eye_height_ratio: float
    bandwidth_3db_hz: float
    source: str
    notes: list[str] = field(default_factory=list)


def conductor_attenuation_db_per_m(spec: ChannelSpec, freq_hz: float) -> float:
    """Skin-effect conductor attenuation (dB/m); grows as sqrt(frequency)."""
    if freq_hz <= 0:
        return 0.0
    surface_resistance = math.sqrt(math.pi * freq_hz * MU0_H_PER_M / spec.conductivity_s_per_m)
    width_m = spec.trace_width_mm / 1000.0
    alpha_np_per_m = surface_resistance / (spec.z0_ohm * width_m)
    return alpha_np_per_m * NEPER_TO_DB


def dielectric_attenuation_db_per_m(spec: ChannelSpec, freq_hz: float) -> float:
    """Dielectric (tan-delta) attenuation (dB/m); grows ~linearly with frequency."""
    if freq_hz <= 0:
        return 0.0
    alpha_np_per_m = math.pi * freq_hz * math.sqrt(spec.eps_eff) * spec.loss_tangent / C0_M_PER_S
    return alpha_np_per_m * NEPER_TO_DB


def insertion_loss_db(spec: ChannelSpec, freq_hz: float) -> float:
    """Total channel insertion loss (positive dB) at ``freq_hz`` over the line length."""
    length_m = spec.length_mm / 1000.0
    per_m = conductor_attenuation_db_per_m(spec, freq_hz) + dielectric_attenuation_db_per_m(
        spec, freq_hz
    )
    return per_m * length_m


def nyquist_frequency_hz(spec: ChannelSpec) -> float:
    """Nyquist frequency of the data rate (fundamental of a 1010 pattern)."""
    return spec.data_rate_gbps * 1e9 / 2.0


def bandwidth_3db_hz(spec: ChannelSpec, max_freq_hz: float | None = None) -> float:
    """Frequency at which insertion loss reaches 3 dB (monotonic; found by bisection)."""
    high = max_freq_hz if max_freq_hz is not None else max(nyquist_frequency_hz(spec) * 4.0, 1e9)
    if insertion_loss_db(spec, high) < 3.0:
        return high
    low = 0.0
    for _ in range(60):
        mid = 0.5 * (low + high)
        if insertion_loss_db(spec, mid) < 3.0:
            low = mid
        else:
            high = mid
    return 0.5 * (low + high)


def closed_form_channel_metrics(spec: ChannelSpec) -> ChannelMetrics:
    """Compute channel metrics from the closed-form lossy-line model."""
    spec.validate()
    f_nyquist = nyquist_frequency_hz(spec)
    il_db = insertion_loss_db(spec, f_nyquist)
    ratio = 10.0 ** (-il_db / 20.0)
    return ChannelMetrics(
        nyquist_hz=f_nyquist,
        insertion_loss_nyquist_db=il_db,
        eye_height_v=spec.amplitude_v * ratio,
        eye_height_ratio=ratio,
        bandwidth_3db_hz=bandwidth_3db_hz(spec),
        source="closed-form",
    )


def insertion_loss_from_ac(
    freqs_hz: list[float],
    mag_out: list[float],
    target_hz: float,
    *,
    reference_mag: float = 0.5,
) -> float:
    """Interpolate the AC magnitude at ``target_hz`` and return insertion loss (dB).

    ``reference_mag`` is the matched-through reference amplitude (0.5 for a source and
    load both equal to Z0 driven by a 1 V AC source). Loss is reported as a positive dB.
    """
    if not freqs_hz or not mag_out or len(freqs_hz) != len(mag_out):
        raise ValueError("freqs_hz and mag_out must be non-empty and the same length.")
    pairs = sorted(zip(freqs_hz, mag_out, strict=True), key=lambda item: item[0])
    if target_hz <= pairs[0][0]:
        magnitude = pairs[0][1]
    elif target_hz >= pairs[-1][0]:
        magnitude = pairs[-1][1]
    else:
        magnitude = pairs[-1][1]
        for (f_low, m_low), (f_high, m_high) in zip(pairs, pairs[1:], strict=False):
            if f_low <= target_hz <= f_high:
                span = f_high - f_low
                ratio = 0.0 if span == 0 else (target_hz - f_low) / span
                magnitude = m_low + (m_high - m_low) * ratio
                break
    if magnitude <= 0.0:
        return float("inf")
    return 20.0 * math.log10(reference_mag / magnitude)


def build_rlgc_ladder_deck(spec: ChannelSpec, segments: int = 20) -> str:
    """Build an ngspice RLGC-ladder AC deck for the channel, matched at both ends.

    The line is split into ``segments`` lumped R-L-G-C sections so an AC sweep measures a
    real distributed transfer function. Per-segment R and G are set from the conductor and
    dielectric attenuation at the Nyquist frequency, so the loss is exact at Nyquist and
    approximate elsewhere (constant per-segment RLGC does not reproduce the sqrt(f) /
    linear-f frequency dependence within one run).
    """
    spec.validate()
    segments = max(1, int(segments))
    length_m = spec.length_mm / 1000.0
    seg_len = length_m / segments
    f_nyquist = nyquist_frequency_hz(spec)
    velocity = C0_M_PER_S / math.sqrt(spec.eps_eff)
    l_pul = spec.z0_ohm / velocity
    c_pul = 1.0 / (spec.z0_ohm * velocity)
    alpha_c_np = conductor_attenuation_db_per_m(spec, f_nyquist) / NEPER_TO_DB
    alpha_d_np = dielectric_attenuation_db_per_m(spec, f_nyquist) / NEPER_TO_DB
    r_pul = 2.0 * spec.z0_ohm * alpha_c_np
    g_pul = 2.0 * alpha_d_np / spec.z0_ohm

    lines = [
        "* KiCad MCP Pro high-speed channel (RLGC ladder)",
        "Vin src 0 AC 1",
        f"Rsrc src n0 {spec.z0_ohm:.6g}",
    ]
    for index in range(segments):
        node_a = f"n{index}"
        node_b = f"n{index + 1}"
        mid = f"m{index}"
        lines.extend(
            [
                f"R{index} {node_a} {mid} {r_pul * seg_len:.6g}",
                f"L{index} {mid} {node_b} {l_pul * seg_len:.6g}",
                f"G{index} {node_b} 0 {node_b} 0 {g_pul * seg_len:.6g}",
                f"C{index} {node_b} 0 {c_pul * seg_len:.6g}",
            ]
        )
    lines.append(f"Rload n{segments} 0 {spec.z0_ohm:.6g}")
    lines.append(".end")
    return "\n".join(lines) + "\n"


def simulate_channel_insertion_loss(
    spec: ChannelSpec,
    runner: NgspiceRunner,
    output_dir: Path,
    *,
    segments: int = 20,
    points_per_decade: int = 30,
) -> ChannelMetrics | None:
    """Measure insertion loss with an ngspice AC sweep; return ``None`` on any failure.

    Falls back to ``None`` (so the caller keeps the closed-form result) if ngspice is not
    available or the run/parse fails, rather than raising.
    """
    spec.validate()
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        deck_path = output_dir / "channel_input.cir"
        deck_path.write_text(build_rlgc_ladder_deck(spec, segments), encoding="utf-8")
        f_nyquist = nyquist_frequency_hz(spec)
        out_node = f"n{max(1, int(segments))}"
        result = runner.run_ac_analysis(
            deck_path,
            output_dir,
            [out_node],
            start_freq_hz=max(f_nyquist / 1000.0, 1.0e3),
            stop_freq_hz=f_nyquist * 4.0,
            points_per_decade=points_per_decade,
        )
        trace = next(
            (item for item in result.traces if item.name.lower() == out_node.lower()),
            None,
        )
        if trace is None or not trace.values or not result.x_values:
            return None
        il_db = insertion_loss_from_ac(result.x_values, trace.values, f_nyquist)
        if not math.isfinite(il_db):
            return None
        ratio = 10.0 ** (-il_db / 20.0)
        return ChannelMetrics(
            nyquist_hz=f_nyquist,
            insertion_loss_nyquist_db=il_db,
            eye_height_v=spec.amplitude_v * ratio,
            eye_height_ratio=ratio,
            bandwidth_3db_hz=bandwidth_3db_hz(spec),
            source="ngspice",
            notes=[f"Measured from a {segments}-segment RLGC AC sweep ({result.backend})."],
        )
    except (OSError, ValueError, RuntimeError):
        return None
