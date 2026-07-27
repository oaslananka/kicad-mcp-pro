# pyright: reportPrivateUsage=false

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from kicad_mcp.tools.metadata import get_tool_metadata
from kicad_mcp.tools.pcb_transaction_lifecycle import (
    PcbTransactionLifecycleDependencies,
    register,
)


class FakeTransactionLifecycleService:
    def begin(self) -> str:
        return "begin"

    def push(self) -> str:
        return "push"

    def drop(self) -> str:
        return "drop"

    def revert(self) -> str:
        return "revert"


def _registered() -> FastMCP:
    server = FastMCP("pcb-transaction-lifecycle-test")
    register(
        server,
        PcbTransactionLifecycleDependencies(service=FakeTransactionLifecycleService()),
    )
    return server


def test_registration_preserves_exact_public_names_and_empty_schemas() -> None:
    tools = {tool.name: tool for tool in _registered()._tool_manager.list_tools()}

    assert set(tools) == {
        "pcb_begin_commit",
        "pcb_push_commit",
        "pcb_drop_commit",
        "pcb_revert",
    }
    for tool in tools.values():
        assert tool.parameters["properties"] == {}
        assert "required" not in tool.parameters


def test_registration_preserves_descriptions_metadata_and_forwarding() -> None:
    tools = {tool.name: tool for tool in _registered()._tool_manager.list_tools()}

    assert tools["pcb_begin_commit"].description.startswith(
        "Begin a transaction group for atomic board modifications."
    )
    assert tools["pcb_push_commit"].description.startswith(
        "Push (commit) the current transaction group to the board."
    )
    assert tools["pcb_drop_commit"].description.startswith(
        "Drop (discard) the current transaction group without applying changes."
    )
    assert tools["pcb_revert"].description.startswith(
        "Revert the board to the last saved state, discarding all unsaved changes."
    )
    assert tools["pcb_begin_commit"].fn() == "begin"
    assert tools["pcb_push_commit"].fn() == "push"
    assert tools["pcb_drop_commit"].fn() == "drop"
    assert tools["pcb_revert"].fn() == "revert"
    for name in tools:
        metadata = get_tool_metadata(name)
        assert metadata is not None
        assert metadata.requires_kicad_running is True
