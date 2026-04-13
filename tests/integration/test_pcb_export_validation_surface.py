from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from kipy.proto.board.board_types_pb2 import BoardLayer, ViaType

from kicad_mcp.config import get_config
from kicad_mcp.discovery import CliCapabilities, get_cli_capabilities
from kicad_mcp.server import build_server
from tests.conftest import call_tool_text


def _field(value: str) -> SimpleNamespace:
    return SimpleNamespace(text=SimpleNamespace(value=value))


def _configure_mock_board(mock_board) -> None:
    track = SimpleNamespace(
        start=SimpleNamespace(x_nm=0, y_nm=0),
        end=SimpleNamespace(x_nm=1_000_000, y_nm=0),
        layer=BoardLayer.BL_F_Cu,
        width=250_000,
        net=SimpleNamespace(name="NET1"),
        id=SimpleNamespace(value="track-12345678"),
    )
    track_usb_p = SimpleNamespace(
        start=SimpleNamespace(x_nm=0, y_nm=1_000_000),
        end=SimpleNamespace(x_nm=10_000_000, y_nm=1_000_000),
        layer=BoardLayer.BL_F_Cu,
        width=200_000,
        net=SimpleNamespace(name="USB_DP"),
        id=SimpleNamespace(value="track-usb-dp"),
    )
    track_usb_n = SimpleNamespace(
        start=SimpleNamespace(x_nm=0, y_nm=2_000_000),
        end=SimpleNamespace(x_nm=9_700_000, y_nm=2_000_000),
        layer=BoardLayer.BL_F_Cu,
        width=200_000,
        net=SimpleNamespace(name="USB_DN"),
        id=SimpleNamespace(value="track-usb-dn"),
    )
    via = SimpleNamespace(
        position=SimpleNamespace(x_nm=500_000, y_nm=500_000),
        diameter=800_000,
        drill_diameter=400_000,
        net=SimpleNamespace(name="NET1"),
        type=ViaType.VT_THROUGH,
    )
    footprint_1 = SimpleNamespace(
        reference_field=_field("R1"),
        value_field=_field("10k"),
        position=SimpleNamespace(x_nm=1_000_000, y_nm=2_000_000),
        layer=BoardLayer.BL_F_Cu,
        id=SimpleNamespace(value="footprint-r1"),
        angle=None,
    )
    footprint_2 = SimpleNamespace(
        reference_field=_field("U2"),
        value_field=_field("MCU"),
        position=SimpleNamespace(x_nm=3_000_000, y_nm=4_000_000),
        layer=BoardLayer.BL_B_Cu,
        id=SimpleNamespace(value="footprint-u2"),
        orientation=0.0,
    )
    pad_1 = SimpleNamespace(
        parent=footprint_1,
        number="1",
        net=SimpleNamespace(name="NET1"),
        position=SimpleNamespace(x_nm=1_000_000, y_nm=2_000_000),
    )
    pad_2 = SimpleNamespace(
        parent=footprint_2,
        number="3",
        net=SimpleNamespace(name="NET1"),
        position=SimpleNamespace(x_nm=3_000_000, y_nm=4_000_000),
    )
    zone = SimpleNamespace(
        name="GND_FILL",
        net=SimpleNamespace(name="GND"),
        layer=BoardLayer.BL_F_Cu,
    )
    shape = SimpleNamespace(layer=BoardLayer.BL_Edge_Cuts)
    stackup = SimpleNamespace(
        layers=[SimpleNamespace(layer=BoardLayer.BL_F_Cu, thickness=35_000, material_name="Copper")]
    )

    mock_board.get_tracks.return_value = [track, track_usb_p, track_usb_n]
    mock_board.get_vias.return_value = [via]
    mock_board.get_footprints.return_value = [footprint_1, footprint_2]
    mock_board.get_nets.return_value = [
        SimpleNamespace(name="NET1"),
        SimpleNamespace(name="GND"),
        SimpleNamespace(name="USB_DP"),
        SimpleNamespace(name="USB_DN"),
        SimpleNamespace(name="HS"),
    ]
    mock_board.get_zones.return_value = [zone]
    mock_board.get_shapes.return_value = [shape]
    mock_board.get_pads.return_value = [pad_1, pad_2]
    mock_board.get_enabled_layers.return_value = [BoardLayer.BL_F_Cu, BoardLayer.BL_B_Cu]
    mock_board.get_selection.return_value = [track, footprint_1]
    mock_board.get_stackup.return_value = stackup
    mock_board.get_as_string.return_value = "(kicad_pcb)" + ("x" * 60_000)


