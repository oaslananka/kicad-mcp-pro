from __future__ import annotations

from pathlib import Path

import pytest
from mcp.server.caching import CacheHint

from kicad_mcp.server import KiCadFastMCP

ROOT = Path(__file__).resolve().parents[2]
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


def test_temporary_rc_translation_bridge_is_removed() -> None:
    assert not (ROOT / "src" / "kicad_mcp" / "protocol_compat.py").exists()

    server_source = (ROOT / "src" / "kicad_mcp" / "server.py").read_text(encoding="utf-8")
    for obsolete_symbol in (
        "_handle_candidate_post",
        "candidate_discover_result",
        "decorate_candidate_response",
        "stable_sdk_request",
        "validate_candidate_request",
    ):
        assert obsolete_symbol not in server_source
