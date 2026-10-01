"""MCP resource and tool for server-info/capability discovery."""

from __future__ import annotations

import json

from mcp.server.mcpserver import MCPServer as FastMCP

from ..server_info import get_server_info_contract
from ..tools.metadata import headless_compatible


def register(mcp: FastMCP) -> None:
    """Register the server-info discovery surface."""

    @mcp.resource("kicad://server/info")
    def server_info_resource() -> str:
        """Return versioned server information and capability diagnostics."""
        return json.dumps(get_server_info_contract(), sort_keys=True)

    @mcp.tool(structured_output=True)
    @headless_compatible
    def kicad_get_server_info() -> dict[str, object]:
        """Return versioned server information and capability diagnostics for clients."""
        return get_server_info_contract()
