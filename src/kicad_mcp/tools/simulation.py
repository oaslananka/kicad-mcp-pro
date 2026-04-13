"""SPICE simulation tools backed by InSpice and ngspice."""

from __future__ import annotations

import math
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from ..config import get_config
from ..models.simulation import (
    ACAnalysisInput,
    DCSweepInput,
    OperatingPointInput,
    SpiceDirectiveInput,
    StabilityCheckInput,
    TransientAnalysisInput,
)
from ..utils.ngspice import NgspiceRunner, SimulationResult, prepare_spice_netlist
from .export import _ensure_output_dir, _get_sch_file, _run_cli_variants

DIRECTIVE_FILENAME = ".kicad_mcp_spice_directives.cir"


def _simulation_output_dir() -> Path:
    return _ensure_output_dir("simulation")


def _directive_file() -> Path:
    return get_config().project_root / DIRECTIVE_FILENAME


def _read_directives() -> list[str]:
    path = _directive_file()
    if not path.exists():
        return []
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _persist_directive(directive: str) -> Path:
    path = _directive_file()
    existing = _read_directives()
    if directive not in existing:
        lines = [*existing, directive]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _export_spice_netlist_file() -> Path:
    sch_file = _get_sch_file()
    out_file = _simulation_output_dir() / "exported_netlist.cir"
    code, _, stderr = _run_cli_variants(
        [
            [
                "sch",
                "export",
                "netlist",
                "--format",
                "spice",
                "--output",
                str(out_file),
                str(sch_file),
            ]
        ]
    )
    if code != 0 or not out_file.exists():
        raise RuntimeError(f"SPICE netlist export failed: {stderr or 'unknown error'}")
    return out_file


def _resolve_netlist_path(raw_path: str) -> Path:
    cfg = get_config()
    if not raw_path:
        return _export_spice_netlist_file()
    candidate = cfg.resolve_within_project(raw_path, allow_absolute=True)
    if not candidate.exists():
        raise FileNotFoundError(f"SPICE netlist file was not found: {candidate}")
    return candidate


def _runner() -> NgspiceRunner:
    cfg = get_config()
    return NgspiceRunner(cfg.ngspice_cli, cfg.cli_timeout)


def _format_result_header(title: str, result: SimulationResult) -> list[str]:
    lines = [f"{title} ({result.backend}):", f"- Netlist: {result.netlist_path}"]
    if result.log_path is not None:
        lines.append(f"- Log: {result.log_path}")
    if result.data_path is not None:
        lines.append(f"- Data: {result.data_path}")
    if result.raw_path is not None:
        lines.append(f"- Raw: {result.raw_path}")
    return lines


def _format_operating_point(result: SimulationResult) -> str:
    lines = _format_result_header("Operating point analysis", result)
    if not result.traces:
        lines.append("No node or branch data was returned.")
        return "\n".join(lines)

    lines.append(f"- Scalars: {len(result.traces)}")
    lines.append("Values:")
    for trace in result.traces[: get_config().max_items_per_response]:
        value = trace.values[-1] if trace.values else 0.0
        lines.append(f"- {trace.name}: {value:.6g}")
    return "\n".join(lines)


def _format_series_result(title: str, result: SimulationResult) -> str:
    lines = _format_result_header(title, result)
    point_count = len(result.x_values)
    lines.append(f"- Samples: {point_count}")
    if result.x_label and result.x_values:
        lines.append(f"- {result.x_label}: {result.x_values[0]:.6g} -> {result.x_values[-1]:.6g}")
    if not result.traces:
        lines.append("No waveform data was returned.")
        return "\n".join(lines)

    lines.append("Waveforms:")
    for trace in result.traces[: get_config().max_items_per_response]:
        first = trace.values[0] if trace.values else 0.0
        last = trace.values[-1] if trace.values else 0.0
        detail = f"- {trace.name}: {first:.6g} -> {last:.6g}"
        if trace.phase_values:
            detail += f", phase {trace.phase_values[0]:.3f} -> {trace.phase_values[-1]:.3f} deg"
        lines.append(detail)
    return "\n".join(lines)


