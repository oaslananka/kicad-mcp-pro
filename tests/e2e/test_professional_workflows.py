from __future__ import annotations

import json
from pathlib import Path

import pytest
from kipy.proto.board.board_types_pb2 import BoardLayer

from kicad_mcp.discovery import CliCapabilities
from kicad_mcp.server import build_server
from kicad_mcp.tools.validation import GateOutcome
from kicad_mcp.utils.component_search import ComponentRecord
from kicad_mcp.utils.ngspice import SimulationResult, SimulationTrace
from tests.conftest import call_tool_text
from tests.integration.test_emc_tools import _configure_emc_board
from tests.integration.test_pcb_export_validation_surface import _fake_cli_run_factory
from tests.integration.test_power_integrity_tools import _configure_power_board
from tests.integration.test_signal_integrity_tools import _configure_signal_integrity_board


def _write_manufacturing_approval(project: Path) -> str:
    evidence_dir = project / ".kicad-mcp"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    path = evidence_dir / "manufacturing_approval.json"
    path.write_text(
        json.dumps(
            {
                "approved_by": "Test Reviewer",
                "approved_at_utc": "2026-07-04T00:00:00Z",
                "approval_scope": "manufacturing release package",
            }
        ),
        encoding="utf-8",
    )
    return ".kicad-mcp/manufacturing_approval.json"


class _WorkflowComponentClient:
    def search(self, keyword, *, package=None, only_basic=True, limit=20):
        _ = (keyword, package, only_basic, limit)
        return [
            ComponentRecord(
                source="jlcsearch",
                lcsc_code="C25804",
                mpn="0603WAF1002T5E",
                package="0603",
                description="10k resistor",
                stock=37_000_000,
                price=0.000842857,
                is_basic=True,
                is_preferred=False,
            )
        ]

    def get_part(self, lcsc_code_or_mpn):
        _ = lcsc_code_or_mpn
        return self.search("10k resistor")[0]


class _WorkflowSimulationRunner:
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
        _ = (output_dir, probe_nets, start_freq_hz, stop_freq_hz, points_per_decade)
        return SimulationResult(
            backend="inspice",
            analysis="ac",
            netlist_path=netlist_path,
            x_label="frequency",
            x_values=[1.0e6, 2.4e9],
            traces=[
                SimulationTrace(name="ant", values=[0.9, 0.72], phase_values=[-5.0, -42.0]),
            ],
        )


