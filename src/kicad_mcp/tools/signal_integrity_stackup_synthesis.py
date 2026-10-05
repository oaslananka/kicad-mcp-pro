"""Thin FastMCP adapter for stackup synthesis."""

# pyright: reportUnusedFunction=false

from __future__ import annotations

from dataclasses import dataclass

from mcp.server.mcpserver import MCPServer as FastMCP

from ..signal_integrity.stackup_synthesis import SignalIntegrityStackupSynthesisService


@dataclass(frozen=True)
class SignalIntegrityStackupSynthesisDependencies:
    service: SignalIntegrityStackupSynthesisService


def _default_dependencies() -> SignalIntegrityStackupSynthesisDependencies:
    return SignalIntegrityStackupSynthesisDependencies(
        service=SignalIntegrityStackupSynthesisService()
    )


def register(
    mcp: FastMCP,
    dependencies: SignalIntegrityStackupSynthesisDependencies | None = None,
) -> None:
    """Register stackup synthesis tools."""
    deps = dependencies or _default_dependencies()

    @mcp.tool()
    def si_synthesize_stackup_for_interfaces(
        interfaces: list[dict[str, object]],
        cost_tier: str = "standard",
        board_thickness_mm: float = 1.6,
    ) -> str:
        """Synthesise a PCB stackup that meets the impedance requirements of the given interfaces.

        Analyses each InterfaceSpec dict and recommends:
        - Layer count
        - Dielectric material
        - Copper weight per layer
        - Outer dielectric thickness for target impedance
        - Net class settings (impedance, clearance, diff-pair gap)

        Args:
            interfaces: List of InterfaceSpec dicts (matching project_set_design_intent
                interface format). Each must have at least ``kind`` and optionally
                ``impedance_target_ohm``, ``differential``, ``diff_skew_max_ps``.
            cost_tier: ``"standard"`` (FR4), ``"midloss"`` (FR4 mid/low-loss),
                ``"highspeed"`` (Rogers/Megtron). Overrides material selection.
            board_thickness_mm: Target board thickness in mm (1.0, 1.6, 2.0, 3.2).

        Returns:
            Recommended stackup specification and net class table in human-readable
            markdown, ready to pass to pcb_set_stackup() and pcb_set_net_class().
        """
        return deps.service.synthesize(
            interfaces=interfaces,
            cost_tier=cost_tier,
            board_thickness_mm=board_thickness_mm,
        )
