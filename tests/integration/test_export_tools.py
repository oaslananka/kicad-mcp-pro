from __future__ import annotations

import json

import pytest

from kicad_mcp.discovery import CliCapabilities
from kicad_mcp.server import build_server
from tests.conftest import call_tool_text


@pytest.mark.anyio
async def test_export_gerber_uses_cli_variants(sample_project, monkeypatch) -> None:
    out_dir = sample_project / "output" / "gerber"

    def fake_run(cmd, *args: object, **kwargs: object):
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "demo-F_Cu.gbr").write_text("gerber", encoding="utf-8")

        class Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return Result()

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
    server = build_server("manufacturing")
    text = await call_tool_text(server, "export_gerber", {"output_subdir": "gerber", "layers": []})
    assert "Gerber export completed" in text


@pytest.mark.anyio
async def test_run_drc_reads_json_report(sample_project, monkeypatch) -> None:
    report_path = sample_project / "output" / "drc_report.json"

    def fake_run(cmd, *args: object, **kwargs: object):
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(
                {
                    "violations": [{"severity": "error", "description": "Clearance"}],
                    "unconnected_items": [],
                    "items_not_passing_courtyard": [],
                }
            ),
            encoding="utf-8",
        )

        class Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return Result()

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
    server = build_server("manufacturing")
    text = await call_tool_text(server, "run_drc", {"save_report": True})
    assert "DRC summary" in text


@pytest.mark.anyio
async def test_export_pcb_pdf_uses_default_layers(sample_project, monkeypatch) -> None:
    commands: list[list[str]] = []

    def fake_run(cmd, *args: object, **kwargs: object):
        commands.append(list(cmd))

        class Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return Result()

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
    server = build_server("manufacturing")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    text = await call_tool_text(server, "export_pcb_pdf", {})

    assert "PCB PDF exported" in text
    assert commands
    assert "--layers" in commands[0]
    assert commands[0][commands[0].index("--layers") + 1] == "F.Cu,Edge.Cuts"


@pytest.mark.anyio
async def test_export_pcb_pdf_joins_multiple_layers(sample_project, monkeypatch) -> None:
    commands: list[list[str]] = []

    def fake_run(cmd, *args: object, **kwargs: object):
        commands.append(list(cmd))

        class Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return Result()

    monkeypatch.setattr("kicad_mcp.tools.export.subprocess.run", fake_run)
    monkeypatch.setattr("kicad_mcp.discovery.subprocess.run", fake_run)
    server = build_server("manufacturing")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    text = await call_tool_text(server, "export_pcb_pdf", {"layers": ["F.Cu", "Edge.Cuts"]})

    assert "PCB PDF exported" in text
    assert commands
    assert commands[0].count("--layers") == 1
    assert commands[0][commands[0].index("--layers") + 1] == "F.Cu,Edge.Cuts"


@pytest.mark.anyio
async def test_export_netlist_maps_kicad_format_for_cli(sample_project, monkeypatch) -> None:
    commands: list[list[str]] = []

    def fake_run(cmd, *args: object, **kwargs: object):
        commands.append(list(cmd))
        out_path = sample_project / "output" / "netlist.net"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text("(export (version D))\n", encoding="utf-8")

        class Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return Result()

    monkeypatch.setattr("kicad_mcp.tools.export.subprocess.run", fake_run)
    monkeypatch.setattr("kicad_mcp.discovery.subprocess.run", fake_run)
    server = build_server("manufacturing")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    text = await call_tool_text(server, "export_netlist", {"format": "kicad"})

    assert "Netlist exported" in text
    assert commands
    assert "--format" in commands[0]
    assert commands[0][commands[0].index("--format") + 1] == "kicadsexpr"
    assert "--input" not in commands[0]


@pytest.mark.anyio
async def test_export_svg_uses_multi_mode_directory_output(sample_project, monkeypatch) -> None:
    commands: list[list[str]] = []

    def fake_run(cmd, *args: object, **kwargs: object):
        commands.append(list(cmd))
        out_dir = sample_project / "output" / "svg"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "board.svg").write_text("<svg />\n", encoding="utf-8")

        class Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return Result()

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
    server = build_server("manufacturing")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    text = await call_tool_text(server, "export_svg", {"layer": "Edge.Cuts"})

    assert "SVG export completed" in text
    assert commands
    assert "--mode-multi" in commands[0]
    assert "--input" not in commands[0]
