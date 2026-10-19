"""Runtime tool-surface boundaries for the opt-in reference ChatGPT–Ops host."""

from __future__ import annotations

import asyncio

import pytest

from kicad_mcp.config import reset_config
from kicad_mcp.evals.reference_agent_runner import (
    ReferenceAgentPhase,
    ReferenceAgentRunnerError,
    reviewed_mcp_tools,
)
from kicad_mcp.evals.reference_ops_server import build_reference_ops_server


@pytest.fixture(autouse=True)
def _isolate_phase_environment(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("KICAD_MCP_PROFILE", "schematic_authoring")
    monkeypatch.setenv("KICAD_MCP_OPERATING_MODE", "write")
    monkeypatch.setenv("KICAD_MCP_TRANSPORT", "stdio")
    reset_config()
    try:
        yield
    finally:
        reset_config()


def test_schematic_tools_are_exact_reviewed_allowlist_in_both_layers() -> None:
    server = build_reference_ops_server(phase_name="schematic")
    server.filter_runtime_tools = False
    exact = {
        name.removeprefix("mcp__kicad__")
        for name in reviewed_mcp_tools(ReferenceAgentPhase.for_name("schematic"))
    }
    names = {tool.name for tool in server.list_tools_sync()}
    assert len(exact) == 35
    assert names == exact
    assert server.allowed_tool_names == exact
    assert server.execution_tool_names == exact
    assert "drc_rule_delete" not in names


def test_nonreviewed_tool_is_rejected_at_execution_boundary() -> None:
    server = build_reference_ops_server(phase_name="schematic")
    result = asyncio.run(server.call_tool("drc_rule_delete", {"name": "UNREVIEWED"}))
    assert result.is_error is True
    assert "not available in this server execution surface" in str(result)
    assert result.structured_content is None


@pytest.mark.parametrize(
    ("profile", "operating_mode", "phase"),
    [
        ("review", "write", "schematic"),
        ("schematic_authoring", "readonly", "schematic"),
        ("schematic_authoring", "write", "manufacturing"),
        ("pcb_layout", "write", "schematic"),
    ],
)
def test_wrong_profile_or_phase_refuses_server(
    monkeypatch: pytest.MonkeyPatch, profile: str, operating_mode: str, phase: str
) -> None:
    monkeypatch.setenv("KICAD_MCP_PROFILE", profile)
    monkeypatch.setenv("KICAD_MCP_OPERATING_MODE", operating_mode)
    reset_config()
    with pytest.raises(ReferenceAgentRunnerError):
        build_reference_ops_server(phase_name=phase)
