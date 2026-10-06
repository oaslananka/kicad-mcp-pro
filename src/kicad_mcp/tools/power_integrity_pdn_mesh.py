"""Thin FastMCP adapter for PDN mesh analysis."""

# pyright: reportUnusedFunction=false

from __future__ import annotations

from mcp.server.mcpserver import MCPServer as FastMCP

from ..models.verdict import VerdictReport
from ..power_integrity.pdn_mesh_check import PowerIntegrityPdnMeshService


def register(
    mcp: FastMCP,
    service: PowerIntegrityPdnMeshService | None = None,
) -> None:
    """Register PDN mesh analysis tools."""
    pdn_service = service or PowerIntegrityPdnMeshService()

    @mcp.tool()
    def check_power_integrity(
        net_name: str,
        source_ref: str,
        load_refs: list[str],
        trace_width_mm: float,
        load_current_a: float = 0.1,
        trace_length_mm: float = 100.0,
        copper_weight_oz: float = 1.0,
        nominal_voltage_v: float = 3.3,
        frequency_points_hz: list[float] | None = None,
        decoupling_caps_uf: list[float] | None = None,
        target_impedance_ohm: float | None = None,
        decoupling_esr_mohm: float = 20.0,
        decoupling_esl_nh: float = 1.0,
    ) -> VerdictReport:
        """Run a lightweight PDN mesh voltage-drop check for a power net."""
        return pdn_service.analyze(
            net_name=net_name,
            source_ref=source_ref,
            load_refs=load_refs,
            trace_width_mm=trace_width_mm,
            load_current_a=load_current_a,
            trace_length_mm=trace_length_mm,
            copper_weight_oz=copper_weight_oz,
            nominal_voltage_v=nominal_voltage_v,
            frequency_points_hz=frequency_points_hz,
            decoupling_caps_uf=decoupling_caps_uf,
            target_impedance_ohm=target_impedance_ohm,
            decoupling_esr_mohm=decoupling_esr_mohm,
            decoupling_esl_nh=decoupling_esl_nh,
        )
