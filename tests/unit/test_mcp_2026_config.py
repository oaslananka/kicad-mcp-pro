from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from kicad_mcp.config import KiCadMCPConfig

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_ROOT = ROOT / "tests" / "contracts" / "mcp" / "2026-07-28"


def test_candidate_contract_fixtures_pin_the_release_candidate_source() -> None:
    provenance = json.loads((CONTRACT_ROOT / "provenance.json").read_text(encoding="utf-8"))
    discover_request = json.loads(
        (CONTRACT_ROOT / "server-discover.request.json").read_text(encoding="utf-8")
    )
    discover_response = json.loads(
        (CONTRACT_ROOT / "server-discover.response.json").read_text(encoding="utf-8")
    )
    tools_request = json.loads(
        (CONTRACT_ROOT / "tools-list.request.json").read_text(encoding="utf-8")
    )
    tools_response = json.loads(
        (CONTRACT_ROOT / "tools-list.response.json").read_text(encoding="utf-8")
    )

    assert provenance == {
        "source": "https://github.com/modelcontextprotocol/modelcontextprotocol",
        "commit": "73720340e7c42ddaf4b303b86e81663e9a2796d0",
        "protocolVersion": "2026-07-28",
        "capturedAt": "2026-07-22",
        "status": "release-candidate-draft",
    }
    for request in (discover_request, tools_request):
        meta = request["params"]["_meta"]
        assert meta["io.modelcontextprotocol/protocolVersion"] == "2026-07-28"
        assert meta["io.modelcontextprotocol/clientCapabilities"] == {}
    for response in (discover_response, tools_response):
        assert response["result"]["resultType"] == "complete"
        assert response["result"]["ttlMs"] >= 0
        assert response["result"]["cacheScope"] in {"public", "private"}


def test_protocol_lane_defaults_to_stable(fake_cli: Path) -> None:
    config = KiCadMCPConfig(kicad_cli=fake_cli)

    assert config.protocol_lane == "stable"


def test_candidate_protocol_lane_can_be_selected_explicitly(fake_cli: Path) -> None:
    config = KiCadMCPConfig(
        kicad_cli=fake_cli,
        transport="streamable-http",
        protocol_lane="2026-07-28-rc",
    )

    assert config.protocol_lane == "2026-07-28-rc"
    assert config.stateful_http is False
    assert config.safe_diagnostics()["protocol_lane"] == "2026-07-28-rc"


def test_candidate_protocol_lane_loads_from_environment(
    monkeypatch: pytest.MonkeyPatch,
    fake_cli: Path,
) -> None:
    monkeypatch.setenv("KICAD_MCP_TRANSPORT", "streamable-http")
    monkeypatch.setenv("KICAD_MCP_PROTOCOL_LANE", "2026-07-28-rc")
    monkeypatch.setenv("KICAD_MCP_KICAD_CLI", str(fake_cli))

    config = KiCadMCPConfig()

    assert config.protocol_lane == "2026-07-28-rc"


def test_candidate_protocol_lane_accepts_http_alias(fake_cli: Path) -> None:
    config = KiCadMCPConfig(
        kicad_cli=fake_cli,
        transport="http",
        protocol_lane="2026-07-28-rc",
    )

    assert config.transport == "streamable-http"


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"transport": "stdio"}, "requires transport='streamable-http'"),
        ({"transport": "sse"}, "requires transport='streamable-http'"),
        (
            {"transport": "streamable-http", "stateful_http": True},
            "requires stateful_http=false",
        ),
        (
            {"transport": "streamable-http", "legacy_sse": True},
            "does not support legacy_sse",
        ),
        (
            {"transport": "streamable-http", "enable_tasks": True},
            "does not support the legacy Tasks implementation",
        ),
    ],
)
def test_candidate_protocol_lane_rejects_incompatible_runtime_modes(
    overrides: dict[str, Any],
    message: str,
    fake_cli: Path,
) -> None:
    with pytest.raises(ValidationError, match=message):
        KiCadMCPConfig(
            kicad_cli=fake_cli,
            protocol_lane="2026-07-28-rc",
            **overrides,
        )
