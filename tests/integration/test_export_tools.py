from __future__ import annotations

import json
from pathlib import Path

import pytest
from mcp.types import ImageContent

from kicad_mcp.connection import KiCadConnectionError
from kicad_mcp.discovery import CliCapabilities
from kicad_mcp.server import build_server
from kicad_mcp.tools.export import LOW_LEVEL_EXPORT_NOTICE
from kicad_mcp.tools.validation import GateOutcome
from tests.conftest import call_tool_content, call_tool_text, tool_text


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
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})
    text = await call_tool_text(server, "export_gerber", {"output_subdir": "gerber", "layers": []})
    assert text.startswith(LOW_LEVEL_EXPORT_NOTICE)
    assert "Gerber export completed" in text


@pytest.mark.anyio
async def test_export_gerber_prefers_modern_command_then_legacy_fallback(
    sample_project,
    monkeypatch,
) -> None:
    out_dir = sample_project / "output" / "gerber"
    commands: list[list[str]] = []

    def fake_run(cmd, *args: object, **kwargs: object):
        _ = args, kwargs
        commands.append(list(cmd))
        if "render" in cmd:
            output_path = Path(cmd[cmd.index("--output") + 1])
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"\x89PNG\r\n\x1a\n")

        class Result:
            stdout = ""

            def __init__(self, returncode: int, stderr: str) -> None:
                self.returncode = returncode
                self.stderr = stderr

        if "gerbers" in cmd:
            return Result(1, "unknown command")
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "demo-F_Cu.gbr").write_text("gerber", encoding="utf-8")
        return Result(0, "")

    monkeypatch.setattr("kicad_mcp.tools.export.subprocess.run", fake_run)
    monkeypatch.setattr("kicad_mcp.discovery.subprocess.run", fake_run)
    monkeypatch.setattr(
        "kicad_mcp.tools.export.get_cli_capabilities",
        lambda _cli: CliCapabilities(
            version="KiCad 10.0.1",
            gerber_command="gerbers",
            drill_command="drill",
            position_command="pos",
            supports_step=True,
            supports_stepz=True,
            supports_xao=True,
            supports_render=True,
        ),
    )
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})
    text = await call_tool_text(server, "export_gerber", {"output_subdir": "gerber", "layers": []})

    assert text.startswith(LOW_LEVEL_EXPORT_NOTICE)
    assert "Gerber export completed" in text
    assert [command[3] for command in commands[:3]] == ["gerbers", "gerbers", "gerber"]


@pytest.mark.anyio
async def test_render_stackup_colors_flag_is_opt_in(
    sample_project,
    monkeypatch,
) -> None:
    commands: list[list[str]] = []

    def fake_run(cmd, *args: object, **kwargs: object):
        _ = args, kwargs
        commands.append(list(cmd))
        if "--output" in cmd:
            output_path = Path(cmd[cmd.index("--output") + 1])
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)

        class Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return Result()

    monkeypatch.setattr("kicad_mcp.tools.export.subprocess.run", fake_run)
    monkeypatch.setattr(
        "kicad_mcp.tools.export.get_cli_capabilities",
        lambda _cli: CliCapabilities(
            version="KiCad 10.0.5",
            gerber_command="gerbers",
            drill_command="drill",
            position_command="pos",
            supports_render=True,
        ),
    )
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    await call_tool_text(server, "export_3d_render", {"output_file": "default.png"})
    await call_tool_text(
        server,
        "export_3d_render",
        {"output_file": "stackup.png", "use_board_stackup_colors": True},
    )

    render_commands = [command for command in commands if "render" in command]
    assert "--use-board-stackup-colors" not in render_commands[0]
    assert render_commands[1].count("--use-board-stackup-colors") == 1


