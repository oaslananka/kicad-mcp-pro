"""SPICE simulation tools backed by ngspice with optional InSpice support."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import Context
from mcp.server.mcpserver import MCPServer as FastMCP

from ..config import get_config
from ..models.simulation import (
    ACAnalysisInput,
    DCSweepInput,
    OperatingPointInput,
    SpiceDirectiveInput,
    SpiceLibraryEntry,
    SpiceModelAssignmentInput,
    StabilityCheckInput,
    TransientAnalysisInput,
)
from ..utils.ngspice import NgspiceRunner, SimulationResult, prepare_spice_netlist
from .export_support import _ensure_output_dir, _get_sch_file, _run_cli_variants
from .metadata import headless_compatible
from .schematic import update_symbol_property

DIRECTIVE_FILENAME = ".kicad_mcp_spice_directives.cir"
_ALLOWED_DIRECTIVE_PREFIXES = (
    ".param",
    ".include",
    ".options",
    ".model",
    ".ic",
    ".nodeset",
    ".ac",
    ".tran",
    ".dc",
    "*",
)


async def _report_progress(
    ctx: Context[Any, Any] | None,
    progress: float,
    total: float,
    message: str,
) -> None:
    if ctx is None:
        return
    try:
        await ctx.report_progress(progress, total, message)
    except ValueError:
        return


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


def _validate_spice_directive(directive: str) -> str:
    cleaned = directive.strip()
    lowered = cleaned.lower()
    if any(lowered.startswith(prefix) for prefix in _ALLOWED_DIRECTIVE_PREFIXES):
        return cleaned
    allowed = ", ".join(_ALLOWED_DIRECTIVE_PREFIXES)
    raise ValueError(
        "Unsupported SPICE directive prefix. "
        f"Expected one of: {allowed}. Received: {cleaned[:80]!r}"
    )


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
    candidate = cfg.resolve_within_project(raw_path, allow_absolute=False)
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
    @headless_compatible
    def sim_add_spice_directive(directive: str) -> str:
        """Persist a SPICE directive used by future MCP simulation runs."""
        payload = SpiceDirectiveInput(directive=directive)
        path = _persist_directive(_validate_spice_directive(payload.directive))
        count = len(_read_directives())
        return f"Stored simulation directive in {path} ({count} total directive(s))."

    @mcp.tool()
    @headless_compatible
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
    @headless_compatible
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
    @headless_compatible
    async def sim_run_transient(
        stop_time_s: float,
        step_time_s: float,
        probe_nets: list[str] | None = None,
        netlist_path: str = "",
        ctx: Context[Any, Any] | None = None,
    ) -> str:
        """Run a transient time-domain simulation."""
        payload = TransientAnalysisInput(
            stop_time_s=stop_time_s,
            step_time_s=step_time_s,
            probe_nets=probe_nets or [],
            netlist_path=netlist_path,
        )
        await _report_progress(ctx, 5, 100, "Preparing SPICE transient netlist...")
        prepared = _prepare_run_netlist(payload.netlist_path)
        await _report_progress(ctx, 35, 100, "Running ngspice transient analysis...")
        result = _runner().run_transient_analysis(
            prepared,
            _simulation_output_dir(),
            payload.probe_nets,
            stop_time_s=payload.stop_time_s,
            step_time_s=payload.step_time_s,
        )
        await _report_progress(ctx, 100, 100, "Transient analysis complete.")
        return _format_series_result("Transient analysis", result)

    @mcp.tool()
    @headless_compatible
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
    @headless_compatible
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

    # ── SPICE model assignment ──────────────────────────────────────────────

    @mcp.tool()
    @headless_compatible
    def sim_assign_spice_model(
        reference: str,
        model_name: str = "",
        library: str = "",
        model_type: str = "",
        pins: str = "",
        params: str = "",
    ) -> str:
        """Assign SPICE model properties to a component in the active schematic.

        Sets Sim.Name, Sim.Library, Sim.Type, Sim.Pins, and Sim.Params symbol
        properties.  Empty strings are skipped so you can update a single field
        without overwriting the others.
        """
        payload = SpiceModelAssignmentInput(
            reference=reference,
            model_name=model_name,
            library=library,
            model_type=model_type,
            pins=pins,
            params=params,
        )
        results: list[str] = []
        mapping = {
            "Sim.Name": payload.model_name,
            "Sim.Library": payload.library,
            "Sim.Type": payload.model_type,
            "Sim.Pins": payload.pins,
            "Sim.Params": payload.params,
        }
        for field, value in mapping.items():
            if not value:
                continue
            result = update_symbol_property(payload.reference, field, value)
            results.append(result)
        if not results:
            return (
                f"No fields were provided for {payload.reference}. "
                "Pass at least one of model_name, library, model_type, pins, or params."
            )
        return "\n".join(results)

    # ── SPICE library management ────────────────────────────────────────────

    def _read_project_json() -> dict[str, Any]:
        """Return the parsed .kicad_pro file as a dict."""
        cfg = get_config()
        if cfg.project_file is None or not cfg.project_file.exists():
            raise ValueError("No project file is configured. Call kicad_set_project() first.")
        try:
            raw = cfg.project_file.read_text(encoding="utf-8")
            payload: dict[str, Any] = json.loads(raw)
            return payload
        except json.JSONDecodeError as exc:
            raise ValueError(f"Project file '{cfg.project_file}' is not valid JSON.") from exc

    def _write_project_json(payload: dict[str, Any]) -> str:
        """Write the dict back to .kicad_pro and return a status message."""
        cfg = get_config()
        if cfg.project_file is None:
            raise ValueError("No project file is configured.")
        cfg.project_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return str(cfg.project_file)

    def _spice_libraries(
        payload: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Return the SPICE library entries from a project-file payload."""
        raw: list[dict[str, Any]] = payload.get("libraries", [])
        if not isinstance(raw, list):
            return []
        return [lib for lib in raw if lib.get("type") == "Spice"]

    @mcp.tool()
    @headless_compatible
    def sim_list_spice_libraries() -> str:
        """List SPICE model libraries registered in the active project."""
        payload = _read_project_json()
        libs = _spice_libraries(payload)
        if not libs:
            return "No SPICE libraries are configured in the active project."
        lines = [f"SPICE libraries ({len(libs)}):"]
        for entry in libs:
            lines.append(f"  - {entry.get('name', '(unnamed)')}: {entry.get('uri', '(no uri)')}")
        return "\n".join(lines)

    @mcp.tool()
    @headless_compatible
    def sim_add_spice_library(name: str, uri: str) -> str:
        """Register a SPICE model library in the active project file.

        Parameters
        ----------
        name : str
            Display / key name for the library entry.
        uri : str
            Path or URI to the SPICE model file.  Absolute paths, relative
            paths (resolved from the project directory), and KiCad environment
            variable references (e.g. ${KICAD_USER_LIB}) are all valid.
        """
        payload = SpiceLibraryEntry(name=name, uri=uri)
        project = _read_project_json()
        libraries: list[dict[str, Any]] = project.setdefault("libraries", [])
        if not isinstance(libraries, list):
            raise ValueError("The 'libraries' field in the project file must be an array.")

        for existing in libraries:
            if existing.get("name") == payload.name:
                return (
                    f"A library named '{payload.name}' already exists. "
                    f"Remove it first with sim_remove_spice_library() if you want to replace it."
                )

        libraries.append({"name": payload.name, "type": "Spice", "uri": payload.uri})
        saved = _write_project_json(project)
        return f"Added SPICE library '{payload.name}' -> {payload.uri}. Saved to {saved}."

    @mcp.tool()
    @headless_compatible
    def sim_remove_spice_library(name: str) -> str:
        """Unregister a SPICE model library from the active project file."""
        project = _read_project_json()
        libraries: list[dict[str, Any]] = project.get("libraries", [])
        if not isinstance(libraries, list):
            return "No SPICE libraries are configured in the active project."

        before = len(libraries)
        project["libraries"] = [lib for lib in libraries if lib.get("name") != name]
        after = len(project["libraries"])
        if before == after:
            return f"No SPICE library named '{name}' was found."

        _write_project_json(project)
        return f"Removed SPICE library '{name}'."

    @mcp.tool()
    @headless_compatible
    def sim_validate_spice_setup() -> str:
        """Check that registered SPICE libraries are resolvable from the project
        directory."""
        payload = _read_project_json()
        libs = _spice_libraries(payload)
        if not libs:
            return "No SPICE libraries are configured. Nothing to validate."

        cfg = get_config()
        project_dir = cfg.project_file.parent if cfg.project_file else Path.cwd()

        resolved_count = 0
        missing_count = 0
        lines = [f"SPICE library validation ({len(libs)} entries):"]
        for entry in libs:
            name = str(entry.get("name", "(unnamed)"))
            uri = str(entry.get("uri", ""))
            candidate = Path(uri)
            if not candidate.is_absolute():
                candidate = (project_dir / uri).resolve()
            exists = candidate.exists()
            status = "OK" if exists else "NOT FOUND"
            if exists:
                resolved_count += 1
            else:
                missing_count += 1
            lines.append(f"  {status}: {name} -> {candidate}")
        lines.append(f"Resolved: {resolved_count}, Missing: {missing_count}")
        return "\n".join(lines)
