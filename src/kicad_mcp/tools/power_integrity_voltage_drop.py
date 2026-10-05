"""Thin FastMCP adapter for PDN voltage-drop estimation."""

# pyright: reportUnusedFunction=false

from __future__ import annotations

from dataclasses import dataclass

from mcp.server.mcpserver import MCPServer as FastMCP

from ..power_integrity.voltage_drop import PowerIntegrityVoltageDropService


@dataclass(frozen=True)
class PowerIntegrityVoltageDropDependencies:
    service: PowerIntegrityVoltageDropService


def _default_dependencies() -> PowerIntegrityVoltageDropDependencies:
    return PowerIntegrityVoltageDropDependencies(service=PowerIntegrityVoltageDropService())


def register(
    mcp: FastMCP,
    dependencies: PowerIntegrityVoltageDropDependencies | None = None,
) -> None:
    """Register PDN voltage-drop tools."""
    deps = dependencies or _default_dependencies()

    @mcp.tool()
    def pdn_calculate_voltage_drop(
        current_a: float,
        trace_width_mm: float,
        trace_length_mm: float,
        copper_oz: float = 1.0,
        max_temp_rise_c: float = 10.0,
        internal_layer: bool = False,
    ) -> str:
        """Estimate DC voltage drop, trace resistance, and IPC-2221 current-density fusing.

        ``max_temp_rise_c`` is the temperature-rise budget; the verdict is PASS within it,
        WARN up to 2x, FAIL beyond. Set ``internal_layer=True`` for a buried trace (lower
        ampacity).
        """
        return deps.service.calculate_voltage_drop(
            current_a,
            trace_width_mm,
            trace_length_mm,
            copper_oz,
            max_temp_rise_c,
            internal_layer,
        )