@pytest.mark.anyio
async def test_scenario_1_mcu_board_workflow(
    sample_project: Path,
    mock_board,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_run = _fake_cli_run_factory(sample_project)
    monkeypatch.setattr("kicad_mcp.tools.export.subprocess.run", fake_run)
    monkeypatch.setattr("kicad_mcp.discovery.subprocess.run", fake_run)
    monkeypatch.setattr(
        "kicad_mcp.tools.export.get_cli_capabilities",
        lambda _cli: CliCapabilities(
            version="KiCad 10.0.1",
            gerber_command="gerber",
            drill_command="drill",
            position_command="pos",
            supports_ipc2581=True,
            supports_svg=True,
            supports_dxf=True,
            supports_step=True,
            supports_render=True,
            supports_spice_netlist=True,
        ),
    )
    monkeypatch.setattr(
        "kicad_mcp.tools.library._component_search_client",
        lambda source: _WorkflowComponentClient(),
    )
    monkeypatch.setattr(
        "kicad_mcp.tools.validation._evaluate_project_gate",
        lambda **_kwargs: [
            GateOutcome(
                name="Schematic",
                status="PASS",
                summary="ERC is clean.",
                details=["ERC violations: 0"],
            ),
            GateOutcome(
                name="PCB",
                status="PASS",
                summary="PCB passes DRC, unconnected, and courtyard checks.",
                details=["DRC violations: 0"],
            ),
            GateOutcome(
                name="Placement",
                status="PASS",
                summary="Footprint placement is geometrically sane.",
                details=["Overlaps: 0"],
            ),
            GateOutcome(
                name="Manufacturing",
                status="PASS",
                summary="DFM checks passed.",
                details=["Profile: JLCPCB / standard"],
            ),
            GateOutcome(
                name="Footprint parity",
                status="PASS",
                summary="PCB and schematic references are aligned.",
                details=["Missing on board: 0"],
            ),
        ],
    )
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    search = await call_tool_text(
        server,
        "lib_search_components",
        {"keyword": "STM32F103", "source": "jlcsearch"},
    )
    await call_tool_text(
        server,
        "sch_build_circuit",
        {
            "auto_layout": True,
            "symbols": [
                {
                    "library": "Device",
                    "symbol_name": "R",
                    "reference": "R1",
                    "value": "10k",
                    "footprint": "Resistor_SMD:R_0805",
                },
                {
                    "library": "Device",
                    "symbol_name": "R",
                    "reference": "R2",
                    "value": "1k",
                    "footprint": "Resistor_SMD:R_0805",
                },
            ],
        },
    )
    assigned = await call_tool_text(
        server,
        "lib_assign_lcsc_to_symbol",
        {"reference": "R1", "lcsc_code": "25804"},
    )
    dfm = await call_tool_text(
        server,
        "dfm_calculate_manufacturing_cost",
        {"quantity": 10, "manufacturer": "JLCPCB", "tier": "standard"},
    )
    package = await call_tool_text(
        server,
        "export_manufacturing_package",
        {"approval_evidence_path": _write_manufacturing_approval(sample_project)},
    )

    assert "Live component matches" in search
    assert "Assigned LCSC code 'C25804'" in assigned
    assert "Manufacturing cost estimate" in dfm
    assert "Gerber export completed" in package
    assert "Pick and place data exported" in package


@pytest.mark.anyio
async def test_scenario_2_high_speed_workflow(
    sample_project: Path,
    mock_board,
) -> None:
    _configure_signal_integrity_board(mock_board)
    server = build_server("high_speed")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    stackup = await call_tool_text(
        server,
        "si_generate_stackup",
        {"layer_count": 4, "target_impedance_ohm": 50.0, "manufacturer": "JLCPCB"},
    )
    await call_tool_text(
        server,
        "pcb_set_stackup",
        {
            "layers": [
                {"name": "F_Cu", "type": "signal", "thickness_mm": 0.035, "material": "Copper"},
                {
                    "name": "dielectric_1",
                    "type": "prepreg",
                    "thickness_mm": 0.18,
                    "material": "FR4",
                    "epsilon_r": 4.2,
                },
                {"name": "In1_Cu", "type": "ground", "thickness_mm": 0.018, "material": "Copper"},
                {"name": "dielectric_2", "type": "core", "thickness_mm": 1.164, "material": "FR4"},
                {"name": "B_Cu", "type": "signal", "thickness_mm": 0.035, "material": "Copper"},
            ]
        },
    )
    rules = await call_tool_text(
        server,
        "route_set_net_class_rules",
        {
            "net_class": "USB",
            "width_mm": 0.2,
            "clearance_mm": 0.15,
            "via_diameter_mm": 0.5,
            "via_drill_mm": 0.25,
        },
    )
    diff = await call_tool_text(
        server,
        "route_differential_pair",
        {
            "net_p": "USB_DP",
            "net_n": "USB_DN",
            "width_mm": 0.2,
            "gap_mm": 0.18,
            "length_tolerance_mm": 0.1,
        },
    )
    match = await call_tool_text(
        server,
        "si_validate_length_matching",
        {"net_groups": [["USB_DP", "USB_DN"]], "tolerance_mm": 1.0},
    )

    assert "Recommended 4-layer JLCPCB stackup" in stackup
    assert "Net-class routing rule" in rules
    assert "Differential-pair routing rule" in diff
    assert "Length-matching validation" in match


@pytest.mark.anyio
async def test_scenario_3_hierarchical_power_supply_workflow(
    sample_project: Path,
    mock_board,
) -> None:
    _configure_power_board(mock_board)
    server = build_server("power")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    sheet_a = await call_tool_text(
        server,
        "sch_create_sheet",
        {"name": "buck_5v", "filename": "buck_5v.kicad_sch", "x_mm": 30.0, "y_mm": 30.0},
    )
    sheet_b = await call_tool_text(
        server,
        "sch_create_sheet",
        {"name": "ldo_3v3", "filename": "ldo_3v3.kicad_sch", "x_mm": 80.0, "y_mm": 30.0},
    )
    sheets = await call_tool_text(server, "sch_list_sheets", {})
    info = await call_tool_text(server, "sch_get_sheet_info", {"sheet_name": "buck_5v"})
    decoupling = await call_tool_text(
        server,
        "pdn_recommend_decoupling_caps",
        {"ic_refs": ["U1", "U2"], "vcc_net": "3V3", "supply_voltage_v": 3.3},
    )
    thermal = await call_tool_text(
        server,
        "thermal_calculate_via_count",
        {"power_w": 3.0, "via_diameter_mm": 0.3, "thermal_resistance_target": 4.0},
    )

    assert "Created child sheet" in sheet_a
    assert "Created child sheet" in sheet_b
    assert "buck_5v" in sheets
    assert "ldo_3v3" in sheets
    assert "Sheet 'buck_5v'" in info
    assert "Decoupling recommendation for 3V3" in decoupling
    assert "Thermal via estimate" in thermal


@pytest.mark.anyio
async def test_scenario_4_rf_keepout_and_simulation_workflow(
    sample_project: Path,
    mock_board,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_board.get_enabled_layers.return_value = [BoardLayer.BL_F_Cu, BoardLayer.BL_B_Cu]
    monkeypatch.setattr("kicad_mcp.tools.simulation._runner", _WorkflowSimulationRunner)

    netlist = sample_project / "rf_frontend.cir"
    netlist.write_text("* rf\n.end\n", encoding="utf-8")

    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    width = await call_tool_text(
        server,
        "si_calculate_trace_width_for_impedance",
        {"target_ohm": 50.0, "height_mm": 0.18, "er": 4.2, "trace_type": "microstrip"},
    )
    keepout = await call_tool_text(
        server,
        "pcb_set_keepout_zone",
        {"x_mm": 42.0, "y_mm": 18.0, "w_mm": 12.0, "h_mm": 8.0},
    )
    directive = await call_tool_text(
        server,
        "sim_add_spice_directive",
        {"directive": ".ac dec 20 1Meg 2.4Gig"},
    )
    ac = await call_tool_text(
        server,
        "sim_run_ac_analysis",
        {
            "netlist_path": "rf_frontend.cir",
            "start_freq_hz": 1.0e6,
            "stop_freq_hz": 2.4e9,
            "points_per_decade": 20,
            "probe_nets": ["ant"],
        },
    )

    assert "Width synthesis for 50.00 ohm" in width
    assert "Added keepout zone" in keepout
    assert "Stored simulation directive" in directive
    assert "AC analysis" in ac


@pytest.mark.anyio
async def test_scenario_5_emc_usb_hub_workflow(
    sample_project: Path,
    mock_board,
) -> None:
    _configure_emc_board(mock_board)
    server = build_server("analysis")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    skew = await call_tool_text(
        server,
        "si_check_differential_pair_skew",
        {"net_p": "USB_DP", "net_n": "USB_DN"},
    )
    emc = await call_tool_text(
        server,
        "emc_run_full_compliance",
        {"standard": "FCC"},
    )
    continuity = await call_tool_text(
        server,
        "emc_check_return_path_continuity",
        {"signal_net": "USB_DP", "reference_plane_layer": "B_Cu"},
    )

    assert "Differential-pair skew analysis" in skew
    assert "EMC compliance sweep (FCC)" in emc
    assert "Checks run: 10" in emc
    assert "Return path continuity" in continuity
