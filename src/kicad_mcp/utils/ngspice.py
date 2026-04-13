"""Simulation helpers backed by InSpice and ngspice CLI."""

from __future__ import annotations

import importlib
import math
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any, Literal, Protocol, cast

import structlog

logger = structlog.get_logger(__name__)

SimulationBackend = Literal["inspice", "ngspice-cli"]
SimulationKind = Literal["operating-point", "ac", "transient", "dc"]


@dataclass(slots=True)
class SimulationTrace:
    """One simulated waveform or scalar result."""

    name: str
    values: list[float]
    phase_values: list[float] | None = None


@dataclass(slots=True)
class SimulationResult:
    """Normalized simulation output independent of the backend."""

    backend: SimulationBackend
    analysis: SimulationKind
    netlist_path: Path
    log_path: Path | None = None
    raw_path: Path | None = None
    data_path: Path | None = None
    x_label: str | None = None
    x_values: list[float] = field(default_factory=list)
    traces: list[SimulationTrace] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


class _OperatingPointLike(Protocol):
    nodes: dict[str, object]
    branches: dict[str, object]


class _AcAnalysisLike(_OperatingPointLike, Protocol):
    frequency: object


class _TransientAnalysisLike(_OperatingPointLike, Protocol):
    time: object


class _DcAnalysisLike(_OperatingPointLike, Protocol):
    sweep: object


def discover_ngspice_cli(configured: Path | None = None) -> Path | None:
    """Discover an ngspice executable on the host system."""
    candidates: list[Path] = []
    if configured is not None:
        candidates.append(configured.expanduser())

    which_path = shutil.which("ngspice")
    if which_path is not None:
        candidates.append(Path(which_path))

    candidates.extend(
        [
            Path(r"C:\Program Files\KiCad\10.0\bin\ngspice.exe"),
            Path(r"C:\Program Files\KiCad\9.0\bin\ngspice.exe"),
            Path("/usr/bin/ngspice"),
            Path("/usr/local/bin/ngspice"),
            Path("/Applications/KiCad/KiCad.app/Contents/MacOS/ngspice"),
        ]
    )

    for candidate in candidates:
        resolved = candidate.expanduser()
        if resolved.exists():
            return resolved
    return None


def prepare_spice_netlist(
    netlist_path: Path,
    output_dir: Path,
    directives: list[str] | tuple[str, ...] | None = None,
) -> Path:
    """Create a simulation-ready copy of a SPICE deck with optional MCP directives."""
    directives = [directive.strip() for directive in directives or () if directive.strip()]
    output_dir.mkdir(parents=True, exist_ok=True)
    content = netlist_path.read_text(encoding="utf-8", errors="ignore")
    if not directives:
        prepared = output_dir / "simulation_input.cir"
        prepared.write_text(content, encoding="utf-8")
        return prepared

    trimmed = _strip_spice_end(content)
    directive_block = "\n".join(directives)
    merged = f"{trimmed}\n* Added by KiCad MCP Pro simulation tools\n{directive_block}\n.end\n"
    prepared = output_dir / "simulation_input.cir"
    prepared.write_text(merged, encoding="utf-8")
    return prepared


def _strip_spice_end(content: str) -> str:
    lines = content.rstrip().splitlines()
    while lines and not lines[-1].strip():
        lines.pop()
    if lines and lines[-1].strip().lower() == ".end":
        lines.pop()
    return "\n".join(lines)


def _optional_numpy() -> ModuleType | None:
    try:
        return importlib.import_module("numpy")
    except Exception:
        return None


def _import_inspice_modules() -> dict[str, Any] | None:
    try:
        parser = importlib.import_module("InSpice.Spice.Parser")
        translator = importlib.import_module("InSpice.Spice.Parser.Translator")
        simulator_mod = importlib.import_module("InSpice.Spice.Simulator")
    except Exception as exc:
        logger.debug("inspice_import_failed", error=str(exc))
        return None

    return {
        "SpiceFile": parser.SpiceFile,
        "Builder": translator.Builder,
        "Simulator": simulator_mod.Simulator,
    }


