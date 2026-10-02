from __future__ import annotations

import json
from pathlib import Path

import yaml

from kicad_mcp import compatibility

ROOT = Path(__file__).resolve().parents[2]


def test_public_contract_promotes_final_2026_without_dropping_legacy_wire_support() -> None:
    assert compatibility.MCP_PROTOCOL_VERSION == "2026-07-28"
    assert getattr(compatibility, "MCP_LEGACY_PROTOCOL_VERSION", None) == "2025-11-25"

    matrix = yaml.safe_load((ROOT / "compatibility.yaml").read_text(encoding="utf-8"))
    assert matrix["mcp"]["protocolVersion"] == "2026-07-28"
    assert matrix["mcp"]["supportedProtocolVersions"] == ["2026-07-28", "2025-11-25"]
    assert "nextProtocolVersion" not in matrix["mcp"]


def test_registry_metadata_advertises_modern_primary_and_legacy_compatibility() -> None:
    registry = json.loads((ROOT / "server.json").read_text(encoding="utf-8"))
    meta = registry["_meta"]["io.github.oaslananka/kicad-mcp-pro"]

    assert meta["supportedMcpProtocolVersions"] == ["2026-07-28", "2025-11-25"]
    assert meta["serverInfo"]["mcpProtocolVersion"] == "2026-07-28"