@pytest.mark.anyio
async def test_export_paths_reject_traversal_and_absolute_outputs(
    sample_project,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "kicad_mcp.tools.export.get_cli_capabilities",
        lambda _cli: CliCapabilities(
            version="KiCad 10.0.1",
            gerber_command="gerbers",
            drill_command="drill",
            position_command="pos",
            supports_step=True,
            supports_stepz=True,
            supports_xao=True,
            supports_render=True,
        ),
    )
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    gerber = await call_tool_text(server, "export_gerber", {"output_subdir": "../escape"})
    step = await call_tool_text(
        server,
        "export_step",
        {"output_path": str(sample_project.parent / "escape.step")},
    )
    stepz = await call_tool_text(server, "export_stepz", {"output_path": "../escape.stepz"})
    xao = await call_tool_text(
        server,
        "export_xao",
        {"output_path": str(sample_project.parent / "escape.xao")},
    )
    render = await call_tool_text(server, "export_3d_render", {"output_file": "nested/render.png"})
    render_backslash = await call_tool_text(
        server,
        "export_3d_render",
        {"output_file": r"nested\render.png"},
    )

    assert gerber.startswith(LOW_LEVEL_EXPORT_NOTICE)
    assert step.startswith(LOW_LEVEL_EXPORT_NOTICE)
    assert stepz.startswith(LOW_LEVEL_EXPORT_NOTICE)
    assert xao.startswith(LOW_LEVEL_EXPORT_NOTICE)
    assert render.startswith(LOW_LEVEL_EXPORT_NOTICE)
    assert render_backslash.startswith(LOW_LEVEL_EXPORT_NOTICE)
    assert "Invalid output path" in gerber
    assert "Invalid output path" in step
    assert "Invalid output path" in stepz
    assert "Invalid output path" in xao
    assert "Invalid output path" in render
    assert "Invalid output path" in render_backslash


@pytest.mark.anyio
async def test_export_step_and_render_keep_relative_names_under_output_dir(
    sample_project,
    monkeypatch,
) -> None:
    commands: list[list[str]] = []

    def fake_run(cmd, *args: object, **kwargs: object):
        _ = args, kwargs
        commands.append(list(cmd))
        if "render" in cmd and "--output" in cmd:
            output_path = Path(cmd[cmd.index("--output") + 1])
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)

        class Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return Result()

    monkeypatch.setattr("kicad_mcp.tools.export.subprocess.run", fake_run)
    monkeypatch.setattr(
        "kicad_mcp.tools.export.get_cli_capabilities",
        lambda _cli: CliCapabilities(
            version="KiCad 10.0.1",
            gerber_command="gerbers",
            drill_command="drill",
            position_command="pos",
            supports_step=True,
            supports_stepz=True,
            supports_xao=True,
            supports_render=True,
        ),
    )
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    step = await call_tool_text(server, "export_step", {"output_path": "board.step"})
    stepz = await call_tool_text(server, "export_stepz", {"output_path": "board.stepz"})
    xao = await call_tool_text(server, "export_xao", {"output_path": "board.xao"})
    render_content = await call_tool_content(
        server,
        "export_3d_render",
        {"output_file": "render.png"},
    )
    render = tool_text(render_content)

    assert step.startswith(LOW_LEVEL_EXPORT_NOTICE)
    assert stepz.startswith(LOW_LEVEL_EXPORT_NOTICE)
    assert xao.startswith(LOW_LEVEL_EXPORT_NOTICE)
    assert render.startswith(LOW_LEVEL_EXPORT_NOTICE)
    assert "STEP model exported" in step
    assert "STEPZ model exported" in stepz
    assert "XAO model exported" in xao
    assert "Rendered board image exported" in render
    image = next(item for item in render_content if isinstance(item, ImageContent))
    assert image.mimeType == "image/png"
    assert image.data
    assert str(sample_project / "output" / "3d" / "board.step") in commands[0]
    assert "stpz" in commands[1]
    assert str(sample_project / "output" / "3d" / "board.stepz") in commands[1]
    assert "xao" in commands[2]
    assert str(sample_project / "output" / "3d" / "board.xao") in commands[2]
    assert str(sample_project / "output" / "3d" / "render.png") in commands[3]


@pytest.mark.anyio
async def test_export_3d_pdf_and_bom_forward_active_variant_to_cli(
    sample_project,
    monkeypatch,
) -> None:
    commands: list[list[str]] = []

    def fake_run(cmd, *args: object, **kwargs: object):
        _ = args, kwargs
        commands.append(list(cmd))
        command_blob = " ".join(str(part) for part in cmd)
        if "3dpdf" in command_blob:
            out_file = sample_project / "output" / "3d" / "board-3d.pdf"
            out_file.parent.mkdir(parents=True, exist_ok=True)
            out_file.write_text("pdf", encoding="utf-8")
        if " bom " in f" {command_blob} ":
            out_file = sample_project / "output" / "bom.csv"
            out_file.parent.mkdir(parents=True, exist_ok=True)
            out_file.write_text("ref,value\nR1,10k\n", encoding="utf-8")

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
            supports_3d_pdf=True,
            supports_spice_netlist=True,
            supports_cli_variant=True,
        ),
    )

    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})
    await call_tool_text(server, "variant_create", {"name": "lite"})
    await call_tool_text(server, "variant_set_active", {"name": "lite"})

    pdf_result = await call_tool_text(server, "pcb_export_3d_pdf", {})
    bom_result = await call_tool_text(server, "export_bom", {"format": "csv"})

    assert pdf_result.startswith(LOW_LEVEL_EXPORT_NOTICE)
    assert bom_result.startswith(LOW_LEVEL_EXPORT_NOTICE)
    assert any("--variant" in command and "lite" in command for command in commands)