def _as_real_list(values: object) -> list[float]:
    numpy = _optional_numpy()
    if numpy is not None:
        array = numpy.asarray(values)
        if array.ndim == 0:
            return [float(array.item())]
        return [float(item) for item in array.tolist()]
    if isinstance(values, (int, float)):
        return [float(values)]
    if isinstance(values, complex):
        return [float(values.real)]
    if isinstance(values, list):
        return [float(cast(float, item)) for item in values]
    if isinstance(values, tuple):
        return [float(cast(float, item)) for item in values]
    try:
        return [float(item) for item in cast(Any, values)]
    except TypeError:
        return [float(cast(float, values))]


def _as_complex_list(values: object) -> list[complex]:
    numpy = _optional_numpy()
    if numpy is not None:
        array = numpy.asarray(values)
        if array.ndim == 0:
            return [complex(array.item())]
        return [complex(item) for item in array.tolist()]
    if isinstance(values, complex):
        return [values]
    if isinstance(values, (int, float)):
        return [complex(float(values), 0.0)]
    if isinstance(values, list):
        return [complex(item) for item in values]
    if isinstance(values, tuple):
        return [complex(item) for item in values]
    try:
        return [complex(item) for item in cast(Any, values)]
    except TypeError:
        return [complex(cast(complex, values))]


def _waveform_name(raw_name: str) -> str:
    lowered = raw_name.strip().lower()
    if lowered.startswith("v(") and lowered.endswith(")"):
        return raw_name.strip()[2:-1]
    if lowered.startswith("vm(") and lowered.endswith(")"):
        return raw_name.strip()[3:-1]
    if lowered.startswith("vp(") and lowered.endswith(")"):
        return raw_name.strip()[3:-1]
    return raw_name.strip()


def _parse_wrdata_table(data_path: Path) -> tuple[list[str], list[list[float]]]:
    lines = [
        line.strip()
        for line in data_path.read_text(encoding="utf-8", errors="ignore").splitlines()
        if line.strip() and not line.lstrip().startswith("*")
    ]
    if not lines:
        raise ValueError(f"ngspice produced an empty data file: {data_path}")

    first_tokens = lines[0].split()
    has_header = any(not _is_float(token) for token in first_tokens)
    header = first_tokens if has_header else [f"col_{index}" for index in range(len(first_tokens))]
    data_lines = lines[1:] if has_header else lines

    rows: list[list[float]] = []
    for line in data_lines:
        tokens = line.split()
        numeric = [float(token) for token in tokens if _is_float(token)]
        if numeric:
            rows.append(numeric)

    if not rows:
        raise ValueError(f"ngspice did not emit numeric data rows in {data_path}")
    return header, rows


def _is_float(token: str) -> bool:
    try:
        float(token)
    except ValueError:
        return False
    return True


