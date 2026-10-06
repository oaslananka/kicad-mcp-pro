"""Thin FastMCP adapter for thermal-via estimation."""

# pyright: reportUnusedFunction=false

from __future__ import annotations

from collections.abc import Callable

from mcp.server.mcpserver import MCPServer as FastMCP

from ..connection import get_board
from ..models.power_integrity import ThermalViaInput
from ..power_integrity.thermal_via import (
    DEFAULT_BOARD_THICKNESS_MM,
    PowerIntegrityThermalViaService,
)
from ..utils.units import nm_to_mm

BoardThicknessProvider = Callable[[], float]


def _board_thickness_mm() -> float:
    stackup = get_board().get_stackup()
    total_nm = sum(int(getattr(layer, "thickness", 0)) for layer in getattr(stackup, "layers", []))
    if total_nm <= 0:
        return DEFAULT_BOARD_THICKNESS_MM
    return nm_to_mm(total_nm)


def register(
    mcp: FastMCP,
    service: PowerIntegrityThermalViaService | None = None,
    *,
    board_thickness_provider: BoardThicknessProvider = _board_thickness_mm,
) -> None:
    """Register thermal-via estimation tools."""
    thermal_via_service = service or PowerIntegrityThermalViaService()

    @mcp.tool()
    def thermal_calculate_via_count(
        power_w: float | None = None,
        package_power_w: float | None = None,
        ambient_c: float = 25.0,
        max_junction_c: float = 125.0,
        theta_ja_deg_c_w: float = 40.0,
        via_diameter_mm: float = 0.3,
        thermal_resistance_target: float = 5.0,
    ) -> str:
        """Estimate thermal via count from package heat and board thermal resistance."""
        payload = ThermalViaInput(
            power_w=power_w,
            package_power_w=package_power_w,
            ambient_c=ambient_c,
            max_junction_c=max_junction_c,
            theta_ja_deg_c_w=theta_ja_deg_c_w,
            via_diameter_mm=via_diameter_mm,
            thermal_resistance_target=thermal_resistance_target,
        )
        return thermal_via_service.estimate(
            payload,
            board_thickness_mm=board_thickness_provider(),
        )
