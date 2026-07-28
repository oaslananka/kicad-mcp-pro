"""Registration contract tests for validation policy-state tools."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from kicad_mcp.tools.metadata import get_tool_metadata
from kicad_mcp.tools.validation_policy_state import ValidationPolicyStateDependencies, register


class FakeService:
    def list_drc_exclusions(self) -> str:
        return "drc-list"

    def add_drc_exclusions(self, reason: str = "Reviewed — not actionable.") -> str:
        return reason

    def remove_drc_exclusion(self, uuid: str) -> str:
        return uuid

    def validate_drc_exclusions(self) -> str:
        return "drc-validate"

    def list_erc_rules(self) -> str:
        return "erc-list"

    def set_erc_rule_severity(self, rule_name: str, severity: str) -> str:
        return f"{rule_name}:{severity}"

    def reset_erc_rules(self, rule_name: str | None = None) -> str:
        return str(rule_name)


def test_register_preserves_tool_names_parameters_and_annotations() -> None:
    mcp = FastMCP("test")
    register(mcp, ValidationPolicyStateDependencies(service=FakeService()))
    tools = {
        tool.name: tool
        for tool in mcp._tool_manager.list_tools()  # pyright: ignore[reportPrivateUsage]
    }
    assert set(tools) == {
        "drc_list_exclusions",
        "drc_add_exclusion",
        "drc_remove_exclusion",
        "drc_validate_exclusions",
        "erc_list_rules",
        "erc_set_rule_severity",
        "erc_reset_rules",
    }
    assert tools["drc_add_exclusion"].parameters["properties"]["reason"]["default"] == (
        "Reviewed — not actionable."
    )
    assert tools["erc_set_rule_severity"].parameters["required"] == ["rule_name", "severity"]
    assert tools["erc_reset_rules"].parameters["properties"]["rule_name"]["default"] is None
    for name in tools:
        metadata = get_tool_metadata(name)
        assert metadata is not None
        assert metadata.headless_compatible