@pytest.mark.anyio
async def test_export_odb_uses_kicad_10_odb_cli_surface(sample_project, monkeypatch) -> None:
    commands: list[list[str]] = []

    def fake_run(cmd, *args: object, **kwargs: object):
        _ = args, kwargs
        commands.append(list(cmd))
        command_blob = " ".join(str(part) for part in cmd)
        if " odb " in f" {command_blob} ":
            out_file = sample_project / "output" / "manufacturing" / "board.odb.zip"
            out_file.parent.mkdir(parents=True, exist_ok=True)
            out_file.write_text("odb", encoding="utf-8")

        class Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return Result()

    monkeypatch.setattr("kicad_mcp.tools.export.subprocess.run", fake_run)
    monkeypatch.setattr(
        "kicad_mcp.tools.export.get_cli_capabilities",
        lambda _cli: CliCapabilities(
            version="KiCad 10.0.1",
            supports_odb_export=True,
            supports_cli_variant=True,
        ),
    )

    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})
    await call_tool_text(server, "variant_create", {"name": "fab"})
    await call_tool_text(server, "variant_set_active", {"name": "fab"})

    text = await call_tool_text(server, "export_odb", {})

    assert text.startswith(LOW_LEVEL_EXPORT_NOTICE)
    assert "ODB++ exported" in text
    assert commands
    assert commands[0][3] == "odb"
    assert "--compression" in commands[0]
    assert "--variant" in commands[0] and "fab" in commands[0]


@pytest.mark.anyio
async def test_export_odb_reports_unsupported_cli(sample_project, monkeypatch) -> None:
    monkeypatch.setattr(
        "kicad_mcp.tools.export.get_cli_capabilities",
        lambda _cli: CliCapabilities(version="KiCad 9.0.7", supports_odb_export=False),
    )

    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    text = await call_tool_text(server, "export_odb", {})

    assert text.startswith(LOW_LEVEL_EXPORT_NOTICE)
    assert "ODB++ export is not supported" in text


@pytest.mark.anyio
async def test_low_level_exports_include_debug_notice(sample_project, monkeypatch) -> None:
    def fake_run(cmd, *args: object, **kwargs: object):
        _ = args, kwargs
        command_blob = " ".join(str(part) for part in cmd)
        output_path = sample_project / "output"
        if "gerber" in command_blob:
            out_dir = output_path / "gerber"
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / "demo-F_Cu.gbr").write_text("gerber", encoding="utf-8")
        elif "drill" in command_blob:
            out_dir = output_path / "gerber"
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / "demo.drl").write_text("drill", encoding="utf-8")
        elif "bom" in command_blob:
            output_path.mkdir(parents=True, exist_ok=True)
            (output_path / "bom.csv").write_text("ref,value\nR1,10k\n", encoding="utf-8")

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

    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    gerber = await call_tool_text(
        server,
        "export_gerber",
        {"output_subdir": "gerber", "layers": []},
    )
    drill = await call_tool_text(server, "export_drill", {"output_subdir": "gerber"})
    bom = await call_tool_text(server, "export_bom", {"format": "csv"})

    assert gerber.startswith(LOW_LEVEL_EXPORT_NOTICE)
    assert "Gerber export completed" in gerber
    assert drill.startswith(LOW_LEVEL_EXPORT_NOTICE)
    assert "Drill export completed" in drill
    assert bom.startswith(LOW_LEVEL_EXPORT_NOTICE)
    assert "BOM exported" in bom