def _fake_cli_run_factory(sample_project: Path):
    def fake_run(
        cmd: list[str],
        capture_output: bool,
        text: bool,
        timeout: float,
        check: bool,
    ) -> subprocess.CompletedProcess[str]:
        _ = (capture_output, text, timeout, check)
        if "--version" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout="KiCad 10.0.1", stderr="")

        output_path = None
        if "--output" in cmd:
            output_path = Path(cmd[cmd.index("--output") + 1])

        if "gerber" in cmd or "gerbers" in cmd:
            assert output_path is not None
            output_path.mkdir(parents=True, exist_ok=True)
            (output_path / "demo-F_Cu.gbr").write_text("gerber", encoding="utf-8")
        elif "drill" in cmd:
            assert output_path is not None
            output_path.mkdir(parents=True, exist_ok=True)
            (output_path / "demo.drl").write_text("drill", encoding="utf-8")
        elif "bom" in cmd or "python-bom" in cmd:
            assert output_path is not None
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text("Ref,Value\nR1,10k\n", encoding="utf-8")
        elif "netlist" in cmd:
            assert output_path is not None
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text("(export netlist)", encoding="utf-8")
        elif "pdf" in cmd:
            assert output_path is not None
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text("pdf", encoding="utf-8")
        elif "step" in cmd:
            assert output_path is not None
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text("step", encoding="utf-8")
        elif "render" in cmd:
            assert output_path is not None
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text("png", encoding="utf-8")
        elif "pos" in cmd or "positions" in cmd:
            assert output_path is not None
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text("ref,x,y\nR1,1,2\n", encoding="utf-8")
        elif "ipc2581" in cmd:
            assert output_path is not None
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text("<ipc2581/>", encoding="utf-8")
        elif "svg" in cmd:
            assert output_path is not None
            output_path.mkdir(parents=True, exist_ok=True)
            (output_path / "board.svg").write_text("<svg/>", encoding="utf-8")
        elif "dxf" in cmd:
            assert output_path is not None
            output_path.mkdir(parents=True, exist_ok=True)
            (output_path / "board.dxf").write_text("0\nSECTION\n", encoding="utf-8")
        elif "stats" in cmd:
            assert output_path is not None
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text("Board size: 50 x 50 mm", encoding="utf-8")
        elif "drc" in cmd:
            assert output_path is not None
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                json.dumps(
                    {
                        "violations": [
                            {"severity": "error", "description": "Silk pad overlap"},
                            {"severity": "warning", "description": "Clearance"},
                        ],
                        "unconnected_items": [{"severity": "error", "description": "NET1"}],
                        "items_not_passing_courtyard": [
                            {"severity": "warning", "description": "Courtyard overlap"}
                        ],
                    }
                ),
                encoding="utf-8",
            )
        elif "erc" in cmd:
            assert output_path is not None
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                json.dumps(
                    {"violations": [{"severity": "error", "description": "Missing driver"}]}
                ),
                encoding="utf-8",
            )
        elif "--help" in cmd:
            return subprocess.CompletedProcess(
                cmd,
                0,
                stdout="gerber drill positions ipc2581 svg dxf step render spice",
                stderr="",
            )

        return subprocess.CompletedProcess(cmd, 0, stdout=str(sample_project), stderr="")

    return fake_run


