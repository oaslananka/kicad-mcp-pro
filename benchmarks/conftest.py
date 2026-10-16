"""Shared fixtures for the CodSpeed benchmark suite.

These benchmarks are run with ``pytest benchmarks/ --codspeed`` and are kept
separate from ``tests/`` so the regular test, coverage, and latency-budget
gates are unaffected.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from mcp.server.mcpserver import MCPServer


def _unavailable_ipc_state() -> object:
    """Return a deterministic "KiCad not running" IPC state."""
    from kicad_mcp.ipc.capabilities import KiCadIpcCapabilityState
    from kicad_mcp.ipc.discovery import KiCadIpcEndpoint

    return KiCadIpcCapabilityState(
        endpoint=KiCadIpcEndpoint(
            socket_path=None,
            source="default",
            token_configured=False,
            timeout_ms=10_000,
        ),
        reachable=False,
        version=None,
        api_version=None,
        major_version=None,
        live_pcb_context=False,
        live_schematic_context=False,
        headless_requested=False,
        operations={},
        diagnostics=(),
    )


@pytest.fixture(scope="session")
def full_server() -> Iterator[MCPServer]:
    """Build the full-profile MCP server once, isolated from the host KiCad setup."""
    from kicad_mcp.config import reset_config
    from kicad_mcp.server import build_server

    with pytest.MonkeyPatch.context() as patch:
        for name in tuple(os.environ):
            if name.startswith(("KICAD_MCP_", "KICAD_API_")) or name == "KICAD_CLI_PATH":
                patch.delenv(name)
        patch.setattr("kicad_mcp.server.get_ipc_capability_state", _unavailable_ipc_state)
        reset_config()
        server = build_server("full")
        # Warm the one-time capability probe so benchmarks measure steady state.
        server.list_tools_sync()
        yield server
    reset_config()
