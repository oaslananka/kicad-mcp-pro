"""Signal-integrity helpers for trace impedance, skew, and placement heuristics.

These are first-order, closed-form estimates (IPC-2141/Wheeler-class formulas), not a
substitute for a 2D/3D field solver, EM simulation, or formal sign-off. Treat results as
a fast first-pass review; accuracy is typically ~5-10%. A field-solver mode is planned
(P3-T1/P3-T3).
"""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer as FastMCP

from ..pcb.geometry import point_xy_mm

__all__ = ["point_xy_mm", "register"]


def register(mcp: FastMCP) -> None:
    """Register signal-integrity tools."""

    from . import signal_integrity_solver_capabilities

    signal_integrity_solver_capabilities.register(mcp)

    from . import signal_integrity_impedance

    signal_integrity_impedance.register(mcp)

    from . import signal_integrity_differential_pair_skew

    signal_integrity_differential_pair_skew.register(mcp)

    from . import signal_integrity_length_matching

    signal_integrity_length_matching.register(mcp)

    from . import signal_integrity_high_speed_channel

    signal_integrity_high_speed_channel.register(mcp)

    from . import signal_integrity_stackup_generation

    signal_integrity_stackup_generation.register(mcp)

    from . import signal_integrity_via_stub

    signal_integrity_via_stub.register(mcp)

    from . import signal_integrity_decoupling_placement

    signal_integrity_decoupling_placement.register(mcp)

    from . import signal_integrity_dielectric_materials

    signal_integrity_dielectric_materials.register(mcp)

    from . import signal_integrity_stackup_synthesis

    signal_integrity_stackup_synthesis.register(mcp)

    from . import signal_integrity_net_class_binding

    signal_integrity_net_class_binding.register(mcp)
