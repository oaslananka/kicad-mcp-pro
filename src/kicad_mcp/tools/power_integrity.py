"""Power-integrity and thermal MCP composition root."""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer as FastMCP


def register(mcp: FastMCP) -> None:
    """Register power-integrity and thermal tools."""
    from . import (
        power_integrity_copper_weight,
        power_integrity_decoupling,
        power_integrity_pdn_mesh,
        power_integrity_power_plane,
        power_integrity_thermal_plane,
        power_integrity_thermal_pour,
        power_integrity_thermal_via,
        power_integrity_voltage_drop,
    )

    power_integrity_voltage_drop.register(mcp)
    power_integrity_pdn_mesh.register(mcp)
    power_integrity_decoupling.register(mcp)
    power_integrity_copper_weight.register(mcp)
    power_integrity_power_plane.register(mcp)
    power_integrity_thermal_via.register(mcp)
    power_integrity_thermal_pour.register(mcp)
    power_integrity_thermal_plane.register(mcp)