@pytest.mark.anyio
async def test_export_bom_consolidates_flat_schematic_siblings(sample_project, monkeypatch) -> None:
    (sample_project / "demo.kicad_sch").write_text(
        """(kicad_sch
  (version 20250316)
  (symbol
    (lib_id "Device:R")
    (at 25.4 25.4 0)
    (unit 1)
    (exclude_from_sim no)
    (in_bom yes)
    (on_board yes)
    (dnp no)
    (property "Reference" "R1" (at 0 0 0))
    (property "Value" "10k" (at 0 0 0))
    (property "Footprint" "Resistor_SMD:R_0805" (at 0 0 0))
    (property "LCSC" "C25804" (at 0 0 0))
    (property "MPN" "RC0805FR-0710KL" (at 0 0 0))
    (property "Manufacturer" "YAGEO" (at 0 0 0))
  )
)
""",
        encoding="utf-8",
    )
    (sample_project / "second.kicad_sch").write_text(
        """(kicad_sch
  (version 20250316)
  (symbol
    (lib_id "Device:C")
    (at 50.8 25.4 0)
    (unit 1)
    (exclude_from_sim no)
    (in_bom yes)
    (on_board yes)
    (dnp yes)
    (property "Reference" "C1" (at 0 0 0))
    (property "Value" "100n" (at 0 0 0))
    (property "Footprint" "Capacitor_SMD:C_0805" (at 0 0 0))
    (property "LCSC" "C49678" (at 0 0 0))
    (property "MPN" "CL21B104KBCNNNC" (at 0 0 0))
    (property "Manufacturer" "Samsung" (at 0 0 0))
  )
)
""",
        encoding="utf-8",
    )

    class FakeBackend:
        def parse_schematic_file(self, sch_file):
            reference = "R1" if sch_file.name == "demo.kicad_sch" else "C1"
            value = "10k" if reference == "R1" else "100n"
            footprint = "Resistor_SMD:R_0805" if reference == "R1" else "Capacitor_SMD:C_0805"
            return {
                "symbols": [
                    {
                        "reference": reference,
                        "value": value,
                        "footprint": footprint,
                        "lib_id": "Device:R" if reference == "R1" else "Device:C",
                    }
                ]
            }

    monkeypatch.setattr("kicad_mcp.tools.library.get_schematic_backend", lambda: FakeBackend())

    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    bom = await call_tool_text(server, "export_bom", {"format": "csv"})

    assert "Consolidated 2 reference(s) from 2 schematic files" in bom
    assert "R1" in bom
    assert "C1" in bom
    assert "mpn" in bom
    assert "manufacturer" in bom
    assert "populate" in bom
    assert "RC0805FR-0710KL" in bom
    assert "CL21B104KBCNNNC" in bom
    assert "YAGEO" in bom
    assert "Samsung" in bom
    assert "DNP" in bom


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
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})
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
        "kicad_mcp.tools.validation._is_project_empty",
        lambda: False,
    )
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
async def test_export_manufacturing_package_requires_approval_evidence_after_gate_pass(
    sample_project,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "kicad_mcp.tools.validation._evaluate_project_gate",
        lambda **_kwargs: [GateOutcome(name="Project", status="PASS", summary="ready")],
    )

    server = build_server("manufacturing")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    text = await call_tool_text(server, "export_manufacturing_package", {})

    assert "hard-blocked" in text
    assert "approval_evidence_path" in text
    assert "Gerber export completed" not in text


