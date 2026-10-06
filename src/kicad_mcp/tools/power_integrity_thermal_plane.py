"""Thin FastMCP adapter for copper-plane thermal spreading analysis."""

# pyright: reportUnusedFunction=false

from __future__ import annotations

from mcp.server.mcpserver import MCPServer as FastMCP

from ..models.power_integrity import ThermalPlaneSpreadInput
from ..models.verdict import VerdictReport
from ..power_integrity.thermal_plane_spreading import PowerIntegrityThermalPlaneService


def register(
    mcp: FastMCP,
    service: PowerIntegrityThermalPlaneService | None = None,
) -> None:
    """Register copper-plane thermal spreading tools."""
    thermal_service = service or PowerIntegrityThermalPlaneService()

    @mcp.tool()
    def thermal_simulate_plane_spreading(
        power_w: float,
        plane_width_mm: float,
        plane_height_mm: float,
        source_width_mm: float = 5.0,
        source_height_mm: float = 5.0,
        copper_oz: float = 1.0,
        ambient_c: float = 25.0,
        film_coefficient_w_per_m2_k: float = 20.0,
        max_temp_rise_c: float = 40.0,
    ) -> VerdictReport:
        """Solve copper-plane heat spreading with a 2-D finite-difference thermal solver.

        Models a hot source dissipating ``power_w`` into a copper plane that loses heat to
        ambient through both faces (``film_coefficient_w_per_m2_k`` is the combined
        top+bottom film coefficient). Returns the peak and average temperature rise from a
        genuine distributed steady-state solve, with a PASS/WARN/FAIL verdict against
        ``max_temp_rise_c``. This is a 2-D spreading solve, not a 3-D FEA with airflow.
        """
        payload = ThermalPlaneSpreadInput(
            power_w=power_w,
            plane_width_mm=plane_width_mm,
            plane_height_mm=plane_height_mm,
            source_width_mm=source_width_mm,
            source_height_mm=source_height_mm,
            copper_oz=copper_oz,
            ambient_c=ambient_c,
            film_coefficient_w_per_m2_k=film_coefficient_w_per_m2_k,
            max_temp_rise_c=max_temp_rise_c,
        )
        return thermal_service.analyze(payload)
