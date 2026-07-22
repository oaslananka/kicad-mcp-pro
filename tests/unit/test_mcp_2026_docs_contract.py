from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ADR = ROOT / "docs" / "adr" / "0006-mcp-2026-stateless-compatibility-lane.md"
TRANSPORT = ROOT / "docs" / "mcp" / "transport.md"
API_REFERENCE = ROOT / "docs" / "mcp" / "api-reference.md"
MKDOCS = ROOT / "mkdocs.yml"


def test_candidate_protocol_operator_documentation_is_explicitly_release_gated() -> None:
    adr = ADR.read_text(encoding="utf-8")
    transport = TRANSPORT.read_text(encoding="utf-8")
    api_reference = API_REFERENCE.read_text(encoding="utf-8")
    navigation = MKDOCS.read_text(encoding="utf-8")

    assert "**Status:** Accepted" in adr
    assert "## Component state inventory" in adr
    for component in (
        "Streamable HTTP",
        "Tasks",
        "Apps",
        "Authorization",
        "Caching",
        "Telemetry and benchmarks",
        "Registry metadata",
    ):
        assert component in adr

    assert "KICAD_MCP_PROTOCOL_LANE=2026-07-28-rc" in transport
    assert "release-candidate compatibility lane" in transport
    assert "not a general-availability protocol advertisement" in transport
    assert "Mcp-Method" in transport
    assert "Mcp-Name" in transport
    assert "server/discover" in transport
    assert "Mcp-Session-Id" in transport
    assert "unset KICAD_MCP_PROTOCOL_LANE" in transport

    assert "Current public contract" in api_reference
    assert "`2025-11-25`" in api_reference
    assert "Candidate compatibility lane" in api_reference
    assert "`2026-07-28`" in api_reference
    assert "server.json remains on `2025-11-25`" in api_reference

    for gate in (
        "final MCP 2026-07-28 specification",
        "stable MCP Python SDK",
        "supported host smoke tests",
        "Tasks and Apps extension parity",
        "tested rollback",
    ):
        assert gate in adr

    assert "MCP 2026 Stateless Compatibility Lane" in navigation
    assert "adr/0006-mcp-2026-stateless-compatibility-lane.md" in navigation
