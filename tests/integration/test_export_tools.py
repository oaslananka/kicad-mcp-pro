from __future__ import annotations

import json

import pytest

from kicad_mcp.connection import KiCadConnectionError
from kicad_mcp.discovery import CliCapabilities
from kicad_mcp.server import build_server
from kicad_mcp.tools.validation import GateOutcome
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
async def test_run_erc_flattens_sheet_violations(sample_project, monkeypatch) -> None:
    monkeypatch.setattr(
        "kicad_mcp.tools.validation._run_erc_report",
        lambda _report_name: (
            sample_project / "output" / "erc_report.json",
            {
                "sheets": [
                    {
                        "path": "/",
                        "violations": [
                            {
                                "severity": "error",
                                "type": "label_dangling",
                                "description": "Label not connected",
                            },
                            {
                                "severity": "warning",
                                "type": "pin_not_connected",
                                "description": "Pin not connected",
                            },
                        ],
                    }
                ]
            },
            None,
        ),
    )

    server = build_server("manufacturing")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    text = await call_tool_text(server, "run_erc", {"save_report": True})

    assert "ERC summary" in text
    assert "- Violations: 2" in text
    assert "Label not connected" in text
    assert "Pin not connected" in text


@pytest.mark.anyio
async def test_project_quality_gate_reports_failures(sample_project, monkeypatch) -> None:
    monkeypatch.setattr(
        "kicad_mcp.tools.validation._run_erc_report",
        lambda _report_name: (
            sample_project / "output" / "schematic_quality_gate.json",
            {
                "sheets": [
                    {
                        "path": "/",
                        "violations": [
                            {
                                "severity": "error",
                                "type": "pin_not_connected",
                                "description": "Pin not connected",
                            }
                        ],
                    }
                ]
            },
            None,
        ),
    )
    monkeypatch.setattr(
        "kicad_mcp.tools.validation._run_drc_report",
        lambda _report_name: (
            sample_project / "output" / "pcb_quality_gate.json",
            {
                "violations": [
                    {
                        "severity": "error",
                        "type": "clearance",
                        "description": "Clearance violation",
                    }
                ],
                "unconnected_items": [{"severity": "error", "description": "NET1"}],
                "items_not_passing_courtyard": [],
            },
            None,
        ),
    )
    monkeypatch.setattr(
        "kicad_mcp.tools.validation._evaluate_pcb_placement_gate",
        lambda: GateOutcome(
            name="Placement",
            status="FAIL",
            summary="Footprint placement still has overlap or board-boundary issues.",
            details=["Overlaps: 2"],
        ),
    )
    monkeypatch.setattr(
        "kicad_mcp.tools.validation._evaluate_manufacturing_gate",
        lambda **_kwargs: GateOutcome(
            name="Manufacturing",
            status="FAIL",
            summary="DFM reported 1 failing checks.",
            details=["Profile: JLCPCB / standard"],
        ),
    )
    monkeypatch.setattr(
        "kicad_mcp.tools.validation._evaluate_pcb_transfer_gate",
        lambda: GateOutcome(
            name="PCB transfer",
            status="FAIL",
            summary="Named schematic pad nets did not transfer cleanly to the PCB.",
            details=["Transfer coverage: 25.0%"],
        ),
    )
    monkeypatch.setattr(
        "kicad_mcp.tools.validation._footprint_parity_outcome",
        lambda: GateOutcome(
            name="Footprint parity",
            status="FAIL",
            summary="Schematic and PCB references are out of sync.",
            details=["Missing on board: 1"],
        ),
    )

    server = build_server("manufacturing")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    text = await call_tool_text(server, "project_quality_gate", {})

    assert "Project quality gate: FAIL" in text
    assert "Schematic quality gate: FAIL" in text
    assert "PCB quality gate: FAIL" in text
    assert "Placement quality gate: FAIL" in text
    assert "Manufacturing quality gate: FAIL" in text
    assert "Footprint parity quality gate: FAIL" in text


@pytest.mark.anyio
async def test_export_manufacturing_package_hard_blocks_on_failed_project_gate(
    sample_project,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "kicad_mcp.tools.validation._evaluate_project_gate",
        lambda **_kwargs: [
            GateOutcome(
                name="Schematic",
                status="FAIL",
                summary="ERC reported blocking issues.",
                details=["ERC violations: 2"],
            ),
            GateOutcome(
                name="Placement",
                status="FAIL",
                summary="Footprint placement still has overlap or board-boundary issues.",
                details=["Overlaps: 1"],
            ),
        ],
    )

    server = build_server("manufacturing")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    text = await call_tool_text(server, "export_manufacturing_package", {})

    assert "Project quality gate: FAIL" in text
    assert "hard-blocked" in text
    assert "Gerber export completed" not in text
    assert "Drill export completed" not in text


