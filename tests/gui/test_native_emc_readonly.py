"""Opt-in real Windows IPC acceptance for the read-only EMC tool family."""

from __future__ import annotations

import asyncio
import hashlib
import os
import sys
import tempfile
from pathlib import Path

import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from kicad_mcp.config import reset_config
from kicad_mcp.connection import get_board, reset_connection
from kicad_mcp.pcb.live_edit_runtime import reset_live_edit_service
from tests.conftest import tool_text
from tests.gui.test_native_ipc_discovery_recovery import (
    OPT_IN,
    _configure_private_project,
    _installed_bin_dir,
    _private_editor,
)
from tests.integration.test_mcp_native_v2_protocol import (
    _configure_native_v2_server,
    _running_http_server,
)
from tests.integration.test_routing_native_drc_preflight import _run_native_python

pytestmark = [
    pytest.mark.gui,
    pytest.mark.slow,
    pytest.mark.skipif(
        sys.platform != "win32" or not os.environ.get(OPT_IN),
        reason=f"Set {OPT_IN} to an authorized local KiCad 10.0 bin directory",
    ),
]

# Independent native fixture construction only; production uses IPC, not SWIG.
_NATIVE_FIXTURE = """
import sys
import pcbnew

board = pcbnew.BOARD()
board.SetCopperLayerCount(4)
def point(x, y):
    return pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y))
for start, end in [((0, 0), (20, 0)), ((20, 0), (20, 20)),
                   ((20, 20), (0, 20)), ((0, 20), (0, 0))]:
    shape = pcbnew.PCB_SHAPE(board)
    shape.SetShape(pcbnew.SHAPE_T_SEGMENT)
    shape.SetStart(point(*start))
    shape.SetEnd(point(*end))
    shape.SetLayer(pcbnew.Edge_Cuts)
    board.Add(shape)
ground = pcbnew.NETINFO_ITEM(board, 'GND')
board.Add(ground)
signal = pcbnew.NETINFO_ITEM(board, 'USB_P')
board.Add(signal)
zone = pcbnew.ZONE(board)
zone.SetLayer(pcbnew.In1_Cu)
zone.SetNetCode(ground.GetNetCode())
zone.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_NEVER)
zone.SetLocalClearance(pcbnew.FromMM(0.2))
zone.SetMinThickness(pcbnew.FromMM(0.1))
outline = zone.Outline()
outline.NewOutline()
for x, y in [(1, 1), (19, 1), (19, 19), (1, 19)]:
    outline.Append(point(x, y), 0, -1)
outline.NewHole(0)
for x, y in [(8, 8), (8, 12), (12, 12), (12, 8)]:
    outline.Append(point(x, y), 0, 0)
board.Add(zone)
track = pcbnew.PCB_TRACK(board)
track.SetStart(point(4.05, 10))
track.SetEnd(point(16.05, 10))
track.SetLayer(pcbnew.F_Cu)
track.SetWidth(pcbnew.FromMM(0.25))
track.SetNetCode(signal.GetNetCode())
board.Add(track)
assert pcbnew.ZONE_FILLER(board).Fill(board.Zones())
assert pcbnew.SaveBoard(sys.argv[1], board)
reopened = pcbnew.LoadBoard(sys.argv[1])
fill = list(reopened.Zones())[0].GetFilledPolysList(pcbnew.In1_Cu)
covered = sum(fill.Contains(point(4.05 + i * 0.1, 10)) for i in range(121))
assert covered == 81, covered
print('Native stored-fill baseline: 81/121 covered, 40 uncovered')
"""

_EMC_CALLS = {
    "emc_check_ground_plane_voids": {},
    "emc_check_return_path_continuity": {"signal_net": "USB_P", "reference_plane_layer": "In1_Cu"},
    "emc_check_split_plane_crossing": {"signal_nets": ["USB_P"]},
    "emc_check_decoupling_placement": {},
    "emc_check_via_stitching": {},
    "emc_check_differential_pair_symmetry": {"net_p": "USB_P", "net_n": "USB_N"},
    "emc_check_high_speed_routing_rules": {"net_class": "USB"},
    "emc_run_full_compliance": {},
}


async def _exercise_readonly_emc(board: Path) -> None:
    native = get_board()
    assert Path(native.get_project().path).resolve() == board.parent.resolve()
    assert native.name == board.name
    before = native.get_as_string()
    server = _configure_native_v2_server(board.parent, profile="expert")
    with _running_http_server(server.streamable_http_app()) as url:
        async with streamable_http_client(url + "/mcp") as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                catalog = {tool.name: tool for tool in (await session.list_tools()).tools}
                assert set(_EMC_CALLS) <= catalog.keys()
                assert "pcb_add_track" not in catalog
                assert "export_manufacturing_package" not in catalog
                for name, args in _EMC_CALLS.items():
                    annotations = catalog[name].annotations
                    assert annotations is not None
                    assert annotations.read_only_hint is True
                    result = await session.call_tool(name, args)
                    assert not result.is_error, tool_text(result)
                    assert result.structured_content is not None
                    payload = result.structured_content.get("result", result.structured_content)
                    assert payload["verdict"] in {"PASS", "WARN", "FAIL"}, name
                    if name == "emc_check_return_path_continuity":
                        assert payload["verdict"] == "WARN"
                        assert "81/121 covered, 40 uncovered" in payload["summary"]
                denied = await session.call_tool(
                    "pcb_add_track",
                    {
                        "x1_mm": 2,
                        "y1_mm": 2,
                        "x2_mm": 3,
                        "y2_mm": 2,
                        "layer": "F_Cu",
                    },
                )
                assert denied.is_error
                assert "MODE_FORBIDDEN" in tool_text(denied)
    assert native.get_as_string() == before


def test_native_windows_emc_readonly(monkeypatch: pytest.MonkeyPatch) -> None:
    bin_dir = _installed_bin_dir(os.environ[OPT_IN])
    with tempfile.TemporaryDirectory(prefix="kicad-emc-") as temp:
        try:
            board, env, endpoint = _configure_private_project(
                Path(temp), bin_dir, monkeypatch, mode="readonly"
            )
            _run_native_python(bin_dir / "python.exe", _NATIVE_FIXTURE, board, env=env)
            digest = hashlib.sha256(board.read_bytes()).hexdigest()
            with _private_editor(bin_dir / "pcbnew.exe", board, env, endpoint):
                asyncio.run(_exercise_readonly_emc(board))
            assert hashlib.sha256(board.read_bytes()).hexdigest() == digest
        finally:
            reset_live_edit_service()
            reset_connection()
            reset_config()