def _prepare_run_netlist(netlist_path: str) -> Path:
    base = _resolve_netlist_path(netlist_path)
    return prepare_spice_netlist(base, _simulation_output_dir(), _read_directives())


def _interpolate_zero_crossing(x1: float, x2: float, y1: float, y2: float) -> float:
    if math.isclose(y1, y2):
        return x1
    ratio = (0.0 - y1) / (y2 - y1)
    return x1 + ((x2 - x1) * ratio)


def _interpolate_value(x1: float, x2: float, y1: float, y2: float, target_x: float) -> float:
    if math.isclose(x1, x2):
        return y1
    ratio = (target_x - x1) / (x2 - x1)
    return y1 + ((y2 - y1) * ratio)


def _normalize_loop_phase(phase_deg: float) -> float:
    normalized = phase_deg
    while normalized > 0.0:
        normalized -= 360.0
    while normalized <= -360.0:
        normalized += 360.0
    return normalized


def _format_stability(result: SimulationResult, output_net: str, feedback_net: str) -> str:
    lines = _format_result_header("Stability check", result)
    traces = {trace.name.lower(): trace for trace in result.traces}
    output_trace = traces.get(output_net.lower())
    feedback_trace = traces.get(feedback_net.lower())
    if output_trace is None or feedback_trace is None:
        lines.append(
            f"Could not find both AC traces for '{output_net}' and '{feedback_net}' in the result."
        )
        return "\n".join(lines)

    if not output_trace.phase_values or not feedback_trace.phase_values:
        lines.append("Phase data was unavailable, so phase margin could not be estimated.")
        return "\n".join(lines)

    gain_db: list[float] = []
    phase_deg: list[float] = []
    for out_mag, fb_mag, out_phase, fb_phase in zip(
        output_trace.values,
        feedback_trace.values,
        output_trace.phase_values,
        feedback_trace.phase_values,
        strict=False,
    ):
        if fb_mag <= 0.0:
            gain_db.append(float("inf"))
        else:
            gain_db.append(20.0 * math.log10(out_mag / fb_mag))
        phase_deg.append(_normalize_loop_phase(out_phase - fb_phase))

    crossover_index: int | None = None
    for index in range(1, len(gain_db)):
        previous = gain_db[index - 1]
        current = gain_db[index]
        if (previous >= 0.0 >= current) or (previous <= 0.0 <= current):
            crossover_index = index
            break

    lines.append(f"- Loop samples: {len(result.x_values)}")
    if crossover_index is None or len(result.x_values) < 2:
        lines.append(
            "No unity-gain crossover was found in the sampled band, so phase margin is unavailable."
        )
        if gain_db:
            lines.append(f"- Loop gain range: {min(gain_db):.3f} dB -> {max(gain_db):.3f} dB")
        return "\n".join(lines)

    crossover_freq = _interpolate_zero_crossing(
        result.x_values[crossover_index - 1],
        result.x_values[crossover_index],
        gain_db[crossover_index - 1],
        gain_db[crossover_index],
    )
    crossover_phase = _interpolate_value(
        result.x_values[crossover_index - 1],
        result.x_values[crossover_index],
        phase_deg[crossover_index - 1],
        phase_deg[crossover_index],
        crossover_freq,
    )
    phase_margin = 180.0 + crossover_phase
    lines.extend(
        [
            f"- Unity-gain crossover: {crossover_freq:.6g} Hz",
            f"- Loop phase at crossover: {crossover_phase:.3f} deg",
            f"- Estimated phase margin: {phase_margin:.3f} deg",
        ]
    )
    return "\n".join(lines)


