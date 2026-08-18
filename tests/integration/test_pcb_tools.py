from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from kipy.proto.board import board_types_pb2
from kipy.proto.board.board_types_pb2 import BoardLayer, ViaType
from kipy.proto.common import types as common_types

from kicad_mcp.file_formats import GENERATED_SEXPR_DIALECT_VERSION
from kicad_mcp.server import build_server
from kicad_mcp.tools.validation import GateOutcome
from kicad_mcp.utils.sexpr import _extract_block
from tests.conftest import call_tool_text


def _footprint_position(pcb_text: str, reference: str) -> tuple[float, float, int]:
    ref_index = pcb_text.find(f'(property "Reference" "{reference}"')
    if ref_index < 0:
        raise AssertionError(f"Could not find footprint reference for {reference}")
    block_start = pcb_text.rfind("(footprint", 0, ref_index)
    if block_start < 0:
        raise AssertionError(f"Could not find footprint block for {reference}")
    block, _ = _extract_block(pcb_text, block_start)
    match = re.search(r"\n\t\t\(at\s+([0-9.\-]+)\s+([0-9.\-]+)\s+(\d+)\)", block)
    if match is None:
        raise AssertionError(f"Could not find placement for {reference}")
    return float(match.group(1)), float(match.group(2)), int(match.group(3))


def _footprint_block(
    name: str,
    reference: str,
    value: str,
    x_mm: float,
    y_mm: float,
    uid: str,
    *,
    width_mm: float = 2.8,
    height_mm: float = 1.8,
) -> str:
    half_width_mm = width_mm / 2
    half_height_mm = height_mm / 2
    return "\n".join(
        [
            f'\t(footprint "{name}"',
            '\t\t(layer "F.Cu")',
            f'\t\t(uuid "{uid}")',
            f"\t\t(at {x_mm} {y_mm} 0)",
            f'\t\t(property "Reference" "{reference}"',
            "\t\t\t(at 0 -1.5 0)",
            '\t\t\t(layer "F.SilkS")',
            "\t\t)",
            f'\t\t(property "Value" "{value}"',
            "\t\t\t(at 0 1.5 0)",
            '\t\t\t(layer "F.Fab")',
            "\t\t)",
            (
                f"\t\t(fp_rect (start {-half_width_mm:.2f} {-half_height_mm:.2f}) "
                f"(end {half_width_mm:.2f} {half_height_mm:.2f}) "
                '(stroke (width 0.05) (type solid)) (fill no) (layer "F.CrtYd"))'
            ),
            "\t)",
        ]
    )


def _board_text(*footprints: str) -> str:
    body = "\n".join(footprints)
    return "\n".join(
        [
            "(kicad_pcb",
            "\t(version 20250216)",
            '\t(generator "pytest")',
            body,
            ")",
            "",
        ]
    )


@pytest.mark.anyio
async def test_pcb_auto_place_force_directed_respects_keepouts() -> None:
    server = build_server("pcb")

    payload = json.loads(
        await call_tool_text(
            server,
            "pcb_auto_place_force_directed",
            {
                "component_positions": [
                    {"ref": "U1", "x": 15.0, "y": 10.0, "w": 4.0, "h": 4.0},
                ],
                "nets": [],
                "board_width_mm": 30.0,
                "board_height_mm": 20.0,
                "iterations": 20,
                "grid_mm": 0.5,
                "keepout_regions": [[12.0, 8.0, 18.0, 12.0]],
            },
        )
    )

    placement = payload["placements"][0]
    x_mm = float(placement["x"])
    y_mm = float(placement["y"])

    assert payload["grid_mm"] == 0.5
    assert x_mm * 2 == round(x_mm * 2)
    assert y_mm * 2 == round(y_mm * 2)
    assert x_mm + 2.0 <= 12.0 or x_mm - 2.0 >= 18.0 or y_mm + 2.0 <= 8.0 or y_mm - 2.0 >= 12.0


def _allow_schematic_sync(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "kicad_mcp.tools.validation._evaluate_schematic_gate",
        lambda: GateOutcome(
            name="Schematic",
            status="PASS",
            summary="ERC is clean.",
            details=["ERC violations: 0"],
        ),
    )
    monkeypatch.setattr(
        "kicad_mcp.tools.validation._evaluate_schematic_connectivity_gate",
        lambda: GateOutcome(
            name="Schematic connectivity",
            status="PASS",
            summary="Connectivity is structurally sound.",
            details=["Zero-wire pages: 0"],
        ),
    )


@pytest.mark.anyio
async def test_pcb_summary_tool(mock_board) -> None:
    server = build_server("pcb")
    text = await call_tool_text(server, "pcb_get_board_summary", {})
    assert "Board summary" in text


