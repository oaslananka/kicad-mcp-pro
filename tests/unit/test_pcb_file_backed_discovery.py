"""PCB inspection tools with file-backed fallbacks remain discoverable without GUI."""

# pyright: reportPrivateUsage=false

from __future__ import annotations

from mcp.types import Tool

from kicad_mcp.server import _filter_ipc_runtime_tools


class _ClosedPcbState:
    reachable = False
    live_pcb_read = False
    live_pcb_write = False
    live_schematic_read = False
    live_schematic_write = False
    operations: dict[str, object] = {}

    def tool_available(self, _tool_name: str) -> bool:
        return False


def test_tracks_tool_remains_visible_when_gui_unavailable() -> None:
    """File-backed tracks inspection is still useful before opening KiCad."""
    tools = [
        Tool(name="pcb_get_tracks", inputSchema={}),
        Tool(name="pcb_get_zones", inputSchema={}),
    ]
    visible = {
        tool.name
        for tool in _filter_ipc_runtime_tools(
            tools,
            _ClosedPcbState(),  # type: ignore[arg-type]
        )
    }
    assert "pcb_get_tracks" in visible
    assert "pcb_get_zones" not in visible
