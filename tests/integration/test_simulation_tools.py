from __future__ import annotations

from pathlib import Path

import pytest

from kicad_mcp.server import build_server
from kicad_mcp.utils.ngspice import SimulationResult, SimulationTrace
from tests.conftest import call_tool_text


@pytest.mark.anyio
async def test_simulation_tool_surface_and_directive_storage(sample_project: Path) -> None:
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    category_tools = await call_tool_text(
        server, "kicad_get_tools_in_category", {"category": "simulation"}
    )
    directive_text = await call_tool_text(
        server,
        "sim_add_spice_directive",
        {"directive": ".param gain=10"},
    )

    assert "sim_run_operating_point" in category_tools
    assert "sim_check_stability" in category_tools
    assert "Stored simulation directive" in directive_text
    directive_file = sample_project / ".kicad_mcp_spice_directives.cir"
    assert directive_file.exists()
    assert ".param gain=10" in directive_file.read_text(encoding="utf-8")


@pytest.mark.anyio
async def test_simulation_tools_use_runner_outputs(sample_project: Path, monkeypatch) -> None:
    netlist = sample_project / "custom.cir"
    netlist.write_text("* deck\n.end\n", encoding="utf-8")

    class FakeRunner:
        def run_operating_point(self, netlist_path, output_dir, probe_nets):
            _ = output_dir, probe_nets
            return SimulationResult(
                backend="inspice",
                analysis="operating-point",
                netlist_path=netlist_path,
                traces=[SimulationTrace(name="out", values=[2.5])],
            )

        def run_ac_analysis(
            self,
            netlist_path,
            output_dir,
            probe_nets,
            *,
            start_freq_hz,
            stop_freq_hz,
            points_per_decade,
        ):
            _ = output_dir, probe_nets, start_freq_hz, stop_freq_hz, points_per_decade
            return SimulationResult(
                backend="inspice",
                analysis="ac",
                netlist_path=netlist_path,
                x_label="frequency",
                x_values=[10.0, 1000.0],
                traces=[
                    SimulationTrace(name="out", values=[2.0, 1.0], phase_values=[-90.0, -135.0]),
                ],
            )

        def run_transient_analysis(
            self,
            netlist_path,
            output_dir,
            probe_nets,
            *,
            stop_time_s,
            step_time_s,
        ):
            _ = output_dir, probe_nets, stop_time_s, step_time_s
            return SimulationResult(
                backend="inspice",
                analysis="transient",
                netlist_path=netlist_path,
                x_label="time",
                x_values=[0.0, 1e-3],
                traces=[SimulationTrace(name="out", values=[0.0, 4.8])],
            )

        def run_dc_sweep(
            self,
            netlist_path,
            output_dir,
            probe_nets,
            *,
            source_ref,
            start_v,
            stop_v,
            step_v,
        ):
            _ = output_dir, probe_nets, source_ref, start_v, stop_v, step_v
            return SimulationResult(
                backend="inspice",
                analysis="dc",
                netlist_path=netlist_path,
                x_label="sweep",
                x_values=[0.0, 5.0],
                traces=[SimulationTrace(name="out", values=[0.0, 4.95])],
            )

    monkeypatch.setattr("kicad_mcp.tools.simulation._runner", lambda: FakeRunner())
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    op = await call_tool_text(server, "sim_run_operating_point", {"netlist_path": "custom.cir"})
    ac = await call_tool_text(
        server,
        "sim_run_ac_analysis",
        {
            "netlist_path": "custom.cir",
            "start_freq_hz": 10.0,
            "stop_freq_hz": 1000.0,
            "points_per_decade": 20,
            "probe_nets": ["out"],
        },
    )
    tran = await call_tool_text(
        server,
        "sim_run_transient",
        {
            "netlist_path": "custom.cir",
            "stop_time_s": 1e-3,
            "step_time_s": 1e-6,
            "probe_nets": ["out"],
        },
    )
    sweep = await call_tool_text(
        server,
        "sim_run_dc_sweep",
        {
            "netlist_path": "custom.cir",
            "source_ref": "V1",
            "start_v": 0.0,
            "stop_v": 5.0,
            "step_v": 0.5,
            "probe_nets": ["out"],
        },
    )

    assert "Operating point analysis" in op
    assert "out: 2.5" in op
    assert "AC analysis" in ac
    assert "phase -90" in ac
    assert "Transient analysis" in tran
    assert "4.8" in tran
    assert "DC sweep analysis" in sweep
    assert "4.95" in sweep


@pytest.mark.anyio
async def test_stability_check_formats_phase_margin(sample_project: Path, monkeypatch) -> None:
    netlist = sample_project / "loop.cir"
    netlist.write_text("* deck\n.end\n", encoding="utf-8")

    class FakeRunner:
        def run_ac_analysis(
            self,
            netlist_path,
            output_dir,
            probe_nets,
            *,
            start_freq_hz,
            stop_freq_hz,
            points_per_decade,
        ):
            _ = output_dir, probe_nets, start_freq_hz, stop_freq_hz, points_per_decade
            return SimulationResult(
                backend="inspice",
                analysis="ac",
                netlist_path=netlist_path,
                x_label="frequency",
                x_values=[10.0, 100.0, 1000.0],
                traces=[
                    SimulationTrace(
                        name="out",
                        values=[10.0, 1.0, 0.1],
                        phase_values=[-90.0, -135.0, -170.0],
                    ),
                    SimulationTrace(
                        name="fb",
                        values=[1.0, 1.0, 1.0],
                        phase_values=[0.0, 0.0, 0.0],
                    ),
                ],
            )

    monkeypatch.setattr("kicad_mcp.tools.simulation._runner", lambda: FakeRunner())
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    text = await call_tool_text(
        server,
        "sim_check_stability",
        {
            "netlist_path": "loop.cir",
            "output_net": "out",
            "feedback_net": "fb",
        },
    )

    assert "Stability check" in text
    assert "Unity-gain crossover" in text
    assert "Estimated phase margin" in text


@pytest.mark.anyio
async def test_simulation_tools_can_export_active_schematic(
    sample_project: Path,
    monkeypatch,
) -> None:
    exported: list[Path] = []

    def fake_run_cli_variants(variants: list[list[str]]):
        out_file = Path(variants[0][variants[0].index("--output") + 1])
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_text("* exported\n.end\n", encoding="utf-8")
        exported.append(out_file)
        return (0, "", "")

    class FakeRunner:
        def run_operating_point(self, netlist_path, output_dir, probe_nets):
            _ = output_dir, probe_nets
            return SimulationResult(
                backend="ngspice-cli",
                analysis="operating-point",
                netlist_path=netlist_path,
                traces=[SimulationTrace(name="out", values=[1.8])],
            )

    monkeypatch.setattr("kicad_mcp.tools.simulation._run_cli_variants", fake_run_cli_variants)
    monkeypatch.setattr("kicad_mcp.tools.simulation._runner", lambda: FakeRunner())
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    text = await call_tool_text(server, "sim_run_operating_point", {})

    assert "Operating point analysis" in text
    assert exported
    assert exported[0].name == "exported_netlist.cir"