@pytest.mark.anyio
async def test_pcb_and_routing_surface(
    sample_project: Path,
    mock_board,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_mock_board(mock_board)
    server = build_server("pcb")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})
    (sample_project / "demo.dsn").write_text("dsn", encoding="utf-8")

    def fake_freerouting_run(
        cmd: list[str],
        capture_output: bool,
        text: bool,
        timeout: float,
        check: bool,
    ) -> subprocess.CompletedProcess[str]:
        _ = (capture_output, text, timeout, check)
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
        return subprocess.CompletedProcess(cmd, 0, stdout="autorouted", stderr="")

    monkeypatch.setattr("kicad_mcp.utils.freerouting.subprocess.run", fake_freerouting_run)

    cfg = get_config()
    cfg.enable_experimental_tools = True

    summary = await call_tool_text(server, "pcb_get_board_summary", {})
    tracks = await call_tool_text(server, "pcb_get_tracks", {})
    vias = await call_tool_text(server, "pcb_get_vias", {})
    footprints = await call_tool_text(server, "pcb_get_footprints", {})
    nets = await call_tool_text(server, "pcb_get_nets", {})
    zones = await call_tool_text(server, "pcb_get_zones", {})
    shapes = await call_tool_text(server, "pcb_get_shapes", {})
    pads = await call_tool_text(server, "pcb_get_pads", {})
    layers = await call_tool_text(server, "pcb_get_layers", {})
    stackup = await call_tool_text(server, "pcb_get_stackup", {})
    selection = await call_tool_text(server, "pcb_get_selection", {})
    board_text = await call_tool_text(server, "pcb_get_board_as_string", {})
    ratsnest = await call_tool_text(server, "pcb_get_ratsnest", {})
    rules = await call_tool_text(server, "pcb_get_design_rules", {})

    assert "Board summary" in summary
    assert "Tracks (3 total)" in tracks
    assert "Vias (1 total)" in vias
    assert "Footprints (2 total)" in footprints
    assert "NET1" in nets
    assert "GND_FILL" in zones
    assert "Shapes (1 total)" in shapes
    assert "Pads (2 total)" in pads
    assert "Enabled layers" in layers
    assert "Board stackup" in stackup
    assert "Selected items" in selection
    assert "[truncated]" in board_text
    assert "ratsnest" in ratsnest.lower()
    assert "(rules)" in rules

    add_results = [
        await call_tool_text(
            server,
            "pcb_add_track",
            {
                "x1_mm": 0.0,
                "y1_mm": 0.0,
                "x2_mm": 10.0,
                "y2_mm": 0.0,
                "layer": "F_Cu",
                "width_mm": 0.25,
                "net_name": "NET1",
            },
        ),
        await call_tool_text(
            server,
            "pcb_add_tracks_bulk",
            {"tracks": [{"x1": 0.0, "y1": 1.0, "x2": 10.0, "y2": 1.0, "net": "NET1"}]},
        ),
        await call_tool_text(
            server,
            "pcb_add_via",
            {"x_mm": 5.0, "y_mm": 5.0, "diameter_mm": 0.8, "drill_mm": 0.4, "net_name": "NET1"},
        ),
        await call_tool_text(
            server,
            "pcb_add_segment",
            {"x1_mm": 0.0, "y1_mm": 0.0, "x2_mm": 5.0, "y2_mm": 5.0, "layer": "Edge_Cuts"},
        ),
        await call_tool_text(
            server,
            "pcb_add_circle",
            {"cx_mm": 2.0, "cy_mm": 2.0, "radius_mm": 1.0, "layer": "Edge_Cuts"},
        ),
        await call_tool_text(
            server,
            "pcb_add_rectangle",
            {"x1_mm": 0.0, "y1_mm": 0.0, "x2_mm": 5.0, "y2_mm": 5.0, "layer": "Edge_Cuts"},
        ),
        await call_tool_text(
            server,
            "pcb_set_board_outline",
            {"width_mm": 50.0, "height_mm": 40.0, "origin_x_mm": 0.0, "origin_y_mm": 0.0},
        ),
        await call_tool_text(
            server,
            "pcb_add_text",
            {"text": "HELLO", "x_mm": 1.0, "y_mm": 1.0, "layer": "F_SilkS", "size_mm": 1.0},
        ),
        await call_tool_text(server, "pcb_delete_items", {"item_ids": ["abc-def"]}),
        await call_tool_text(server, "pcb_save", {}),
        await call_tool_text(server, "pcb_refill_zones", {}),
        await call_tool_text(server, "pcb_highlight_net", {"net_name": "NET1"}),
        await call_tool_text(
            server,
            "pcb_set_net_class",
            {"net_name": "NET1", "class_name": "Default"},
        ),
        await call_tool_text(
            server,
            "pcb_move_footprint",
            {"reference": "R1", "x_mm": 12.0, "y_mm": 6.0, "rotation_deg": 90.0},
        ),
        await call_tool_text(
            server,
            "pcb_set_footprint_layer",
            {"reference": "R1", "layer": "B_Cu"},
        ),
        await call_tool_text(
            server,
            "route_single_track",
            {"x1_mm": 0.0, "y1_mm": 0.0, "x2_mm": 5.0, "y2_mm": 5.0, "layer": "F_Cu"},
        ),
        await call_tool_text(
            server,
            "route_from_pad_to_pad",
            {"ref1": "R1", "pad1": "1", "ref2": "U2", "pad2": "3", "layer": "F_Cu"},
        ),
    ]

    assert any("successfully" in result.lower() for result in add_results)
    assert any("route from" in result.lower() for result in add_results)
    assert mock_board.create_items.called
    assert mock_board.remove_items_by_id.called
    assert mock_board.save.called
    assert mock_board.refill_zones.called

    routing_results = [
        await call_tool_text(
            server,
            "route_export_dsn",
            {"output_path": "output/routing/board.dsn"},
        ),
        await call_tool_text(
            server,
            "route_autoroute_freerouting",
            {
                "dsn_path": "output/routing/board.dsn",
                "ses_path": "output/routing/board.ses",
                "net_classes_to_ignore": ["GND", "PWR"],
                "use_docker": True,
            },
        ),
        await call_tool_text(server, "route_import_ses", {"ses_path": "output/routing/board.ses"}),
        await call_tool_text(
            server,
            "route_set_net_class_rules",
            {
                "net_class": "HS",
                "width_mm": 0.2,
                "clearance_mm": 0.15,
                "via_diameter_mm": 0.5,
                "via_drill_mm": 0.25,
            },
        ),
        await call_tool_text(
            server,
            "route_differential_pair",
            {
                "net_p": "USB_DP",
                "net_n": "USB_DN",
                "layer": "F_Cu",
                "width_mm": 0.2,
                "gap_mm": 0.18,
                "length_tolerance_mm": 0.1,
            },
        ),
        await call_tool_text(
            server,
            "route_tune_length",
            {
                "net_name": "NET1",
                "target_mm": 5.0,
                "meander_amplitude_mm": 0.8,
            },
        ),
        await call_tool_text(
            server, "tune_track_length", {"net_name": "NET1", "target_length_mm": 5.0}
        ),
        await call_tool_text(
            server,
            "tune_diff_pair_length",
            {"net_name_p": "USB_DP", "net_name_n": "USB_DN", "target_length_mm": 10.0},
        ),
    ]

    joined_routing = "\n".join(routing_results)
    assert "Specctra DSN ready" in joined_routing
    assert "FreeRouting completed successfully" in joined_routing
    assert "Specctra SES session staged" in joined_routing
    assert "Net-class routing rule" in joined_routing
    assert "Differential-pair routing rule" in joined_routing
    assert "Length-tuning rule" in joined_routing
    assert "Differential-pair length rules updated" in joined_routing
    assert (sample_project / "demo.kicad_dru").read_text(encoding="utf-8").count("(rule ") >= 4


