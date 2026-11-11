"""Negative regression cases for the single authoritative MCP tool registry."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from kicad_mcp import runtime_capability_catalog as registry


@pytest.mark.parametrize(
    ("case", "error"),
    [
        ("duplicate_registration", "Duplicate tool name"),
        ("two_categories", "belongs to multiple router categories"),
        ("router_mismatch", "Registered MCP tools do not match"),
        ("missing_metadata", "Missing capability metadata"),
        ("invalid_input_schema", "Invalid MCP input object schema"),
    ],
)
def test_bad_registered_contracts_are_rejected(
    monkeypatch: pytest.MonkeyPatch, case: str, error: str
) -> None:
    """Never publish a catalog for unregistered, ambiguous or malformed tools."""
    from kicad_mcp import server as server_module

    def tool(name: str, schema_type: str = "object") -> SimpleNamespace:
        return SimpleNamespace(
            name=name,
            description="Synthetic only",
            input_schema={"type": schema_type},
        )

    registered = [tool("synthetic")]
    groups = {"main": {"tools": ["synthetic"]}}
    records = {"synthetic": object()}
    if case == "duplicate_registration":
        registered.append(tool("synthetic"))
    elif case == "two_categories":
        groups["secondary"] = {"tools": ["synthetic"]}
    elif case == "router_mismatch":
        groups["main"]["tools"] = ["not_registered"]
    elif case == "missing_metadata":
        records = {}
    elif case == "invalid_input_schema":
        registered = [tool("synthetic", "array")]

    class FakeRegisteredServer:
        def list_tools_sync(self) -> list[SimpleNamespace]:
            return registered

    monkeypatch.setattr(server_module, "build_server", lambda _profile: FakeRegisteredServer())
    monkeypatch.setattr(registry, "TOOL_CATEGORIES", groups)
    monkeypatch.setattr(registry, "all_records", lambda: records)
    with pytest.raises(ValueError, match=error):
        registry.build_local_catalog_entries()
