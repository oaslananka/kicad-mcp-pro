from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from kipy.proto.board.board_types_pb2 import BoardLayer, ViaType

from kicad_mcp.config import get_config
from kicad_mcp.connection import KiCadConnectionError
from kicad_mcp.discovery import CliCapabilities, get_cli_capabilities
from kicad_mcp.server import build_server
from kicad_mcp.tools.export import LOW_LEVEL_EXPORT_NOTICE
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
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        _ = (capture_output, text, timeout, check)
        _ = kwargs
        if "--version" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout="KiCad 10.0.1", stderr="")
        if "--help" in cmd:
            return subprocess.CompletedProcess(
                cmd,
                0,
                stdout="gerber drill positions ipc2581 svg dxf step stpz xao render spice",
                stderr="",
            )

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
        elif "step" in cmd or "stpz" in cmd:
            assert output_path is not None
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text("step", encoding="utf-8")
        elif "xao" in cmd:
            assert output_path is not None
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text("xao", encoding="utf-8")
        elif "render" in cmd:
            assert output_path is not None
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text("png", encoding="utf-8")
        elif "pos" in cmd or "positions" in cmd:
            assert output_path is not None
            output_path.mkdir(parents=True, exist_ok=True)
            (output_path / "demo-pos.csv").write_text("ref,x,y\nR1,1,2\n", encoding="utf-8")
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

        return subprocess.CompletedProcess(cmd, 0, stdout=str(sample_project), stderr="")

    return fake_run


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
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        _ = (capture_output, text, timeout, check)
        _ = kwargs
        if "--version" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout="KiCad 10.0.1", stderr="")
        if "--help" in cmd:
            return subprocess.CompletedProcess(
                cmd,
                0,
                stdout="gerbers positions ipc2581 svg dxf step stpz xao render spice",
                stderr="",
            )
        ses_path = Path(cmd[cmd.index("-do") + 1])
        if "docker" in cmd[0]:
            ses_path = sample_project / "output" / "routing" / ses_path.name
        ses_path.parent.mkdir(parents=True, exist_ok=True)
        ses_path.write_text("ses", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout="autorouted", stderr="")

    monkeypatch.setattr("kicad_mcp.utils.freerouting.subprocess.run", fake_freerouting_run)
    monkeypatch.setattr("kicad_mcp.utils.freerouting._docker_available", lambda _: True)

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
        await call_tool_text(server, "route_tune_length", {"net_name": "NET1", "target_mm": 5.0}),
        await call_tool_text(
            server,
            "tune_diff_pair_length",
            {"net_name_p": "USB_DP", "net_name_n": "USB_DN", "target_length_mm": 10.0},
        ),
    ]

    joined_routing = "\n".join(routing_results)
    assert "Specctra DSN ready" in joined_routing
    # P1-T7: applying the SES is a manual KiCad step, so the route reports honestly.
    assert "FreeRouting produced a routed session" in joined_routing
    assert "Specctra SES session staged" in joined_routing
    assert "Net-class routing rule" in joined_routing
    assert "Differential-pair routing rule" in joined_routing
    assert "Length-tuning rule" in joined_routing
    assert "Differential-pair length rules updated" in joined_routing
    assert (sample_project / "demo.kicad_dru").read_text(encoding="utf-8").count("(rule ") >= 4