@pytest.mark.anyio
async def test_export_and_validation_surface(
    sample_project: Path,
    mock_board,
    monkeypatch,
) -> None:
    _configure_mock_board(mock_board)
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
    get_cli_capabilities.cache_clear()

    server = build_server("manufacturing")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    outputs = [
        await call_tool_text(server, "export_gerber", {"output_subdir": "gerber", "layers": []}),
        await call_tool_text(server, "export_drill", {"output_subdir": "gerber"}),
        await call_tool_text(server, "export_bom", {"format": "csv"}),
        await call_tool_text(server, "export_netlist", {"format": "kicad"}),
        await call_tool_text(server, "export_spice_netlist", {}),
        await call_tool_text(server, "export_pcb_pdf", {"layers": ["F.Cu"]}),
        await call_tool_text(server, "export_sch_pdf", {}),
        await call_tool_text(server, "export_step", {"output_path": ""}),
        await call_tool_text(server, "export_3d_step", {}),
        await call_tool_text(
            server,
            "export_3d_render",
            {"output_file": "render.png", "side": "top", "zoom": 1.2},
        ),
        await call_tool_text(server, "export_pick_and_place", {"format": "csv"}),
        await call_tool_text(server, "export_ipc2581", {}),
        await call_tool_text(server, "export_svg", {"layer": "F.Cu"}),
        await call_tool_text(server, "export_dxf", {"layer": "Edge.Cuts"}),
        await call_tool_text(server, "get_board_stats", {}),
        await call_tool_text(server, "export_manufacturing_package", {}),
        await call_tool_text(server, "run_drc", {"save_report": True}),
        await call_tool_text(server, "run_erc", {"save_report": True}),
        await call_tool_text(server, "validate_design", {}),
        await call_tool_text(server, "check_design_for_manufacture", {"jlcpcb": True}),
        await call_tool_text(server, "check_design_for_manufacture", {"jlcpcb": False}),
        await call_tool_text(server, "get_unconnected_nets", {}),
        await call_tool_text(server, "get_courtyard_violations", {}),
        await call_tool_text(server, "get_silk_to_pad_violations", {}),
        await call_tool_text(server, "validate_footprints_vs_schematic", {}),
    ]

    joined = "\n".join(outputs)
    assert "Gerber export completed" in joined
    assert "Drill export completed" in joined
    assert "BOM exported" in joined
    assert "Netlist exported" in joined
    assert "PCB PDF exported" in joined
    assert "Schematic PDF exported" in joined
    assert "STEP model exported" in joined
    assert "Rendered board image" in joined
    assert "Pick and place data exported" in joined
    assert "IPC-2581 exported" in joined
    assert "SVG export completed" in joined
    assert "DXF export completed" in joined
    assert "Board size: 50 x 50 mm" in joined
    assert "DRC summary" in joined
    assert "ERC summary" in joined
    assert "Design validation summary" in joined
    assert "DFM check" in joined
    assert "Unconnected nets" in joined
    assert "Courtyard violations" in joined
    assert "Silk-to-pad violations" in joined
    assert "Footprint versus schematic comparison" in joined