@pytest.mark.anyio
async def test_pcb_read_tools_report_active_board_items(
    mock_board,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KICAD_MCP_MAX_TEXT_RESPONSE_CHARS", "1000")
    track = SimpleNamespace(
        start=SimpleNamespace(x_nm=1_000_000, y_nm=2_000_000),
        end=SimpleNamespace(x_nm=3_000_000, y_nm=2_000_000),
        layer=BoardLayer.BL_F_Cu,
        width=250_000,
        net=SimpleNamespace(name="USB_DP"),
        id=SimpleNamespace(value="track-1"),
    )
    via = SimpleNamespace(
        position=SimpleNamespace(x_nm=4_000_000, y_nm=5_000_000),
        diameter=600_000,
        drill_diameter=300_000,
        net=SimpleNamespace(name="GND"),
        type=ViaType.VT_THROUGH,
    )
    pad = SimpleNamespace(
        id=SimpleNamespace(value="pad-1"),
        number="1",
        net=SimpleNamespace(name="USB_DP"),
        position=SimpleNamespace(x_nm=6_500_000, y_nm=7_500_000),
    )
    footprint = SimpleNamespace(
        reference_field=SimpleNamespace(text=SimpleNamespace(value="U1")),
        value_field=SimpleNamespace(text=SimpleNamespace(value="MCU")),
        position=SimpleNamespace(x_nm=6_000_000, y_nm=7_000_000),
        layer=BoardLayer.BL_B_Cu,
        id=SimpleNamespace(value="fp-1"),
        definition=SimpleNamespace(pads=[pad]),
    )
    zone = SimpleNamespace(
        name="GND_FILL",
        net=SimpleNamespace(name="GND"),
        layers=[BoardLayer.BL_F_Cu, BoardLayer.BL_B_Cu],
    )
    shape = SimpleNamespace(layer=BoardLayer.BL_Edge_Cuts)
    mock_board.get_tracks.return_value = [track]
    mock_board.get_vias.return_value = [via]
    mock_board.get_footprints.return_value = [footprint]
    mock_board.get_nets.return_value = [SimpleNamespace(name="USB_DP")]
    mock_board.get_zones.return_value = [zone]
    mock_board.get_shapes.return_value = [shape]
    mock_board.get_pads.return_value = [pad]
    mock_board.get_enabled_layers.return_value = [BoardLayer.BL_F_Cu, BoardLayer.BL_B_Cu]
    mock_board.get_selection.return_value = [track]
    mock_board.get_as_string.return_value = "(kicad_pcb " + ("x" * 1200) + ")"
    server = build_server("pcb")

    tracks = await call_tool_text(server, "pcb_get_tracks", {"filter_layer": "F_Cu"})
    track_page = await call_tool_text(server, "pcb_get_tracks", {"page": 2, "page_size": 1})
    vias = await call_tool_text(server, "pcb_get_vias", {})
    footprints = await call_tool_text(server, "pcb_get_footprints", {"filter_layer": "B_Cu"})
    nets = await call_tool_text(server, "pcb_get_nets", {})
    zones = await call_tool_text(server, "pcb_get_zones", {})
    shapes = await call_tool_text(server, "pcb_get_shapes", {})
    pads = await call_tool_text(server, "pcb_get_pads", {})
    layers = await call_tool_text(server, "pcb_get_layers", {})
    selection = await call_tool_text(server, "pcb_get_selection", {})
    board_text = await call_tool_text(server, "pcb_get_board_as_string", {})
    ratsnest = await call_tool_text(server, "pcb_get_ratsnest", {})

    assert "Tracks (1 total)" in tracks
    assert "net=USB_DP" in tracks
    assert "Track page 2 is out of range" in track_page
    assert "diameter=0.600 mm" in vias
    assert "U1 (MCU)" in footprints
    assert "- USB_DP" in nets
    assert "GND_FILL" in zones
    assert "SimpleNamespace layer=BL_Edge_Cuts" in shapes
    assert "U1:1 net=USB_DP" in pads
    assert "BL_F_Cu" in layers and "BL_B_Cu" in layers
    assert "Selected items (1 total)" in selection
    assert "... [truncated]" in board_text
    assert "Live ratsnest extraction is not exposed" in ratsnest


@pytest.mark.anyio
async def test_pcb_add_track_creates_item(mock_board) -> None:
    server = build_server("pcb")
    await server.call_tool(
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
    )
    assert mock_board.create_items.called


@pytest.mark.anyio
async def test_pcb_add_text_uses_kicad_compatible_alignment(mock_board) -> None:
    server = build_server("pcb")

    await server.call_tool(
        "pcb_add_text",
        {
            "text": "HELLO",
            "x_mm": 1.0,
            "y_mm": 1.0,
            "layer": "F_SilkS",
            "size_mm": 1.0,
        },
    )

    [[text_item]] = mock_board.create_items.call_args.args
    assert text_item.attributes.horizontal_alignment == common_types.HA_LEFT
    assert text_item.attributes.vertical_alignment == common_types.VA_BOTTOM


@pytest.mark.anyio
async def test_pcb_sync_from_schematic_adds_missing_footprints(
    sample_project,
    mock_kicad,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _allow_schematic_sync(monkeypatch)
    monkeypatch.setattr("kicad_mcp.tools.pcb._board_is_open", lambda: False)
    monkeypatch.setattr(
        "kicad_mcp.tools.pcb._export_schematic_net_map",
        lambda: (
            {
                ("R1", "1"): "VIN",
                ("R1", "2"): "MID",
                ("R2", "1"): "MID",
                ("R2", "2"): "GND",
            },
            "",
        ),
    )
    server = build_server("full")

    await call_tool_text(
        server,
        "sch_build_circuit",
        {
            "symbols": [
                {
                    "library": "Device",
                    "symbol_name": "R",
                    "reference": "R1",
                    "value": "10k",
                    "footprint": "Resistor_SMD:R_0805",
                    "x_mm": 50.8,
                    "y_mm": 50.8,
                },
                {
                    "library": "Device",
                    "symbol_name": "R",
                    "reference": "R2",
                    "value": "22k",
                    "footprint": "Resistor_SMD:R_0805",
                    "x_mm": 76.2,
                    "y_mm": 50.8,
                },
            ]
        },
    )

    result = await call_tool_text(server, "pcb_sync_from_schematic", {})
    pcb_text = (sample_project / "demo.kicad_pcb").read_text(encoding="utf-8")

    assert "New footprints added: 2" in result
    assert "Total pads considered: 4" in result
    assert "Pads with named nets: 4" in result
    assert "Pads left as <no net>: 0" in result
    assert "Transfer quality: CLEAN (100.0% pad coverage)" in result
    assert "Fully net-mapped refs: 2" in result
    assert "Partially net-mapped refs: 0" in result
    assert "Refs with unresolved pad nets: (none)" in result
    assert f"(version {GENERATED_SEXPR_DIALECT_VERSION})" in pcb_text
    assert pcb_text.count('(footprint "R_0805"') == 2
    assert '(property "Reference" "R1"' in pcb_text
    assert '(property "Reference" "R2"' in pcb_text
    assert '(net "VIN")' in pcb_text
    assert '(net "MID")' in pcb_text
    assert '(net "GND")' in pcb_text


@pytest.mark.anyio
async def test_pcb_sync_from_schematic_refuses_when_board_is_open(
    sample_project,
    mock_kicad,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _allow_schematic_sync(monkeypatch)
    monkeypatch.setattr("kicad_mcp.tools.pcb._board_is_open", lambda: True)
    server = build_server("pcb")

    result = await call_tool_text(server, "pcb_sync_from_schematic", {})

    assert "Refusing file-based PCB sync while a board is open" in result


@pytest.mark.anyio
async def test_pcb_sync_from_schematic_blocks_on_dirty_schematic(
    sample_project,
    mock_kicad,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("kicad_mcp.tools.pcb._board_is_open", lambda: False)
    monkeypatch.setattr(
        "kicad_mcp.tools.validation._evaluate_schematic_gate",
        lambda: GateOutcome(
            name="Schematic",
            status="FAIL",
            summary="ERC violations are still present.",
            details=["ERC violations: 12"],
        ),
    )
    monkeypatch.setattr(
        "kicad_mcp.tools.validation._evaluate_schematic_connectivity_gate",
        lambda: GateOutcome(
            name="Schematic connectivity",
            status="FAIL",
            summary="Connectivity smells suggest the schematic is not ready for PCB work.",
            details=["Zero-wire pages: 1"],
        ),
    )
    server = build_server("full")

    result = await call_tool_text(server, "pcb_sync_from_schematic", {})
    pcb_text = (sample_project / "demo.kicad_pcb").read_text(encoding="utf-8")

    assert "PCB sync aborted because the schematic is not ready" in result
    assert "Schematic quality gate: FAIL" in result
    assert "Schematic connectivity quality gate: FAIL" in result
    assert "schematic_quality_gate()" in result
    assert pcb_text == "(kicad_pcb)\n"


@pytest.mark.anyio
async def test_pcb_sync_from_schematic_force_overrides_pre_sync_gate(
    sample_project,
    mock_kicad,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("kicad_mcp.tools.pcb._board_is_open", lambda: False)
    monkeypatch.setattr(
        "kicad_mcp.tools.validation._evaluate_schematic_gate",
        lambda: GateOutcome(
            name="Schematic",
            status="FAIL",
            summary="ERC violations are still present.",
            details=["ERC violations: 1"],
        ),
    )
    monkeypatch.setattr(
        "kicad_mcp.tools.validation._evaluate_schematic_connectivity_gate",
        lambda: GateOutcome(
            name="Schematic connectivity",
            status="PASS",
            summary="Connectivity is structurally sound.",
            details=[],
        ),
    )
    monkeypatch.setattr("kicad_mcp.tools.pcb._export_schematic_net_map", lambda: ({}, ""))
    server = build_server("full")
    await call_tool_text(
        server,
        "sch_build_circuit",
        {
            "symbols": [
                {
                    "library": "Device",
                    "symbol_name": "R",
                    "reference": "R1",
                    "value": "10k",
                    "footprint": "Resistor_SMD:R_0805",
                    "x_mm": 50.8,
                    "y_mm": 50.8,
                }
            ]
        },
    )

    result = await call_tool_text(server, "pcb_sync_from_schematic", {"force": True})

    assert "Pre-sync gate was overridden by force=True" in result
    assert "New footprints added: 1" in result


@pytest.mark.anyio
async def test_pcb_sync_from_schematic_deduplicates_multi_unit_references(
    sample_project,
    mock_kicad,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _allow_schematic_sync(monkeypatch)
    monkeypatch.setattr("kicad_mcp.tools.pcb._board_is_open", lambda: False)
    monkeypatch.setattr("kicad_mcp.tools.pcb._export_schematic_net_map", lambda: ({}, ""))
    server = build_server("full")

    await call_tool_text(
        server,
        "sch_build_circuit",
        {
            "symbols": [
                {
                    "library": "MultiUnit",
                    "symbol_name": "DualChild",
                    "reference": "U1",
                    "value": "DualOpamp",
                    "footprint": "Resistor_SMD:R_1206",
                    "unit": 1,
                    "x_mm": 50.8,
                    "y_mm": 50.8,
                },
                {
                    "library": "MultiUnit",
                    "symbol_name": "DualChild",
                    "reference": "U1",
                    "value": "DualOpamp",
                    "footprint": "Resistor_SMD:R_1206",
                    "unit": 2,
                    "x_mm": 76.2,
                    "y_mm": 50.8,
                },
            ]
        },
    )

    result = await call_tool_text(server, "pcb_sync_from_schematic", {})
    pcb_text = (sample_project / "demo.kicad_pcb").read_text(encoding="utf-8")

    assert "New footprints added: 1" in result
    assert pcb_text.count('(footprint "R_1206"') == 1
    assert pcb_text.count('(property "Reference" "U1"') == 1


@pytest.mark.anyio
async def test_pcb_sync_from_schematic_reports_mismatches_without_replacing(
    sample_project,
    mock_kicad,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _allow_schematic_sync(monkeypatch)
    monkeypatch.setattr("kicad_mcp.tools.pcb._board_is_open", lambda: False)
    monkeypatch.setattr("kicad_mcp.tools.pcb._export_schematic_net_map", lambda: ({}, ""))
    (sample_project / "demo.kicad_pcb").write_text(
        (
            "(kicad_pcb\n"
            "\t(version 20250216)\n"
            '\t(generator "pytest")\n'
            '\t(footprint "R_1206"\n'
            '\t\t(layer "F.Cu")\n'
            '\t\t(uuid "00000000-0000-0000-0000-000000000001")\n'
            "\t\t(at 40 50 90)\n"
            '\t\t(property "Reference" "R1"\n'
            "\t\t\t(at 0 -1.8 0)\n"
            '\t\t\t(layer "F.SilkS")\n'
            "\t\t)\n"
            '\t\t(property "Value" "10k"\n'
            "\t\t\t(at 0 1.8 0)\n"
            '\t\t\t(layer "F.Fab")\n'
            "\t\t)\n"
            '\t\t(pad "1" smd rect (at -1.4 0) (size 1.2 1.6) (layers "F.Cu"))\n'
            '\t\t(pad "2" smd rect (at 1.4 0) (size 1.2 1.6) (layers "F.Cu"))\n'
            "\t)\n"
            ")\n"
        ),
        encoding="utf-8",
    )
    server = build_server("full")

    await call_tool_text(
        server,
        "sch_build_circuit",
        {
            "symbols": [
                {
                    "library": "Device",
                    "symbol_name": "R",
                    "reference": "R1",
                    "value": "10k",
                    "footprint": "Resistor_SMD:R_0805",
                    "x_mm": 50.8,
                    "y_mm": 50.8,
                }
            ]
        },
    )

    result = await call_tool_text(server, "pcb_sync_from_schematic", {})
    pcb_text = (sample_project / "demo.kicad_pcb").read_text(encoding="utf-8")

    assert "Existing footprint mismatches:" in result
    assert "Rerun with replace_mismatched=True" in result
    assert "Mismatched footprints replaced: 0" in result
    assert '(footprint "R_1206"' in pcb_text
    assert '(footprint "R_0805"' not in pcb_text


@pytest.mark.anyio
async def test_pcb_sync_from_schematic_reports_partial_transfer_quality(
    sample_project,
    mock_kicad,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _allow_schematic_sync(monkeypatch)
    monkeypatch.setattr("kicad_mcp.tools.pcb._board_is_open", lambda: False)
    monkeypatch.setattr(
        "kicad_mcp.tools.pcb._export_schematic_net_map",
        lambda: (
            {
                ("R1", "1"): "VIN",
                ("R1", "2"): "MID",
                ("R2", "1"): "MID",
            },
            "",
        ),
    )
    server = build_server("full")

    await call_tool_text(
        server,
        "sch_build_circuit",
        {
            "symbols": [
                {
                    "library": "Device",
                    "symbol_name": "R",
                    "reference": "R1",
                    "value": "10k",
                    "footprint": "Resistor_SMD:R_0805",
                    "x_mm": 50.8,
                    "y_mm": 50.8,
                },
                {
                    "library": "Device",
                    "symbol_name": "R",
                    "reference": "R2",
                    "value": "22k",
                    "footprint": "Resistor_SMD:R_0805",
                    "x_mm": 76.2,
                    "y_mm": 50.8,
                },
            ]
        },
    )

    result = await call_tool_text(server, "pcb_sync_from_schematic", {})

    assert "Pads with named nets: 3" in result
    assert "Pads left as <no net>: 1" in result
    assert "Transfer quality: DEGRADED (75.0% pad coverage)" in result
    assert "Fully net-mapped refs: 1" in result
    assert "Partially net-mapped refs: 1" in result
    assert "R2 (1/2 pad(s) without net names)" in result


@pytest.mark.anyio
async def test_pcb_transfer_quality_gate_passes_for_clean_sync(
    sample_project,
    mock_kicad,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _allow_schematic_sync(monkeypatch)
    monkeypatch.setattr("kicad_mcp.tools.pcb._board_is_open", lambda: False)
    monkeypatch.setattr(
        "kicad_mcp.tools.pcb._export_schematic_net_map",
        lambda: (
            {
                ("R1", "1"): "VIN",
                ("R1", "2"): "MID",
                ("R2", "1"): "MID",
                ("R2", "2"): "GND",
            },
            "",
        ),
    )
    server = build_server("full")

    await call_tool_text(
        server,
        "sch_build_circuit",
        {
            "symbols": [
                {
                    "library": "Device",
                    "symbol_name": "R",
                    "reference": "R1",
                    "value": "10k",
                    "footprint": "Resistor_SMD:R_0805",
                    "x_mm": 50.8,
                    "y_mm": 50.8,
                },
                {
                    "library": "Device",
                    "symbol_name": "R",
                    "reference": "R2",
                    "value": "22k",
                    "footprint": "Resistor_SMD:R_0805",
                    "x_mm": 76.2,
                    "y_mm": 50.8,
                },
            ]
        },
    )
    await call_tool_text(server, "pcb_sync_from_schematic", {})

    result = await call_tool_text(server, "pcb_transfer_quality_gate", {})

    assert "PCB transfer quality gate: PASS" in result
    assert "Expected named pad nets: 4" in result
    assert "Matched pad nets on PCB: 4" in result
    assert "Transfer coverage: 100.0%" in result


@pytest.mark.anyio
async def test_pcb_transfer_quality_gate_flags_pad_net_mismatch(
    sample_project,
    mock_kicad,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _allow_schematic_sync(monkeypatch)
    monkeypatch.setattr("kicad_mcp.tools.pcb._board_is_open", lambda: False)
    monkeypatch.setattr(
        "kicad_mcp.tools.pcb._export_schematic_net_map",
        lambda: (
            {
                ("R1", "1"): "VIN",
                ("R1", "2"): "MID",
                ("R2", "1"): "MID",
                ("R2", "2"): "GND",
            },
            "",
        ),
    )
    server = build_server("full")

    await call_tool_text(
        server,
        "sch_build_circuit",
        {
            "symbols": [
                {
                    "library": "Device",
                    "symbol_name": "R",
                    "reference": "R1",
                    "value": "10k",
                    "footprint": "Resistor_SMD:R_0805",
                    "x_mm": 50.8,
                    "y_mm": 50.8,
                },
                {
                    "library": "Device",
                    "symbol_name": "R",
                    "reference": "R2",
                    "value": "22k",
                    "footprint": "Resistor_SMD:R_0805",
                    "x_mm": 76.2,
                    "y_mm": 50.8,
                },
            ]
        },
    )
    await call_tool_text(server, "pcb_sync_from_schematic", {})

    pcb_path = sample_project / "demo.kicad_pcb"
    pcb_text = pcb_path.read_text(encoding="utf-8")
    pcb_path.write_text(pcb_text.replace('(net "GND")', '(net "BROKEN")', 1), encoding="utf-8")

    result = await call_tool_text(server, "pcb_transfer_quality_gate", {})

    assert "PCB transfer quality gate: FAIL" in result
    assert "Transfer coverage: 75.0%" in result
    assert "R2.2" in result
    assert "expected 'GND'" in result


@pytest.mark.anyio
async def test_pcb_sync_from_schematic_replaces_mismatched_footprints_in_place(
    sample_project,
    mock_kicad,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _allow_schematic_sync(monkeypatch)
    monkeypatch.setattr("kicad_mcp.tools.pcb._board_is_open", lambda: False)
    monkeypatch.setattr("kicad_mcp.tools.pcb._export_schematic_net_map", lambda: ({}, ""))
    (sample_project / "demo.kicad_pcb").write_text(
        (
            "(kicad_pcb\n"
            "\t(version 20250216)\n"
            '\t(generator "pytest")\n'
            '\t(footprint "R_1206"\n'
            '\t\t(layer "F.Cu")\n'
            '\t\t(uuid "00000000-0000-0000-0000-000000000001")\n'
            "\t\t(at 40 50 90)\n"
            '\t\t(property "Reference" "R1"\n'
            "\t\t\t(at 0 -1.8 0)\n"
            '\t\t\t(layer "F.SilkS")\n'
            "\t\t)\n"
            '\t\t(property "Value" "10k"\n'
            "\t\t\t(at 0 1.8 0)\n"
            '\t\t\t(layer "F.Fab")\n'
            "\t\t)\n"
            '\t\t(pad "1" smd rect (at -1.4 0) (size 1.2 1.6) (layers "F.Cu"))\n'
            '\t\t(pad "2" smd rect (at 1.4 0) (size 1.2 1.6) (layers "F.Cu"))\n'
            "\t)\n"
            ")\n"
        ),
        encoding="utf-8",
    )
    server = build_server("full")

    await call_tool_text(
        server,
        "sch_build_circuit",
        {
            "symbols": [
                {
                    "library": "Device",
                    "symbol_name": "R",
                    "reference": "R1",
                    "value": "10k",
                    "footprint": "Resistor_SMD:R_0805",
                    "x_mm": 50.8,
                    "y_mm": 50.8,
                }
            ]
        },
    )

    result = await call_tool_text(
        server,
        "pcb_sync_from_schematic",
        {"replace_mismatched": True},
    )
    pcb_text = (sample_project / "demo.kicad_pcb").read_text(encoding="utf-8")

    assert "Mismatched footprints replaced: 1" in result
    assert '(footprint "R_0805"' in pcb_text
    assert '(footprint "R_1206"' not in pcb_text
    assert re.search(r"\s+\(at 40\.0000 50\.0000 90\)", pcb_text) is not None


@pytest.mark.anyio
async def test_pcb_sync_from_schematic_avoids_simple_footprint_overlap(
    sample_project,
    mock_kicad,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _allow_schematic_sync(monkeypatch)
    monkeypatch.setattr("kicad_mcp.tools.pcb._board_is_open", lambda: False)
    monkeypatch.setattr("kicad_mcp.tools.pcb._export_schematic_net_map", lambda: ({}, ""))
    server = build_server("full")

    await call_tool_text(
        server,
        "sch_build_circuit",
        {
            "symbols": [
                {
                    "library": "Device",
                    "symbol_name": "R",
                    "reference": "R1",
                    "value": "10k",
                    "footprint": "Resistor_SMD:R_0805",
                    "x_mm": 50.8,
                    "y_mm": 50.8,
                },
                {
                    "library": "Device",
                    "symbol_name": "R",
                    "reference": "R2",
                    "value": "22k",
                    "footprint": "Resistor_SMD:R_0805",
                    "x_mm": 50.8,
                    "y_mm": 50.8,
                },
            ]
        },
    )

    await call_tool_text(server, "pcb_sync_from_schematic", {})
    pcb_text = (sample_project / "demo.kicad_pcb").read_text(encoding="utf-8")

    positions = {
        match.group(1)
        for match in re.finditer(r"\n\t\t\(at\s+([0-9.\-]+\s+[0-9.\-]+\s+\d+)\)", pcb_text)
    }

    assert pcb_text.count('(footprint "R_0805"') == 2
    assert len(positions) >= 2


@pytest.mark.anyio
async def test_pcb_auto_place_by_schematic_repositions_existing_footprints(
    sample_project,
    mock_kicad,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("kicad_mcp.tools.pcb._board_is_open", lambda: False)
    (sample_project / "demo.kicad_pcb").write_text(
        _board_text(
            _footprint_block("R_0805", "R1", "10k", 10, 10, "00000000-0000-0000-0000-000000000011"),
            _footprint_block("R_0805", "R2", "22k", 12, 10, "00000000-0000-0000-0000-000000000012"),
        ),
        encoding="utf-8",
    )
    server = build_server("full")

    await call_tool_text(
        server,
        "sch_build_circuit",
        {
            "symbols": [
                {
                    "library": "Device",
                    "symbol_name": "R",
                    "reference": "R1",
                    "value": "10k",
                    "footprint": "Resistor_SMD:R_0805",
                    "x_mm": 20.0,
                    "y_mm": 20.0,
                },
                {
                    "library": "Device",
                    "symbol_name": "R",
                    "reference": "R2",
                    "value": "22k",
                    "footprint": "Resistor_SMD:R_0805",
                    "x_mm": 40.0,
                    "y_mm": 20.0,
                },
            ]
        },
    )

    result = await call_tool_text(
        server,
        "pcb_auto_place_by_schematic",
        {"strategy": "linear", "origin_x_mm": 25.0, "origin_y_mm": 35.0},
    )
    pcb_text = (sample_project / "demo.kicad_pcb").read_text(encoding="utf-8")
    r1_x, r1_y, _ = _footprint_position(pcb_text, "R1")
    r2_x, r2_y, _ = _footprint_position(pcb_text, "R2")

    assert "Auto-placement strategy: linear" in result
    assert "Existing footprints moved: 2" in result
    assert r1_y == pytest.approx(r2_y)
    assert r2_x > r1_x


@pytest.mark.anyio
async def test_pcb_align_footprints_arranges_horizontal_row(
    sample_project,
    mock_kicad,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("kicad_mcp.tools.pcb._board_is_open", lambda: False)
    (sample_project / "demo.kicad_pcb").write_text(
        _board_text(
            _footprint_block("R_0805", "R1", "10k", 10, 10, "1"),
            _footprint_block("R_0805", "R2", "22k", 30, 40, "2"),
        ),
        encoding="utf-8",
    )
    server = build_server("pcb")

    result = await call_tool_text(
        server,
        "pcb_align_footprints",
        {"refs": ["R1", "R2"], "axis": "x", "spacing_mm": 6.0},
    )
    pcb_text = (sample_project / "demo.kicad_pcb").read_text(encoding="utf-8")
    r1_x, r1_y, _ = _footprint_position(pcb_text, "R1")
    r2_x, r2_y, _ = _footprint_position(pcb_text, "R2")

    assert "Aligned 2 footprint(s) along the x-axis." in result
    assert r1_y == pytest.approx(r2_y)
    assert r2_x - r1_x == pytest.approx(6.0)


@pytest.mark.anyio
async def test_pcb_group_by_function_clusters_groups(
    sample_project,
    mock_kicad,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("kicad_mcp.tools.pcb._board_is_open", lambda: False)
    (sample_project / "demo.kicad_pcb").write_text(
        _board_text(
            _footprint_block("R_0805", "R1", "10k", 10, 10, "1"),
            _footprint_block("R_0805", "R2", "22k", 12, 12, "2"),
            _footprint_block("R_0805", "C1", "100n", 14, 14, "3"),
            _footprint_block("R_0805", "C2", "1u", 16, 16, "4"),
        ),
        encoding="utf-8",
    )
    server = build_server("pcb")

    result = await call_tool_text(
        server,
        "pcb_group_by_function",
        {
            "groups": {"power": ["C1", "C2"], "bias": ["R1", "R2"]},
            "origin_x_mm": 20.0,
            "origin_y_mm": 20.0,
            "group_spacing_mm": 25.0,
            "item_spacing_mm": 5.0,
        },
    )
    pcb_text = (sample_project / "demo.kicad_pcb").read_text(encoding="utf-8")
    c1_x, _, _ = _footprint_position(pcb_text, "C1")
    r1_x, _, _ = _footprint_position(pcb_text, "R1")

    assert "Functional groups placed: 2" in result
    assert c1_x != pytest.approx(r1_x)


@pytest.mark.anyio
async def test_pcb_place_decoupling_caps_moves_caps_near_ic(
    sample_project,
    mock_kicad,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("kicad_mcp.tools.pcb._board_is_open", lambda: False)
    (sample_project / "demo.kicad_pcb").write_text(
        _board_text(
            _footprint_block("U_QFN", "U1", "MCU", 50, 50, "u1", width_mm=8.0, height_mm=8.0),
            _footprint_block("C_0402", "C1", "100n", 20, 20, "c1", width_mm=1.6, height_mm=1.0),
            _footprint_block("C_0402", "C2", "1u", 25, 20, "c2", width_mm=1.6, height_mm=1.0),
        ),
        encoding="utf-8",
    )
    server = build_server("pcb")

    result = await call_tool_text(
        server,
        "pcb_place_decoupling_caps",
        {"ic_ref": "U1", "cap_refs": ["C1", "C2"], "max_distance_mm": 2.0},
    )
    pcb_text = (sample_project / "demo.kicad_pcb").read_text(encoding="utf-8")
    u1_x, u1_y, _ = _footprint_position(pcb_text, "U1")
    c1_x, c1_y, _ = _footprint_position(pcb_text, "C1")
    c2_x, c2_y, _ = _footprint_position(pcb_text, "C2")

    assert "Placed 2 decoupling capacitor(s) near U1." in result
    assert "C1 placed" in result
    assert "C2 placed" in result
    assert abs(c1_y - u1_y) <= 8.5
    assert abs(c2_y - u1_y) <= 10.5
    assert c1_x != pytest.approx(c2_x)


@pytest.mark.anyio
async def test_pcb_add_mounting_holes_appends_custom_footprints(
    sample_project,
    mock_kicad,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("kicad_mcp.tools.pcb._board_is_open", lambda: False)
    server = build_server("pcb")

    result = await call_tool_text(server, "pcb_add_mounting_holes", {})
    pcb_text = (sample_project / "demo.kicad_pcb").read_text(encoding="utf-8")

    assert "Added 4 mounting hole(s)" in result
    assert pcb_text.count('(footprint "MountingHole_3.20mm"') == 4
    assert '(property "Reference" "H1"' in pcb_text


@pytest.mark.anyio
async def test_pcb_add_fiducial_marks_appends_custom_footprints(
    sample_project,
    mock_kicad,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("kicad_mcp.tools.pcb._board_is_open", lambda: False)
    server = build_server("pcb")

    result = await call_tool_text(server, "pcb_add_fiducial_marks", {"count": 3})
    pcb_text = (sample_project / "demo.kicad_pcb").read_text(encoding="utf-8")

    assert "Added 3 fiducial mark(s)" in result
    assert pcb_text.count('(footprint "Fiducial_1.00mm"') == 3
    assert '(property "Reference" "FID1"' in pcb_text


@pytest.mark.anyio
async def test_pcb_design_blocks_and_inner_layer_graphics_success(
    sample_project,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _allow_schematic_sync(monkeypatch)
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})
    (sample_project / "demo.kicad_pcb").write_text(
        _board_text(
            _footprint_block("R_0805", "R1", "10k", 10, 10, "block-r1"),
            _footprint_block("R_0805", "R2", "22k", 14, 10, "block-r2"),
        ),
        encoding="utf-8",
    )

    stackup = await call_tool_text(
        server,
        "pcb_set_stackup",
        {
            "layers": [
                {"name": "F.Cu", "type": "signal", "thickness_mm": 0.035, "material": "Copper"},
                {
                    "name": "dielectric_1",
                    "type": "dielectric",
                    "thickness_mm": 0.2,
                    "material": "FR4",
                    "epsilon_r": 4.2,
                },
                {"name": "In1.Cu", "type": "signal", "thickness_mm": 0.035, "material": "Copper"},
                {
                    "name": "dielectric_2",
                    "type": "dielectric",
                    "thickness_mm": 0.2,
                    "material": "FR4",
                    "epsilon_r": 4.2,
                },
                {"name": "In2.Cu", "type": "signal", "thickness_mm": 0.035, "material": "Copper"},
                {
                    "name": "dielectric_3",
                    "type": "dielectric",
                    "thickness_mm": 0.2,
                    "material": "FR4",
                    "epsilon_r": 4.2,
                },
                {"name": "B.Cu", "type": "signal", "thickness_mm": 0.035, "material": "Copper"},
            ]
        },
    )
    empty_blocks = await call_tool_text(server, "pcb_block_list", {})
    missing_block = await call_tool_text(
        server,
        "pcb_block_create_from_selection",
        {"name": "pair", "references": ["R404"]},
    )
    saved = await call_tool_text(
        server,
        "pcb_block_create_from_selection",
        {"name": "pair", "references": ["R1", "R2"]},
    )
    listed = await call_tool_text(server, "pcb_block_list", {})
    placed = await call_tool_text(
        server,
        "pcb_block_place",
        {"block_name": "pair", "x_mm": 40.0, "y_mm": 50.0, "rotation_deg": 90},
    )
    unknown_place = await call_tool_text(
        server,
        "pcb_block_place",
        {"block_name": "missing", "x_mm": 0.0, "y_mm": 0.0},
    )
    inner = await call_tool_text(
        server,
        "add_footprint_inner_layer_graphic",
        {
            "reference": "R1",
            "layer": "In1.Cu",
            "shape_type": "line",
            "x1_mm": -1.0,
            "y1_mm": 0.0,
            "x2_mm": 1.0,
            "y2_mm": 0.0,
        },
    )
    layers = await call_tool_text(server, "pcb_get_footprint_layers", {"reference": "R1"})

    pcb_text = (sample_project / "demo.kicad_pcb").read_text(encoding="utf-8")
    assert "Configured stackup with 7 layers." in stackup
    assert "{}" in empty_blocks
    assert "R404" in missing_block
    assert "PCB block 'pair' saved" in saved
    assert '"footprint_count": 2' in listed
    assert "Placed PCB block 'pair'" in placed
    assert "was not found" in unknown_place
    assert "Added line inner-layer graphic" in inner
    assert '"In1.Cu"' in layers
    assert pcb_text.count('(footprint "R_0805"') == 4


@pytest.mark.anyio
async def test_pcb_set_keepout_zone_creates_rule_area(mock_board) -> None:
    mock_board.get_enabled_layers.return_value = [BoardLayer.BL_F_Cu, BoardLayer.BL_B_Cu]
    server = build_server("pcb")

    result = await call_tool_text(
        server,
        "pcb_set_keepout_zone",
        {"x_mm": 25.0, "y_mm": 30.0, "w_mm": 10.0, "h_mm": 5.0},
    )

    [[zone]] = mock_board.create_items.call_args.args
    assert "Added keepout zone" in result
    assert zone.proto.rule_area_settings.keepout_tracks is True
    assert zone.proto.rule_area_settings.keepout_vias is True
    assert zone.proto.rule_area_settings.keepout_copper is True
    assert len(zone.layers) == 2


@pytest.mark.anyio
async def test_pcb_add_zone_creates_copper_zone(mock_board) -> None:
    server = build_server("pcb")

    result = await call_tool_text(
        server,
        "pcb_add_zone",
        {
            "net_name": "GND_DIG",
            "layer": "B_Cu",
            "corners": [
                {"x_mm": 0.0, "y_mm": 0.0},
                {"x_mm": 20.0, "y_mm": 0.0},
                {"x_mm": 20.0, "y_mm": 10.0},
                {"x_mm": 0.0, "y_mm": 10.0},
            ],
            "priority": 2,
            "name": "GND_DIG_SPLIT",
        },
    )

    [[zone]] = mock_board.create_items.call_args.args
    assert "Added copper zone 'GND_DIG_SPLIT'" in result
    assert list(zone.layers) == [BoardLayer.BL_B_Cu]
    assert zone.net.name == "GND_DIG"
    assert zone.priority == 2
    assert zone.proto.copper_settings.connection.zone_connection == board_types_pb2.ZCS_THERMAL
    assert zone.proto.copper_settings.connection.thermal_spokes.gap.value_nm == 500_000
    assert zone.proto.copper_settings.connection.thermal_spokes.width.value_nm == 500_000
    mock_board.refill_zones.assert_called_once()


@pytest.mark.anyio
async def test_pcb_add_teardrops_creates_helper_zones(mock_board) -> None:
    mock_board.get_pads.return_value = [
        SimpleNamespace(
            position=SimpleNamespace(x_nm=0, y_nm=0),
            size=SimpleNamespace(x_nm=1_000_000, y_nm=1_000_000),
            net=SimpleNamespace(name="VCC"),
            parent=SimpleNamespace(
                reference_field=SimpleNamespace(text=SimpleNamespace(value="U1"))
            ),
        )
    ]
    mock_board.get_tracks.return_value = [
        SimpleNamespace(
            start=SimpleNamespace(x_nm=0, y_nm=0),
            end=SimpleNamespace(x_nm=3_000_000, y_nm=0),
            layer=BoardLayer.BL_F_Cu,
            width=250_000,
            net=SimpleNamespace(name="VCC"),
        )
    ]
    server = build_server("pcb")

    result = await call_tool_text(server, "pcb_add_teardrops", {})

    [zones] = mock_board.create_items.call_args.args
    assert "Added 1 teardrop helper zone(s)" in result
    assert len(zones) == 1
    mock_board.refill_zones.assert_called_once()


@pytest.mark.anyio
async def test_pcb_set_design_rules_writes_board_level_constraints(
    sample_project,
    mock_kicad,
) -> None:
    server = build_server("pcb")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    result = await call_tool_text(
        server,
        "pcb_set_design_rules",
        {
            "min_trace_width_mm": 0.15,
            "min_clearance_mm": 0.15,
            "min_via_drill_mm": 0.3,
            "min_via_diameter_mm": 0.6,
            "min_annular_ring_mm": 0.13,
            "min_hole_to_hole_mm": 0.25,
        },
    )
    dru_text = (sample_project / "demo.kicad_dru").read_text(encoding="utf-8")

    assert "Board design rules written to" in result
    assert "Board minimum track width" in dru_text
    assert "(constraint track_width (min 0.1500mm) (opt 0.1500mm))" in dru_text
    assert "(constraint clearance (min 0.1500mm))" in dru_text
    assert "(constraint hole_size (min 0.3000mm))" in dru_text
    assert "(constraint via_diameter (min 0.6000mm))" in dru_text
    assert "(constraint annular_width (min 0.1300mm))" in dru_text
    assert "(constraint hole_to_hole (min 0.2500mm))" in dru_text


@pytest.mark.anyio
async def test_pcb_set_stackup_persists_file_and_supports_impedance_lookup(
    sample_project,
    mock_board,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("kicad_mcp.tools.pcb._board_is_open", lambda: False)
    server = build_server("pcb")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    configured = await call_tool_text(
        server,
        "pcb_set_stackup",
        {
            "layers": [
                {
                    "name": "F_Cu",
                    "type": "signal",
                    "thickness_mm": 0.035,
                    "material": "Copper",
                },
                {
                    "name": "dielectric_1",
                    "type": "prepreg",
                    "thickness_mm": 0.18,
                    "material": "FR4",
                    "epsilon_r": 4.2,
                    "loss_tangent": 0.018,
                },
                {
                    "name": "In1_Cu",
                    "type": "ground",
                    "thickness_mm": 0.018,
                    "material": "Copper",
                },
                {
                    "name": "dielectric_2",
                    "type": "core",
                    "thickness_mm": 1.164,
                    "material": "FR4",
                    "epsilon_r": 4.2,
                },
                {
                    "name": "B_Cu",
                    "type": "signal",
                    "thickness_mm": 0.035,
                    "material": "Copper",
                },
            ]
        },
    )
    stackup = await call_tool_text(server, "pcb_get_stackup", {})
    impedance = await call_tool_text(
        server,
        "pcb_get_impedance_for_trace",
        {"width_mm": 0.34, "layer_name": "F_Cu"},
    )

    pcb_text = (sample_project / "demo.kicad_pcb").read_text(encoding="utf-8")
    state_text = (sample_project / "output" / "stackup_profile.json").read_text(encoding="utf-8")

    assert "Configured stackup with 5 layers." in configured
    assert "Total thickness: 1.4320 mm" in configured
    assert "(stackup" in pcb_text
    assert '(layer "F.Cu" 0' in pcb_text
    assert "(layer dielectric 1" in pcb_text
    assert "(epsilon_r 4.2000)" in pcb_text
    assert '"name": "dielectric_1"' in state_text
    assert "Board stackup (5 layers)" in stackup
    assert "dielectric_1" in stackup
    assert "Trace impedance from current stackup" in impedance
    assert "Layer: F_Cu" in impedance
    mock_board.revert.assert_called_once()


@pytest.mark.anyio
async def test_pcb_add_blind_and_micro_via_configure_layer_pairs(mock_board) -> None:
    server = build_server("pcb")

    blind = await call_tool_text(
        server,
        "pcb_add_blind_via",
        {
            "x_mm": 10.0,
            "y_mm": 5.0,
            "from_layer": "F_Cu",
            "to_layer": "In1_Cu",
            "net_name": "USB_DP",
        },
    )
    micro = await call_tool_text(
        server,
        "pcb_add_microvia",
        {
            "x_mm": 12.0,
            "y_mm": 6.0,
            "from_layer": "In1_Cu",
            "to_layer": "In2_Cu",
            "net_name": "USB_DN",
        },
    )

    blind_via = mock_board.create_items.call_args_list[0].args[0][0]
    micro_via = mock_board.create_items.call_args_list[1].args[0][0]

    assert "Blind or buried via added successfully" in blind
    assert blind_via.type == ViaType.VT_BLIND_BURIED
    assert list(blind_via.padstack.layers) == [BoardLayer.BL_F_Cu, BoardLayer.BL_In1_Cu]
    assert blind_via.padstack.drill.start_layer == BoardLayer.BL_F_Cu
    assert blind_via.padstack.drill.end_layer == BoardLayer.BL_In1_Cu

    assert "Microvia added successfully" in micro
    assert micro_via.type == ViaType.VT_MICRO
    assert list(micro_via.padstack.layers) == [BoardLayer.BL_In1_Cu, BoardLayer.BL_In2_Cu]
    assert micro_via.padstack.drill.start_layer == BoardLayer.BL_In1_Cu
    assert micro_via.padstack.drill.end_layer == BoardLayer.BL_In2_Cu


@pytest.mark.anyio
async def test_pcb_check_creepage_clearance_reports_worst_pad_pair(mock_board) -> None:
    mock_board.get_pads.return_value = [
        SimpleNamespace(
            parent=SimpleNamespace(
                reference_field=SimpleNamespace(text=SimpleNamespace(value="J1"))
            ),
            number="1",
            position=SimpleNamespace(x_nm=0, y_nm=0),
            size=SimpleNamespace(x_nm=1_000_000, y_nm=1_000_000),
            net=SimpleNamespace(name="VIN"),
        ),
        SimpleNamespace(
            parent=SimpleNamespace(
                reference_field=SimpleNamespace(text=SimpleNamespace(value="J1"))
            ),
            number="2",
            position=SimpleNamespace(x_nm=2_200_000, y_nm=0),
            size=SimpleNamespace(x_nm=1_000_000, y_nm=1_000_000),
            net=SimpleNamespace(name="GND"),
        ),
    ]
    server = build_server("pcb")

    creepage = await call_tool_text(
        server,
        "pcb_check_creepage_clearance",
        {"voltage_v": 120.0, "pollution_degree": 2, "material_group": 3},
    )

    assert "Creepage clearance review (WARN)" in creepage
    assert "Worst pad pair: J1.1 (VIN) vs J1.2 (GND)" in creepage
    assert "Estimated edge-to-edge clearance: 1.200 mm" in creepage
    assert "Required creepage" in creepage


@pytest.mark.anyio
async def test_pcb_sync_from_root_collects_linked_child_sheet_components(
    sample_project,
    mock_kicad,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _allow_schematic_sync(monkeypatch)
    monkeypatch.setattr("kicad_mcp.tools.pcb._board_is_open", lambda: False)
    monkeypatch.setattr(
        "kicad_mcp.tools.pcb._export_schematic_net_map",
        lambda: ({("R9", "1"): "VIN", ("R9", "2"): "GND"}, ""),
    )
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})
    await call_tool_text(
        server,
        "sch_create_sheet",
        {"name": "Child", "filename": "child.kicad_sch", "x_mm": 40.64, "y_mm": 50.8},
    )
    await call_tool_text(
        server,
        "kicad_set_project",
        {
            "project_dir": str(sample_project),
            "sch_file": str(sample_project / "child.kicad_sch"),
            "pcb_file": str(sample_project / "demo.kicad_pcb"),
        },
    )
    await call_tool_text(
        server,
        "sch_build_circuit",
        {
            "symbols": [
                {
                    "library": "Device",
                    "symbol_name": "R",
                    "reference": "R9",
                    "value": "10k",
                    "footprint": "Resistor_SMD:R_0805",
                    "x_mm": 50.8,
                    "y_mm": 50.8,
                }
            ]
        },
    )
    await call_tool_text(
        server,
        "kicad_set_project",
        {
            "project_dir": str(sample_project),
            "sch_file": str(sample_project / "demo.kicad_sch"),
            "pcb_file": str(sample_project / "demo.kicad_pcb"),
        },
    )

    result = await call_tool_text(server, "pcb_sync_from_schematic", {})
    pcb_text = (sample_project / "demo.kicad_pcb").read_text(encoding="utf-8")

    assert "No schematic symbols were found" not in result
    assert "New footprints added: 1" in result
    assert '(property "Reference" "R9"' in pcb_text


@pytest.mark.anyio
async def test_pcb_sync_from_schematic_resolves_project_fp_lib_table(
    sample_project: Path,
    mock_kicad,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kicad_mcp.config import reset_config

    _allow_schematic_sync(monkeypatch)
    monkeypatch.setattr("kicad_mcp.tools.pcb._board_is_open", lambda: False)
    monkeypatch.setattr(
        "kicad_mcp.tools.pcb._export_schematic_net_map",
        lambda: ({("J1", "1"): "VIN", ("J1", "2"): "GND"}, ""),
    )

    pretty_dir = sample_project / "footprints" / "Gateway.pretty"
    pretty_dir.mkdir(parents=True)
    (pretty_dir / "Custom.kicad_mod").write_text(
        (
            '(footprint "Custom"\n'
            '\t(layer "F.Cu")\n'
            '\t(property "Reference" "REF**" (at 0 -1 0) (layer "F.SilkS"))\n'
            '\t(property "Value" "Custom" (at 0 1 0) (layer "F.Fab"))\n'
            '\t(pad "1" smd rect (at -1 0) (size 1 1) (layers "F.Cu"))\n'
            '\t(pad "2" smd rect (at 1 0) (size 1 1) (layers "F.Cu"))\n'
            ")\n"
        ),
        encoding="utf-8",
    )
    (sample_project / "fp-lib-table").write_text(
        '(fp_lib_table (lib (name "Gateway") (type "KiCad") '
        '(uri "${KIPRJMOD}/footprints/Gateway.pretty") (options "") (descr "")))\n',
        encoding="utf-8",
    )
    monkeypatch.delenv("KICAD_MCP_FOOTPRINT_LIBRARY_DIR")
    reset_config()

    server = build_server("full")
    await call_tool_text(
        server,
        "sch_build_circuit",
        {
            "symbols": [
                {
                    "library": "Device",
                    "symbol_name": "R",
                    "reference": "J1",
                    "value": "Custom",
                    "footprint": "Gateway:Custom",
                    "x_mm": 50.8,
                    "y_mm": 50.8,
                }
            ]
        },
    )

    result = await call_tool_text(server, "pcb_sync_from_schematic", {})
    pcb_text = (sample_project / "demo.kicad_pcb").read_text(encoding="utf-8")

    assert "New footprints added: 1" in result
    assert '(property "Reference" "J1"' in pcb_text
    assert '(net "VIN")' in pcb_text
    assert '(net "GND")' in pcb_text


@pytest.mark.anyio
async def test_pcb_ratsnest_uses_file_fallback_when_live_nets_are_unavailable(
    sample_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (sample_project / "demo.kicad_pcb").write_text(
        '(kicad_pcb (version 20250316) (net 1 "GND"))\n',
        encoding="utf-8",
    )
    monkeypatch.setattr("kicad_mcp.tools.pcb.get_board", lambda: object())
    server = build_server("pcb")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    text = await call_tool_text(server, "pcb_get_ratsnest", {})

    assert "Source: file-backed" in text
    assert "TOOL_EXECUTION_FAILED" not in text
