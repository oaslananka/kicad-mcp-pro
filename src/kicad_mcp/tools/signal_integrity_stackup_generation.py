"""Thin FastMCP adapter for signal-integrity stackup generation tools."""

# pyright: reportUnusedFunction=false

from __future__ import annotations

from dataclasses import dataclass

from mcp.server.mcpserver import MCPServer as FastMCP

from ..signal_integrity.stackup_generation import (
    SignalIntegrityStackupGenerationService,
)


@dataclass(frozen=True)
class SignalIntegrityStackupGenerationDependencies:
    service: SignalIntegrityStackupGenerationService


def _default_dependencies() -> SignalIntegrityStackupGenerationDependencies:
    return SignalIntegrityStackupGenerationDependencies(
        service=SignalIntegrityStackupGenerationService()
    )


def register(
    mcp: FastMCP,
    dependencies: SignalIntegrityStackupGenerationDependencies | None = None,
) -> None:
    """Register signal-integrity stackup generation tools."""
    deps = dependencies or _default_dependencies()

    @mcp.tool()
    def si_generate_stackup(
        layer_count: int = 4,
        target_impedance_ohm: float = 50.0,
        manufacturer: str = "JLCPCB",
        er: float = 4.2,
        copper_oz: float = 1.0,
    ) -> str:
        """Generate a practical board stackup recommendation and target trace geometry."""
        return deps.service.generate(
            layer_count,
            target_impedance_ohm,
            manufacturer,
            er,
            copper_oz,
        )