def register(mcp: FastMCP) -> None:
    """Register simulation tools."""

    @mcp.tool()
    def sim_add_spice_directive(directive: str) -> str:
        """Persist a SPICE directive used by future MCP simulation runs."""
        payload = SpiceDirectiveInput(directive=directive)
        path = _persist_directive(payload.directive.strip())
        count = len(_read_directives())
        return f"Stored simulation directive in {path} ({count} total directive(s))."

    @mcp.tool()
    def sim_run_operating_point(netlist_path: str = "", probe_nets: list[str] | None = None) -> str:
        """Run a DC operating-point analysis."""
        payload = OperatingPointInput(netlist_path=netlist_path, probe_nets=probe_nets or [])
        prepared = _prepare_run_netlist(payload.netlist_path)
        result = _runner().run_operating_point(
            prepared,
            _simulation_output_dir(),
            payload.probe_nets,
        )
        return _format_operating_point(result)

    @mcp.tool()
    def sim_run_ac_analysis(
        start_freq_hz: float,
        stop_freq_hz: float,
        points_per_decade: int = 20,
        probe_nets: list[str] | None = None,
        netlist_path: str = "",
    ) -> str:
        """Run a small-signal AC sweep."""
        payload = ACAnalysisInput(
            start_freq_hz=start_freq_hz,
            stop_freq_hz=stop_freq_hz,
            points_per_decade=points_per_decade,
            probe_nets=probe_nets or [],
            netlist_path=netlist_path,
        )
        prepared = _prepare_run_netlist(payload.netlist_path)
        result = _runner().run_ac_analysis(
            prepared,
            _simulation_output_dir(),
            payload.probe_nets,
            start_freq_hz=payload.start_freq_hz,
            stop_freq_hz=payload.stop_freq_hz,
            points_per_decade=payload.points_per_decade,
        )
        return _format_series_result("AC analysis", result)

    @mcp.tool()
    def sim_run_transient(
        stop_time_s: float,
        step_time_s: float,
        probe_nets: list[str] | None = None,
        netlist_path: str = "",
    ) -> str:
        """Run a transient time-domain simulation."""
        payload = TransientAnalysisInput(
            stop_time_s=stop_time_s,
            step_time_s=step_time_s,
            probe_nets=probe_nets or [],
            netlist_path=netlist_path,
        )
        prepared = _prepare_run_netlist(payload.netlist_path)
        result = _runner().run_transient_analysis(
            prepared,
            _simulation_output_dir(),
            payload.probe_nets,
            stop_time_s=payload.stop_time_s,
            step_time_s=payload.step_time_s,
        )
        return _format_series_result("Transient analysis", result)

    @mcp.tool()
    def sim_run_dc_sweep(
        source_ref: str,
        start_v: float,
        stop_v: float,
        step_v: float,
        probe_nets: list[str] | None = None,
        netlist_path: str = "",
    ) -> str:
        """Run a DC sweep for an independent source."""
        payload = DCSweepInput(
            source_ref=source_ref,
            start_v=start_v,
            stop_v=stop_v,
            step_v=step_v,
            probe_nets=probe_nets or [],
            netlist_path=netlist_path,
        )
        prepared = _prepare_run_netlist(payload.netlist_path)
        result = _runner().run_dc_sweep(
            prepared,
            _simulation_output_dir(),
            payload.probe_nets,
            source_ref=payload.source_ref,
            start_v=payload.start_v,
            stop_v=payload.stop_v,
            step_v=payload.step_v,
        )
        return _format_series_result("DC sweep analysis", result)

    @mcp.tool()
    def sim_check_stability(
        output_net: str,
        feedback_net: str,
        start_freq_hz: float = 10.0,
        stop_freq_hz: float = 1.0e7,
        points_per_decade: int = 20,
        netlist_path: str = "",
    ) -> str:
        """Estimate loop crossover and phase margin from an AC sweep."""
        payload = StabilityCheckInput(
            output_net=output_net,
            feedback_net=feedback_net,
            start_freq_hz=start_freq_hz,
            stop_freq_hz=stop_freq_hz,
            points_per_decade=points_per_decade,
            netlist_path=netlist_path,
        )
        prepared = _prepare_run_netlist(payload.netlist_path)
        result = _runner().run_ac_analysis(
            prepared,
            _simulation_output_dir(),
            [payload.output_net, payload.feedback_net],
            start_freq_hz=payload.start_freq_hz,
            stop_freq_hz=payload.stop_freq_hz,
            points_per_decade=payload.points_per_decade,
        )
        return _format_stability(result, payload.output_net, payload.feedback_net)
