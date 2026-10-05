from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from kicad_mcp.server import build_server
from tests.conftest import call_tool_payload, call_tool_text


@pytest.mark.anyio
async def test_route_export_dsn_surfaces_manual_step_when_headless_unavailable(
    sample_project: Path,
) -> None:
    """When KiCad cannot export the DSN headlessly, the tool returns a clear human-gated
    result instead of dead-ending (work order P1-T7, K1)."""
    server = build_server("pcb")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    payload = await call_tool_payload(server, "route_export_dsn", {})

    assert payload["ok"] is False
    assert payload["human_gate_required"] is True
    assert any("Specctra DSN" in error for error in payload["errors"])


@pytest.mark.anyio
async def test_route_import_ses_surfaces_manual_gui_step(sample_project: Path) -> None:
    """SES import never claims the board is routed; it stages and surfaces the GUI step."""
    ses = sample_project / "output" / "routing" / "board.ses"
    ses.parent.mkdir(parents=True, exist_ok=True)
    ses.write_text("ses", encoding="utf-8")
    server = build_server("pcb")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    payload = await call_tool_payload(server, "route_import_ses", {})

    assert payload["human_gate_required"] is True
    assert payload["changed"] is False
    assert "Specctra Session" in payload["state_delta"]["summary"]


@pytest.mark.anyio
async def test_route_autoroute_freerouting_smoke_handles_large_dsn(
    sample_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    nets = "\n".join(f"  (net NET{i})" for i in range(60))
    (sample_project / "demo.dsn").write_text(f"(pcb\n{nets}\n)\n", encoding="utf-8")

    def fake_run(cmd, capture_output, text, timeout, check, **kwargs: object):
        _ = (capture_output, text, timeout, check)
        _ = kwargs
        if "--version" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout="KiCad 10.0.1", stderr="")
        if "--help" in cmd:
            return subprocess.CompletedProcess(
                cmd,
                0,
                stdout="gerbers positions ipc2581 svg dxf step render spice",
                stderr="",
            )
        ses_path = Path(cmd[cmd.index("-do") + 1])
        if "docker" in cmd[0]:
            ses_path = sample_project / "output" / "routing" / ses_path.name
        ses_path.parent.mkdir(parents=True, exist_ok=True)
        ses_path.write_text("ses", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout="pass 4\n100% routed\nok", stderr="")

    monkeypatch.setattr("kicad_mcp.utils.freerouting.subprocess.run", fake_run)
    monkeypatch.setattr("kicad_mcp.utils.freerouting._docker_available", lambda _: True)

    server = build_server("pcb")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    result = await call_tool_text(
        server,
        "route_autoroute_freerouting",
        {
            "dsn_path": "output/routing/board.dsn",
            "ses_path": "output/routing/board.ses",
            "net_classes_to_ignore": ["GND"],
            "max_passes": 60,
            "thread_count": 8,
            "use_docker": True,
        },
    )

    # SES content "ses" is invalid, so headless apply falls through to the
    # manual-gui-import fallback.
    assert "headless apply failed" in result
    assert "FreeRouting produced a routed session" in result
    assert "File > Import > Specctra Session" in result
    assert (sample_project / "output" / "routing" / "board.ses").exists()
    assert "Thread count: 8" in result
    assert "Routed: 100.00%" in result
    assert "Pass count: 4" in result