class NgspiceRunner:
    """Run simulations through InSpice when possible and fall back to ngspice CLI."""

    def __init__(self, ngspice_cli: Path | None = None, cli_timeout: float = 120.0) -> None:
        self._configured_cli = ngspice_cli
        self._cli_timeout = cli_timeout

    def resolve_cli(self) -> Path:
        """Return the resolved ngspice CLI path or raise an actionable error."""
        cli = discover_ngspice_cli(self._configured_cli)
        if cli is None:
            raise FileNotFoundError(
                "ngspice is not available. Install KiCad/ngspice or set "
                "KICAD_MCP_NGSPICE_CLI to a valid executable."
            )
        return cli

    def run_operating_point(
        self,
        netlist_path: Path,
        output_dir: Path,
        probe_nets: list[str],
    ) -> SimulationResult:
        """Run an operating-point analysis."""
        return self._run("operating-point", netlist_path, output_dir, probe_nets)

    def run_ac_analysis(
        self,
        netlist_path: Path,
        output_dir: Path,
        probe_nets: list[str],
        *,
        start_freq_hz: float,
        stop_freq_hz: float,
        points_per_decade: int,
    ) -> SimulationResult:
        """Run a small-signal AC analysis."""
        return self._run(
            "ac",
            netlist_path,
            output_dir,
            probe_nets,
            start_freq_hz=start_freq_hz,
            stop_freq_hz=stop_freq_hz,
            points_per_decade=points_per_decade,
        )

    def run_transient_analysis(
        self,
        netlist_path: Path,
        output_dir: Path,
        probe_nets: list[str],
        *,
        stop_time_s: float,
        step_time_s: float,
    ) -> SimulationResult:
        """Run a transient analysis."""
        return self._run(
            "transient",
            netlist_path,
            output_dir,
            probe_nets,
            stop_time_s=stop_time_s,
            step_time_s=step_time_s,
        )

    def run_dc_sweep(
        self,
        netlist_path: Path,
        output_dir: Path,
        probe_nets: list[str],
        *,
        source_ref: str,
        start_v: float,
        stop_v: float,
        step_v: float,
    ) -> SimulationResult:
        """Run a DC sweep analysis."""
        return self._run(
            "dc",
            netlist_path,
            output_dir,
            probe_nets,
            source_ref=source_ref,
            start_v=start_v,
            stop_v=stop_v,
            step_v=step_v,
        )

    def _run(
        self,
        analysis: SimulationKind,
        netlist_path: Path,
        output_dir: Path,
        probe_nets: list[str],
        **kwargs: float | int | str,
    ) -> SimulationResult:
        modules = _import_inspice_modules()
        if modules is not None:
            try:
                return self._run_inspice(
                    modules,
                    analysis,
                    netlist_path,
                    probe_nets,
                    **kwargs,
                )
            except Exception as exc:
                logger.warning(
                    "simulation_inspice_fallback_to_cli",
                    analysis=analysis,
                    error=str(exc),
                )

        return self._run_cli(analysis, netlist_path, output_dir, probe_nets, **kwargs)

    def _run_inspice(
        self,
        modules: dict[str, Any],
        analysis: SimulationKind,
        netlist_path: Path,
        probe_nets: list[str],
        **kwargs: float | int | str,
    ) -> SimulationResult:
        cli = self.resolve_cli()
        spice_file = modules["SpiceFile"](path=netlist_path)
        circuit = modules["Builder"]().translate(spice_file)
        simulator = modules["Simulator"].factory(
            simulator="ngspice-subprocess",
            spice_command=str(cli),
        )
        simulation = simulator.simulation(circuit)
        probe_args = tuple(probe_nets)
        call_kwargs: dict[str, Any] = {}
        if probe_args:
            call_kwargs["probes"] = probe_args

        if analysis == "operating-point":
            analysis_obj = simulation.operating_point(**call_kwargs)
        elif analysis == "ac":
            analysis_obj = simulation.ac(
                variation="dec",
                number_of_points=int(kwargs["points_per_decade"]),
                start_frequency=float(kwargs["start_freq_hz"]),
                stop_frequency=float(kwargs["stop_freq_hz"]),
                **call_kwargs,
            )
        elif analysis == "transient":
            analysis_obj = simulation.transient(
                step_time=float(kwargs["step_time_s"]),
                end_time=float(kwargs["stop_time_s"]),
                **call_kwargs,
            )
        elif analysis == "dc":
            analysis_obj = simulation.dc(
                **{str(kwargs["source_ref"]): slice(
                    float(kwargs["start_v"]),
                    float(kwargs["stop_v"]),
                    float(kwargs["step_v"]),
                )},
                **call_kwargs,
            )
        else:
            raise ValueError(f"Unsupported simulation analysis '{analysis}'.")

        return self._result_from_inspice(analysis, netlist_path, analysis_obj)

    def _result_from_inspice(
        self,
        analysis: SimulationKind,
        netlist_path: Path,
        analysis_obj: object,
    ) -> SimulationResult:
        if analysis == "operating-point":
            op_analysis = cast(_OperatingPointLike, analysis_obj)
            traces = [
                SimulationTrace(name=str(name), values=_as_real_list(waveform))
                for name, waveform in sorted(op_analysis.nodes.items())
            ]
            traces.extend(
                SimulationTrace(name=str(name), values=_as_real_list(waveform))
                for name, waveform in sorted(op_analysis.branches.items())
            )
            return SimulationResult(
                backend="inspice",
                analysis=analysis,
                netlist_path=netlist_path,
                traces=traces,
            )

        if analysis == "ac":
            ac_analysis = cast(_AcAnalysisLike, analysis_obj)
            traces = []
            for name, waveform in sorted(ac_analysis.nodes.items()):
                complex_values = _as_complex_list(waveform)
                traces.append(
                    SimulationTrace(
                        name=str(name),
                        values=[abs(value) for value in complex_values],
                        phase_values=[
                            math.degrees(math.atan2(value.imag, value.real))
                            for value in complex_values
                        ],
                    )
                )
            return SimulationResult(
                backend="inspice",
                analysis=analysis,
                netlist_path=netlist_path,
                x_label="frequency",
                x_values=_as_real_list(ac_analysis.frequency),
                traces=traces,
            )

        if analysis == "transient":
            transient_analysis = cast(_TransientAnalysisLike, analysis_obj)
            traces = [
                SimulationTrace(name=str(name), values=_as_real_list(waveform))
                for name, waveform in sorted(transient_analysis.nodes.items())
            ]
            return SimulationResult(
                backend="inspice",
                analysis=analysis,
                netlist_path=netlist_path,
                x_label="time",
                x_values=_as_real_list(transient_analysis.time),
                traces=traces,
            )

        dc_analysis = cast(_DcAnalysisLike, analysis_obj)
        traces = [
            SimulationTrace(name=str(name), values=_as_real_list(waveform))
            for name, waveform in sorted(dc_analysis.nodes.items())
        ]
        return SimulationResult(
            backend="inspice",
            analysis=analysis,
            netlist_path=netlist_path,
            x_label="sweep",
            x_values=_as_real_list(dc_analysis.sweep),
            traces=traces,
        )

    def _run_cli(
        self,
        analysis: SimulationKind,
        netlist_path: Path,
        output_dir: Path,
        probe_nets: list[str],
        **kwargs: float | int | str,
    ) -> SimulationResult:
        cli = self.resolve_cli()
        output_dir.mkdir(parents=True, exist_ok=True)
        data_path = output_dir / f"{analysis.replace('-', '_')}.data"
        raw_path = output_dir / f"{analysis.replace('-', '_')}.raw"
        log_path = output_dir / f"{analysis.replace('-', '_')}.log"
        deck_path = output_dir / f"{analysis.replace('-', '_')}.cir"
        deck_text = self._build_cli_deck(
            analysis,
            netlist_path.read_text(encoding="utf-8", errors="ignore"),
            data_path,
            raw_path,
            probe_nets,
            **kwargs,
        )
        deck_path.write_text(deck_text, encoding="utf-8")

        result = subprocess.run(
            [str(cli), "-b", "-o", str(log_path), str(deck_path)],
            capture_output=True,
            text=True,
            timeout=self._cli_timeout,
            check=False,
        )
        if result.returncode != 0 and not data_path.exists():
            stderr = (result.stderr or "").strip()
            stdout = (result.stdout or "").strip()
            detail = stderr or stdout or f"ngspice exited with code {result.returncode}"
            raise RuntimeError(f"ngspice {analysis} analysis failed: {detail}")

        header, rows = _parse_wrdata_table(data_path)
        return self._result_from_wrdata(
            analysis,
            netlist_path,
            data_path,
            raw_path if raw_path.exists() else None,
            log_path if log_path.exists() else None,
            header,
            rows,
        )

    def _build_cli_deck(
        self,
        analysis: SimulationKind,
        base_netlist: str,
        data_path: Path,
        raw_path: Path,
        probe_nets: list[str],
        **kwargs: float | int | str,
    ) -> str:
        probe_nets = [probe for probe in probe_nets if probe.strip()]
        header_exprs: list[str]
        if analysis == "operating-point":
            header_exprs = [f"v({probe})" for probe in probe_nets] or ["all"]
            analysis_cmd = "op"
        elif analysis == "ac":
            header_exprs = ["frequency"]
            for probe in probe_nets:
                header_exprs.extend([f"vm({probe})", f"vp({probe})"])
            analysis_cmd = (
                f"ac dec {int(kwargs['points_per_decade'])} "
                f"{float(kwargs['start_freq_hz'])} {float(kwargs['stop_freq_hz'])}"
            )
        elif analysis == "transient":
            header_exprs = ["time", *[f"v({probe})" for probe in probe_nets]]
            analysis_cmd = f"tran {float(kwargs['step_time_s'])} {float(kwargs['stop_time_s'])}"
        elif analysis == "dc":
            header_exprs = (
                ["all"]
                if not probe_nets
                else ["v(v-sweep)", *[f"v({probe})" for probe in probe_nets]]
            )
            analysis_cmd = (
                f"dc {kwargs['source_ref']} "
                f"{float(kwargs['start_v'])} {float(kwargs['stop_v'])} {float(kwargs['step_v'])}"
            )
        else:
            raise ValueError(f"Unsupported simulation analysis '{analysis}'.")

        wrdata_line = f'wrdata "{data_path}" {" ".join(header_exprs)}'
        stripped = _strip_spice_end(base_netlist)
        return (
            f"{stripped}\n"
            ".control\n"
            "set filetype=ascii\n"
            "set wr_singlescale\n"
            "set wr_vecnames\n"
            "option numdgt=7\n"
            f"{analysis_cmd}\n"
            f'write "{raw_path}" all\n'
            f"{wrdata_line}\n"
            "quit\n"
            ".endc\n"
            ".end\n"
        )

    def _result_from_wrdata(
        self,
        analysis: SimulationKind,
        netlist_path: Path,
        data_path: Path,
        raw_path: Path | None,
        log_path: Path | None,
        header: list[str],
        rows: list[list[float]],
    ) -> SimulationResult:
        if analysis == "operating-point":
            first_row = rows[0]
            operating_point_traces = [
                SimulationTrace(name=_waveform_name(name), values=[first_row[index]])
                for index, name in enumerate(header[: len(first_row)])
            ]
            return SimulationResult(
                backend="ngspice-cli",
                analysis=analysis,
                netlist_path=netlist_path,
                data_path=data_path,
                raw_path=raw_path,
                log_path=log_path,
                traces=operating_point_traces,
            )

        if analysis == "ac":
            x_values = [row[0] for row in rows]
            ac_traces: list[SimulationTrace] = []
            index = 1
            while index + 1 < len(header):
                magnitude_name = header[index]
                phase_name = header[index + 1]
                magnitude_values = [row[index] for row in rows if len(row) > index]
                phase_values = [row[index + 1] for row in rows if len(row) > index + 1]
                ac_traces.append(
                    SimulationTrace(
                        name=_waveform_name(magnitude_name),
                        values=magnitude_values,
                        phase_values=phase_values if phase_name.lower().startswith("vp(") else None,
                    )
                )
                index += 2
            return SimulationResult(
                backend="ngspice-cli",
                analysis=analysis,
                netlist_path=netlist_path,
                data_path=data_path,
                raw_path=raw_path,
                log_path=log_path,
                x_label="frequency",
                x_values=x_values,
                traces=ac_traces,
            )

        x_label = "time" if analysis == "transient" else "sweep"
        x_index = 0
        for index, name in enumerate(header):
            lowered = name.lower()
            if lowered in {"time", "frequency"} or "sweep" in lowered:
                x_index = index
                break

        x_values = [row[x_index] for row in rows if len(row) > x_index]
        general_traces = [
            SimulationTrace(
                name=_waveform_name(name),
                values=[row[index] for row in rows if len(row) > index],
            )
            for index, name in enumerate(header)
            if index != x_index
        ]
        return SimulationResult(
            backend="ngspice-cli",
            analysis=analysis,
            netlist_path=netlist_path,
            data_path=data_path,
            raw_path=raw_path,
            log_path=log_path,
            x_label=x_label,
            x_values=x_values,
            traces=general_traces,
        )
