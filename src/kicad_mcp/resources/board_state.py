"""MCP resources exposing live KiCad state."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from ..config import get_config
from ..connection import KiCadConnectionError, get_board


def register(mcp: FastMCP) -> None:
    """Register board state resources."""

    @mcp.resource("kicad://board/summary")
    def board_summary_resource() -> str:
        """Live PCB board summary."""
        try:
            board = get_board()
        except KiCadConnectionError as exc:
            return f"KiCad is not connected: {exc}"

        tracks = board.get_tracks()
        footprints = board.get_footprints()
        vias = board.get_vias()
        nets = board.get_nets(netclass_filter=None)
        return (
            f"Board summary\n"
            f"- Tracks: {len(tracks)}\n"
            f"- Vias: {len(vias)}\n"
            f"- Footprints: {len(footprints)}\n"
            f"- Nets: {len(nets)}"
        )

    @mcp.resource("kicad://project/info")
    def project_info_resource() -> str:
        """Current project configuration."""
        cfg = get_config()
        return (
            f"Project directory: {cfg.project_dir}\n"
            f"Project file: {cfg.project_file}\n"
            f"PCB file: {cfg.pcb_file}\n"
            f"Schematic file: {cfg.sch_file}\n"
            f"Output directory: {cfg.output_dir}"
        )

    @mcp.resource("kicad://board/netlist")
    def board_netlist_resource() -> str:
        """Current board S-expression, bounded for safety."""
        cfg = get_config()
        try:
            board = get_board()
        except KiCadConnectionError as exc:
            return f"KiCad is not connected: {exc}"

        data = board.get_as_string()
        if len(data) > cfg.max_text_response_chars:
            return f"{data[: cfg.max_text_response_chars]}\n... [truncated]"
        return data