@pytest.mark.anyio
async def test_validate_footprints_vs_schematic_uses_file_fallback(
    sample_project,
    monkeypatch,
) -> None:
    (sample_project / "demo.kicad_sch").write_text(
        (
            "(kicad_sch\n"
            "\t(version 20250316)\n"
            '\t(generator "pytest")\n'
            '\t(uuid "00000000-0000-0000-0000-000000000000")\n'
            '\t(paper "A4")\n'
            "\t(lib_symbols)\n"
            '\t(symbol (lib_id "Device:R") (at 10 10 0)\n'
            '\t\t(property "Reference" "R1" (at 10 12 0) (effects (font (size 1.27 1.27))))\n'
            '\t\t(property "Value" "10k" (at 10 8 0) (effects (font (size 1.27 1.27))))\n'
            '\t\t(property "Footprint" "Resistor_SMD:R_0805" '
            '(at 10 6 0) (effects (font (size 1.27 1.27))))\n'
            "\t)\n"
            "\t(sheet_instances\n"
            '\t\t(path "/" (page "1"))\n'
            "\t)\n"
            "\t(embedded_fonts no)\n"
            ")\n"
        ),
        encoding="utf-8",
    )
    (sample_project / "demo.kicad_pcb").write_text(
        (
            "(kicad_pcb\n"
            '\t(version 20250216)\n'
            '\t(generator "pytest")\n'
            '\t(footprint "Resistor_SMD:R_0805"\n'
            '\t\t(layer "F.Cu")\n'
            '\t\t(property "Reference" "R1" (at 0 0 0) (layer "F.SilkS"))\n'
            '\t\t(property "Value" "10k" (at 0 1 0) (layer "F.Fab"))\n'
            "\t)\n"
            ")\n"
        ),
        encoding="utf-8",
    )

    def raise_no_ipc():
        raise KiCadConnectionError("no board")

    monkeypatch.setattr("kicad_mcp.tools.validation.get_board", raise_no_ipc)

    server = build_server("manufacturing")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    text = await call_tool_text(server, "validate_footprints_vs_schematic", {})

    assert "Footprint versus schematic comparison:" in text
    assert "- Status: PASS" in text
    assert "PCB footprint refs (file): 1" in text


@pytest.mark.anyio
async def test_pcb_placement_quality_gate_detects_overlap(sample_project) -> None:
    (sample_project / "demo.kicad_pcb").write_text(
        (
            "(kicad_pcb\n"
            '\t(version 20250216)\n'
            '\t(generator "pytest")\n'
            '\t(gr_rect (start 0 0) (end 20 20) (stroke (width 0.05) (type solid)) '
            '(fill no) (layer "Edge.Cuts"))\n'
            '\t(footprint "Resistor_SMD:R_0805"\n'
            '\t\t(layer "F.Cu")\n'
            '\t\t(at 5 5 0)\n'
            '\t\t(property "Reference" "R1" (at 0 0 0) (layer "F.SilkS"))\n'
            '\t\t(property "Value" "10k" (at 0 1 0) (layer "F.Fab"))\n'
            '\t\t(fp_rect (start -2 -1) (end 2 1) (stroke (width 0.05) (type solid)) '
            '(fill no) (layer "F.CrtYd"))\n'
            "\t)\n"
            '\t(footprint "Resistor_SMD:R_0805"\n'
            '\t\t(layer "F.Cu")\n'
            '\t\t(at 5.5 5 0)\n'
            '\t\t(property "Reference" "R2" (at 0 0 0) (layer "F.SilkS"))\n'
            '\t\t(property "Value" "10k" (at 0 1 0) (layer "F.Fab"))\n'
            '\t\t(fp_rect (start -2 -1) (end 2 1) (stroke (width 0.05) (type solid)) '
            '(fill no) (layer "F.CrtYd"))\n'
            "\t)\n"
            ")\n"
        ),
        encoding="utf-8",
    )

    server = build_server("manufacturing")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    text = await call_tool_text(server, "pcb_placement_quality_gate", {})

    assert "Placement quality gate: FAIL" in text
    assert "Placement score:" in text
    assert "Overlap refs: R1/R2" in text


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
