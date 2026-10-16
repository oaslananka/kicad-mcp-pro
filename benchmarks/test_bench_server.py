"""Benchmarks for MCP server discovery (``tools/list``) on the full profile."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.server.mcpserver import MCPServer


def test_tools_list_full_profile(benchmark, full_server: MCPServer) -> None:
    tools = benchmark(full_server.list_tools_sync)
    assert tools