@pytest.mark.anyio
async def test_pcb_read_tools_fall_back_to_configured_board_file(
    sample_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (sample_project / "demo.kicad_pcb").write_text(
        (
            "(kicad_pcb\n"
            "\t(version 20250216)\n"
            '\t(generator "pytest")\n'
            "\t(layers\n"
            '\t\t(0 "F.Cu" signal)\n'
            '\t\t(31 "B.Cu" signal)\n'
            '\t\t(32 "B.Adhes" user "B.Adhesive")\n'
            "\t)\n"
            '\t(net 0 "")\n'
            '\t(net 1 "/VIN")\n'
            '\t(net 2 "/LED_A")\n'
            '\t(footprint "Resistor_SMD:R_0805"\n'
            '\t\t(layer "F.Cu")\n'
            "\t\t(at 10 10 0)\n"
            '\t\t(property "Reference" "R1" (at 0 0 0))\n'
            '\t\t(property "Value" "1k" (at 0 0 0))\n'
            '\t\t(pad "1" smd rect (at -1 0) (size 1 1) (layers "F.Cu") (net 1 "/VIN"))\n'
            '\t\t(pad "2" smd rect (at 1 0) (size 1 1) (layers "F.Cu") (net 2 "/LED_A"))\n'
            "\t)\n"
            '\t(segment (start 10 10) (end 20 10) (width 0.25) (layer "F.Cu") (net 1))\n'
            '\t(via (at 20 10) (size 0.8) (drill 0.4) (layers "F.Cu" "B.Cu") (net 1))\n'
            '\t(zone (net 1) (net_name "/VIN") (layer "F.Cu") (name "VIN_FILL"))\n'
            ")\n"
        ),
        encoding="utf-8",
    )
    server = build_server("pcb")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    def raise_no_live_board() -> object:
        raise KiCadConnectionError("KiCad is connected but no board is currently open.")

    monkeypatch.setattr("kicad_mcp.tools.pcb.get_board", raise_no_live_board)

    summary = await call_tool_text(server, "pcb_get_board_summary", {})
    tracks = await call_tool_text(server, "pcb_get_tracks", {})
    tracks_filtered_out = await call_tool_text(server, "pcb_get_tracks", {"filter_net": "GND"})
    tracks_out_of_range = await call_tool_text(
        server, "pcb_get_tracks", {"page": 2, "page_size": 1}
    )
    footprints = await call_tool_text(server, "pcb_get_footprints", {})
    footprints_filtered_out = await call_tool_text(
        server, "pcb_get_footprints", {"filter_layer": "B_Cu"}
    )
    footprints_out_of_range = await call_tool_text(
        server, "pcb_get_footprints", {"page": 2, "page_size": 1}
    )
    nets = await call_tool_text(server, "pcb_get_nets", {})
    vias = await call_tool_text(server, "pcb_get_vias", {})
    zones = await call_tool_text(server, "pcb_get_zones", {})
    layers = await call_tool_text(server, "pcb_get_layers", {})
    rules = await call_tool_text(server, "pcb_get_design_rules", {})

    # pcb_get_board_summary now returns a structured VerdictReport (P1-T4); its human
    # text lives in the `text` field. Asserting raw paths against the JSON-serialized
    # text would fail on Windows because backslashes are JSON-escaped, so check the
    # unescaped `text` field directly instead.
    summary_text = json.loads(summary)["text"]
    for text in (
        summary_text,
        tracks,
        tracks_filtered_out,
        tracks_out_of_range,
        footprints,
        footprints_filtered_out,
        footprints_out_of_range,
        nets,
        vias,
        zones,
        layers,
    ):
        assert "file-backed fallback" in text
        assert "- Source: file-backed" in text
        assert "Diagnostics:" in text
        assert "IPC endpoint:" in text
        assert f"Active project path: {sample_project}" in text
        assert f"Board file: {sample_project / 'demo.kicad_pcb'}" in text
        assert "Fallback status: using file-backed .kicad_pcb parser" in text

    assert "- Tracks: 1" in summary_text
    assert "- Footprints: 1" in summary_text
    assert "- Nets: 2" in summary
    assert "Tracks (file-backed fallback, 1 total)" in tracks
    assert "net=/VIN" in tracks
    assert "No tracks match the supplied filters" in tracks_filtered_out
    assert "Track page 2 is out of range" in tracks_out_of_range
    assert "R1 (1k)" in footprints
    assert "No footprints match the supplied layer filter" in footprints_filtered_out
    assert "Footprint page 2 is out of range" in footprints_out_of_range
    assert "- /VIN" in nets
    assert "- /LED_A" in nets
    assert "Vias (file-backed fallback, 1 total)" in vias
    assert "diameter=0.800 mm" in vias
    assert "Zones (file-backed fallback, 1 total)" in zones
    assert "VIN_FILL" in zones
    assert "Enabled layers (file-backed fallback, 3 total)" in layers
    assert "F.Cu" in layers and "B.Cu" in layers
    assert "Design rules (file-backed)" in rules
    assert "- Source: file-backed" in rules
    assert "(rules)" in rules


@pytest.mark.anyio
async def test_pcb_file_fallback_reports_empty_and_missing_board_states(
    sample_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = build_server("pcb")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    def raise_no_live_board() -> object:
        raise KiCadConnectionError("KiCad IPC is reachable but has no board.")

    monkeypatch.setattr("kicad_mcp.tools.pcb.get_board", raise_no_live_board)

    empty_tracks = await call_tool_text(server, "pcb_get_tracks", {})
    empty_footprints = await call_tool_text(server, "pcb_get_footprints", {})
    empty_nets = await call_tool_text(server, "pcb_get_nets", {})
    (sample_project / "demo.kicad_pcb").unlink()
    missing_summary = await call_tool_text(server, "pcb_get_board_summary", {})

    assert "No tracks are present in the file-backed fallback" in empty_tracks
    assert "No footprints are present in the file-backed fallback" in empty_footprints
    assert "No nets are present in the file-backed fallback" in empty_nets
    assert "configured .kicad_pcb file is missing" in missing_summary
    assert "Fallback status: unavailable: board file does not exist" in missing_summary


@pytest.mark.anyio
async def test_pcb_file_fallback_reports_missing_board_configuration(
    fake_cli: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ = fake_cli
    server = build_server("pcb")

    def raise_no_live_board() -> object:
        raise KiCadConnectionError("KiCad IPC is reachable but has no board.")

    monkeypatch.setattr("kicad_mcp.tools.pcb.get_board", raise_no_live_board)

    summary = await call_tool_text(server, "pcb_get_board_summary", {})

    assert "no configured .kicad_pcb file was found" in summary
    assert "Board file: (not configured)" in summary
    assert "Fallback status: unavailable: no configured board file" in summary


@pytest.mark.anyio
async def test_pcb_read_pagination_and_filters(
    sample_project: Path,
    mock_board,
) -> None:
    _configure_mock_board(mock_board)
    server = build_server("pcb")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    page_two = await call_tool_text(
        server,
        "pcb_get_tracks",
        {"page": 2, "page_size": 2},
    )
    usb_dp_only = await call_tool_text(
        server,
        "pcb_get_tracks",
        {"filter_net": "USB_DP"},
    )
    back_footprints = await call_tool_text(
        server,
        "pcb_get_footprints",
        {"filter_layer": "B_Cu"},
    )

    assert "Tracks (3 total)" in page_two
    assert "Page 2/2" in page_two
    assert "USB_DN" in page_two
    assert "track-12345678" not in page_two

    assert "Tracks (1 total)" in usb_dp_only
    assert "USB_DP" in usb_dp_only
    assert "USB_DN" not in usb_dp_only
    assert "NET1" not in usb_dp_only

    assert "Footprints (1 total)" in back_footprints
    assert "U2 (MCU)" in back_footprints
    assert "R1 (10k)" not in back_footprints


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
            supports_stepz=True,
            supports_xao=True,
            supports_render=True,
            supports_spice_netlist=True,
        ),
    )
    get_cli_capabilities.cache_clear()

    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    outputs = [
        await call_tool_text(server, "export_gerber", {"output_subdir": "gerber", "layers": []}),
        await call_tool_text(server, "export_drill", {"output_subdir": "gerber"}),
        await call_tool_text(server, "export_bom", {"format": "csv"}),
        await call_tool_text(server, "export_netlist", {"format": "kicad"}),
        await call_tool_text(server, "export_spice_netlist", {}),
        await call_tool_text(server, "export_pcb_pdf", {"layers": ["F.Cu"]}),
        await call_tool_text(server, "export_sch_pdf", {}),
        await call_tool_text(server, "export_sch_svg", {}),
        await call_tool_text(server, "export_sch_dxf", {}),
        await call_tool_text(server, "export_sch_python_bom", {}),
        await call_tool_text(server, "export_step", {"output_path": ""}),
        await call_tool_text(server, "export_3d_step", {}),
        await call_tool_text(server, "export_stepz", {"output_path": ""}),
        await call_tool_text(server, "export_xao", {"output_path": ""}),
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
        await call_tool_text(
            server,
            "export_manufacturing_package",
            {"approval_evidence_path": _write_manufacturing_approval(sample_project)},
        ),
        await call_tool_text(server, "run_drc", {"save_report": True}),
        await call_tool_text(server, "run_erc", {"save_report": True}),
        await call_tool_text(server, "validate_design", {}),
        await call_tool_text(server, "schematic_quality_gate", {}),
        await call_tool_text(server, "schematic_connectivity_gate", {}),
        await call_tool_text(server, "pcb_quality_gate", {}),
        await call_tool_text(server, "pcb_placement_quality_gate", {}),
        await call_tool_text(server, "pcb_score_placement", {}),
        await call_tool_text(server, "manufacturing_quality_gate", {}),
        await call_tool_text(server, "project_quality_gate", {}),
        await call_tool_text(server, "check_design_for_manufacture", {"jlcpcb": True}),
        await call_tool_text(server, "check_design_for_manufacture", {"jlcpcb": False}),
        await call_tool_text(server, "get_unconnected_nets", {}),
        await call_tool_text(server, "get_courtyard_violations", {}),
        await call_tool_text(server, "get_silk_to_pad_violations", {}),
        await call_tool_text(server, "validate_footprints_vs_schematic", {}),
    ]

    joined = "\n".join(outputs)
    assert LOW_LEVEL_EXPORT_NOTICE in joined
    assert "Gerber export completed" in joined
    assert "Drill export completed" in joined
    assert "BOM exported" in joined
    assert "Netlist exported" in joined
    assert "PCB PDF exported" in joined
    assert "Schematic PDF exported" in joined
    assert "STEP model exported" in joined
    assert "STEPZ model exported" in joined
    assert "XAO model exported" in joined
    assert "Rendered board image" in joined
    assert "Pick and place data exported" in joined
    assert "IPC-2581 exported" in joined
    assert "SVG export completed" in joined
    assert "DXF export completed" in joined
    assert "Board size: 50 x 50 mm" in joined
    assert "hard-blocked" in joined
    assert "DRC summary" in joined
    assert "ERC summary" in joined
    assert "Design validation summary" in joined
    assert "Schematic quality gate" in joined
    assert "Schematic connectivity quality gate" in joined
    assert "PCB quality gate" in joined
    assert "Placement quality gate" in joined
    assert "Placement score:" in joined
    assert "Manufacturing quality gate" in joined
    assert "Project quality gate" in joined
    assert "DFM check" in joined
    assert "Unconnected nets" in joined
    assert "Courtyard violations" in joined
    assert "Silk-to-pad violations" in joined
    assert "Footprint versus schematic comparison" in joined