@pytest.mark.anyio
async def test_routing_rule_tools_write_state_and_dru_files(
    sample_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = build_server("pcb")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    monkeypatch.setattr(
        "kicad_mcp.tools.routing._list_board_net_names",
        lambda: {"USB_DP", "USB_DN", "CLK", "DATA0", "DATA1"},
    )
    monkeypatch.setattr(
        "kicad_mcp.tools.routing._current_track_length_mm",
        lambda net_name: {"CLK": 42.0, "USB_DP": 50.0, "USB_DN": 50.4}.get(net_name, 10.0),
    )

    net_class = await call_tool_text(
        server,
        "route_set_net_class_rules",
        {
            "net_class": "high_speed",
            "width_mm": 0.18,
            "clearance_mm": 0.15,
            "via_diameter_mm": 0.45,
            "via_drill_mm": 0.2,
        },
    )
    diff_pair = await call_tool_text(
        server,
        "route_differential_pair",
        {"net_p": "USB_DP", "net_n": "USB_DN", "width_mm": 0.16, "gap_mm": 0.18},
    )
    missing_pair = await call_tool_text(
        server,
        "route_differential_pair",
        {"net_p": "MISSING_P", "net_n": "MISSING_N"},
    )
    length = await call_tool_text(
        server,
        "route_tune_length",
        {"net_name": "CLK", "target_mm": 45.0, "tolerance_mm": 0.2},
    )
    missing_length = await call_tool_text(
        server,
        "tune_diff_pair_length",
        {"net_name_p": "USB_DP", "net_name_n": "NOPE", "target_length_mm": 50.0},
    )
    profile = await call_tool_text(
        server,
        "route_create_tuning_profile",
        {
            "name": "fast",
            "layer": "F.Cu",
            "trace_impedance_ohm": 90.0,
            "propagation_speed_factor": 0.6,
        },
    )
    profiles = await call_tool_text(server, "route_list_tuning_profiles", {})
    assigned = await call_tool_text(
        server,
        "route_apply_tuning_profile",
        {"net_pattern": "DATA*", "profile_name": "fast"},
    )
    missing_profile = await call_tool_text(
        server,
        "route_apply_tuning_profile",
        {"net_pattern": "DATA*", "profile_name": "slow"},
    )
    wildcard_time_domain = await call_tool_text(
        server,
        "route_tune_time_domain",
        {"net_or_group": "DATA*", "target_delay_ps": 250.0, "tolerance_ps": 15.0},
    )
    time_domain = await call_tool_text(
        server,
        "route_tune_time_domain",
        {"net_or_group": "DATA0", "target_delay_ps": 250.0, "tolerance_ps": 15.0},
    )

    dru_text = (sample_project / "demo.kicad_dru").read_text(encoding="utf-8")
    assert "Net-class routing rule" in net_class
    assert "Differential-pair routing rule" in diff_pair
    assert "Missing nets: MISSING_P, MISSING_N" in missing_pair
    assert "Delta: 3.000 mm" in length
    assert "Missing nets: NOPE" in missing_length
    assert "saved" in profile
    assert '"fast"' in profiles
    assert "assigned to 'DATA*'" in assigned
    assert "was not found" in missing_profile
    assert "constraints apply per net" in wildcard_time_domain
    assert "Time-domain tuning rule" in time_domain
    assert "A.NetName == 'DATA0'" in dru_text
    assert "A.NetName =~ 'DATA.*'" not in dru_text


@pytest.mark.anyio
async def test_route_apply_ses_applies_routing_headlessly(sample_project: Path) -> None:
    """route_apply_ses writes the routed SES into the board with no GUI step (P4-T1)."""
    pcb = sample_project / "demo.kicad_pcb"
    pcb.write_text(
        '(kicad_pcb\n\t(version 20250216)\n\t(net 0 "")\n\t(net 1 "GND")\n)\n',
        encoding="utf-8",
    )
    ses = sample_project / "output" / "routing" / "board.ses"
    ses.parent.mkdir(parents=True, exist_ok=True)
    ses.write_text(
        "(session t.dsn (routes (resolution um 10) (network_out "
        '(net "GND" (wire (path F.Cu 250 2500 -5000 11000 -5000)) '
        '(via "Via[0-1]_600:300_um" 11000 -5000)))))',
        encoding="utf-8",
    )
    server = build_server("pcb")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    payload = await call_tool_payload(
        server, "route_apply_ses", {"ses_path": "output/routing/board.ses"}
    )

    # Applied headlessly: changed, never a human gate.
    assert payload["changed"] is True
    assert not payload.get("human_gate_required")
    assert "headlessly" in payload["state_delta"]["summary"]

    # The routed segment + via are now in the board, mapped to net 1 (GND).
    text = pcb.read_text(encoding="utf-8")
    assert '(layer "F.Cu") (net 1)' in text
    assert "(via (at 11 5)" in text
    # The original net table is preserved (round-trip safe).
    assert '(net 1 "GND")' in text and "(version 20250216)" in text


@pytest.mark.anyio
async def test_route_apply_ses_reports_empty_session(sample_project: Path) -> None:
    """An SES with no routing fails cleanly rather than claiming a change."""
    (sample_project / "demo.kicad_pcb").write_text(
        '(kicad_pcb\n\t(net 1 "GND")\n)\n', encoding="utf-8"
    )
    ses = sample_project / "output" / "routing" / "board.ses"
    ses.parent.mkdir(parents=True, exist_ok=True)
    ses.write_text("(session t.dsn (routes (resolution um 10) (network_out)))", encoding="utf-8")
    server = build_server("pcb")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    payload = await call_tool_payload(
        server, "route_apply_ses", {"ses_path": "output/routing/board.ses"}
    )
    assert payload["ok"] is False
    assert any("no routed segments" in error.lower() for error in payload["errors"])


@pytest.mark.anyio
async def test_generate_board_constraints_from_intent(sample_project: Path) -> None:
    """generate_board_constraints emits .kicad_dru rules from the design intent."""
    from kicad_mcp.tools.design_intent_state import (
        InterfaceSpec,
        PowerRailSpec,
        ProjectDesignIntent,
    )
    from kicad_mcp.tools.project import _persist_project_spec

    intent = ProjectDesignIntent(
        power_rails=[
            PowerRailSpec(name="+3V3", voltage_v=3.3, current_max_a=0.5),
            PowerRailSpec(name="+12V", voltage_v=12.0, current_max_a=2.0),
        ],
        interfaces=[
            InterfaceSpec(
                kind="usb2",
                net_prefix="USB_",
                differential=True,
                impedance_target_ohm=90.0,
                diff_skew_max_ps=5.0,
            ),
        ],
    )
    _persist_project_spec(intent)

    server = build_server("pcb")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    payload = await call_tool_payload(server, "generate_board_constraints", {})

    assert payload["ok"] is True
    assert payload["changed"] is True
    summary: str = payload["state_delta"]["summary"]
    # Power rails
    assert "+3V3" in summary
    assert "+12V" in summary
    assert "width>=" in summary
    assert "clearance>=" in summary
    # Differential pair
    assert "usb" in summary.lower() or "USB_" in summary
    assert "diff-pair" in summary
    assert "width=" in summary
    # The .kicad_dru file was written
    dru_files = list(Path(sample_project).glob("*.kicad_dru"))
    assert dru_files
    dru_text = dru_files[0].read_text(encoding="utf-8")
    assert "pwr_+3V3" in dru_text or "pwr_" in dru_text


@pytest.mark.anyio
async def test_generate_board_constraints_empty_intent(sample_project: Path) -> None:
    """Without a saved design intent, generate_board_constraints fails gracefully."""
    server = build_server("pcb")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    payload = await call_tool_payload(server, "generate_board_constraints", {})

    assert payload["ok"] is False
    assert any("import_design_spec" in error.lower() for error in payload["errors"])
