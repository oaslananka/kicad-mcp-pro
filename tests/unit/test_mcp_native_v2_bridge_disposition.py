from __future__ import annotations

import pytest
from mcp.server.caching import CacheHint

from kicad_mcp.server import KiCadFastMCP

EXPECTED_NATIVE_CACHE_HINTS = {
    "server/discover": CacheHint(ttl_ms=3_600_000, scope="private"),
    "tools/list": CacheHint(ttl_ms=300_000, scope="private"),
    "prompts/list": CacheHint(ttl_ms=300_000, scope="private"),
    "resources/list": CacheHint(ttl_ms=300_000, scope="private"),
    "resources/templates/list": CacheHint(ttl_ms=300_000, scope="private"),
    "resources/read": CacheHint(ttl_ms=60_000, scope="private"),
}


def test_native_v2_cache_hints_preserve_reviewed_bridge_policy() -> None:
    server = KiCadFastMCP(name="native-cache-policy")

    assert server._lowlevel_server.cache_hints == EXPECTED_NATIVE_CACHE_HINTS


@pytest.mark.anyio
async def test_native_v2_tools_list_is_alphabetical() -> None:
    server = KiCadFastMCP(name="native-order-policy")
    server.filter_runtime_tools = False

    @server.tool()
    def zeta() -> str:
        return "z"

    @server.tool()
    def alpha() -> str:
        return "a"

    tools = await server.list_tools()

    assert [tool.name for tool in tools] == ["alpha", "zeta"]