@pytest.mark.anyio
async def test_export_manufacturing_package_rejects_incomplete_approval_evidence(
    sample_project,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "kicad_mcp.tools.validation._evaluate_project_gate",
        lambda **_kwargs: [GateOutcome(name="Project", status="PASS", summary="ready")],
    )
    evidence_dir = sample_project / ".kicad-mcp"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    (evidence_dir / "manufacturing_approval.json").write_text(
        json.dumps({"approved_by": "Reviewer"}),
        encoding="utf-8",
    )

    server = build_server("manufacturing")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    text = await call_tool_text(
        server,
        "export_manufacturing_package",
        {"approval_evidence_path": ".kicad-mcp/manufacturing_approval.json"},
    )

    assert "Manufacturing evidence is missing" in text
    assert "approved_at_utc" in text
    assert "approval_scope" in text
    assert "Gerber export completed" not in text


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
            "(at 10 6 0) (effects (font (size 1.27 1.27))))\n"
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
            "\t(version 20250216)\n"
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
async def test_validate_footprints_vs_schematic_consolidates_flat_siblings(
    sample_project,
    monkeypatch,
) -> None:
    (sample_project / "second.kicad_sch").write_text(
        (sample_project / "demo.kicad_sch").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (sample_project / "demo.kicad_pcb").write_text(
        (
            "(kicad_pcb\n"
            '\t(footprint "Resistor_SMD:R_0805"\n'
            '\t\t(property "Reference" "R1" (at 0 0 0) (layer "F.SilkS"))\n'
            "\t)\n"
            '\t(footprint "Capacitor_SMD:C_0805"\n'
            '\t\t(property "Reference" "C1" (at 0 0 0) (layer "F.SilkS"))\n'
            "\t)\n"
            ")\n"
        ),
        encoding="utf-8",
    )

    def fake_parse(sch_file):
        reference = "R1" if sch_file.name == "demo.kicad_sch" else "C1"
        footprint = "Resistor_SMD:R_0805" if reference == "R1" else "Capacitor_SMD:C_0805"
        return {"symbols": [{"reference": reference, "footprint": footprint}]}

    def raise_no_ipc():
        raise KiCadConnectionError("no board")

    monkeypatch.setattr("kicad_mcp.tools.validation.get_board", raise_no_ipc)
    monkeypatch.setattr("kicad_mcp.tools.schematic.parse_schematic_file", fake_parse)

    server = build_server("manufacturing")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    text = await call_tool_text(server, "validate_footprints_vs_schematic", {})

    assert "- Status: PASS" in text
    assert "Schematic files scanned: 2" in text
    assert "PCB footprint refs (file): 2" in text


@pytest.mark.anyio
async def test_pcb_placement_quality_gate_detects_overlap(sample_project) -> None:
    (sample_project / "demo.kicad_pcb").write_text(
        (
            "(kicad_pcb\n"
            "\t(version 20250216)\n"
            '\t(generator "pytest")\n'
            "\t(gr_rect (start 0 0) (end 20 20) (stroke (width 0.05) (type solid)) "
            '(fill no) (layer "Edge.Cuts"))\n'
            '\t(footprint "Resistor_SMD:R_0805"\n'
            '\t\t(layer "F.Cu")\n'
            "\t\t(at 5 5 0)\n"
            '\t\t(property "Reference" "R1" (at 0 0 0) (layer "F.SilkS"))\n'
            '\t\t(property "Value" "10k" (at 0 1 0) (layer "F.Fab"))\n'
            "\t\t(fp_rect (start -2 -1) (end 2 1) (stroke (width 0.05) (type solid)) "
            '(fill no) (layer "F.CrtYd"))\n'
            "\t)\n"
            '\t(footprint "Resistor_SMD:R_0805"\n'
            '\t\t(layer "F.Cu")\n'
            "\t\t(at 5.5 5 0)\n"
            '\t\t(property "Reference" "R2" (at 0 0 0) (layer "F.SilkS"))\n'
            '\t\t(property "Value" "10k" (at 0 1 0) (layer "F.Fab"))\n'
            "\t\t(fp_rect (start -2 -1) (end 2 1) (stroke (width 0.05) (type solid)) "
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
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    text = await call_tool_text(server, "export_pcb_pdf", {})

    assert text.startswith(LOW_LEVEL_EXPORT_NOTICE)
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
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    text = await call_tool_text(server, "export_pcb_pdf", {"layers": ["F.Cu", "Edge.Cuts"]})

    assert text.startswith(LOW_LEVEL_EXPORT_NOTICE)
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
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    text = await call_tool_text(server, "export_netlist", {"format": "kicad"})

    assert text.startswith(LOW_LEVEL_EXPORT_NOTICE)
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
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    text = await call_tool_text(server, "export_svg", {"layer": "Edge.Cuts"})

    assert text.startswith(LOW_LEVEL_EXPORT_NOTICE)
    assert "SVG export completed" in text
    assert commands
    assert "--mode-multi" in commands[0]
    assert "--input" not in commands[0]


@pytest.mark.anyio
async def test_validate_footprints_vs_schematic_uses_file_fallback_when_collection_unavailable(
    sample_project,
    monkeypatch,
) -> None:
    (sample_project / "demo.kicad_sch").write_text(
        '(kicad_sch (symbol (property "Reference" "R1")))\n',
        encoding="utf-8",
    )
    (sample_project / "demo.kicad_pcb").write_text(
        '(kicad_pcb (footprint "Resistor_SMD:R_0805" '
        '(property "Reference" "R1" (at 0 0 0) (layer "F.SilkS"))))\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "kicad_mcp.tools.validation.get_board",
        lambda: object(),
    )

    server = build_server("manufacturing")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    text = await call_tool_text(server, "validate_footprints_vs_schematic", {})

    assert "PCB footprint refs (file): 1" in text
