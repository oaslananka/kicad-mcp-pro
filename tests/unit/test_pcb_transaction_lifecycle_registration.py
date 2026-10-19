# pyright: reportPrivateUsage=false

from __future__ import annotations

import json

from mcp.server.mcpserver import MCPServer as FastMCP

from kicad_mcp.tools.metadata import get_tool_metadata, infer_tool_annotations
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

    def status_payload(self) -> dict[str, object]:
        return {
            "state": "active",
            "schema_version": "pcb-live-edit-state.v1",
            "board_name": "demo.kicad_pcb",
            "board_fingerprint": "a" * 64,
            "mutation_count": 2,
            "verified_mutation_count": 2,
            "ambiguous_mutation_count": 0,
            "recovery_required": False,
            "transaction_supported": True,
            "last_outcome": None,
        }


def _registered() -> FastMCP:
    server = FastMCP("pcb-transaction-lifecycle-test")
    register(
        server,
        PcbTransactionLifecycleDependencies(get_service=FakeTransactionLifecycleService),
    )
    return server


def test_registration_preserves_exact_public_names_and_empty_schemas() -> None:
    tools = {tool.name: tool for tool in _registered()._tool_manager.list_tools()}

    assert set(tools) == {
        "pcb_begin_commit",
        "pcb_push_commit",
        "pcb_drop_commit",
        "pcb_revert",
        "pcb_get_live_edit_state",
    }
    for name in ("pcb_begin_commit", "pcb_push_commit", "pcb_drop_commit", "pcb_revert"):
        tool = tools[name]
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
    for name in ("pcb_begin_commit", "pcb_push_commit", "pcb_drop_commit", "pcb_revert"):
        metadata = get_tool_metadata(name)
        assert metadata is not None
        assert metadata.requires_kicad_running is True

    state_tool = tools["pcb_get_live_edit_state"]
    payload = json.loads(state_tool.fn())
    assert payload == FakeTransactionLifecycleService().status_payload()
    annotations = infer_tool_annotations("pcb_get_live_edit_state")
    assert annotations.read_only_hint is True
    assert annotations.idempotent_hint is True
    assert getattr(annotations, "requiresKiCadRunning", None) is not True


def test_runtime_service_reset_is_observed_by_each_transaction_tool_call() -> None:
    """Project selection resets the singleton: adapters must not retain its old handle."""

    class NamedService(FakeTransactionLifecycleService):
        def __init__(self, label: str) -> None:
            self.label = label

        def begin(self) -> str:
            return f"begin:{self.label}"

        def push(self) -> str:
            return f"push:{self.label}"

        def drop(self) -> str:
            return f"drop:{self.label}"

        def revert(self) -> str:
            return f"revert:{self.label}"

        def status_payload(self) -> dict[str, object]:
            return {"server_generation": self.label}

    original = NamedService("before-project-selection")
    replacement = NamedService("after-project-selection")
    current = [original]
    server = FastMCP("project-reset-transaction-service-test")
    register(server, PcbTransactionLifecycleDependencies(get_service=lambda: current[0]))
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    assert tools["pcb_begin_commit"].fn() == "begin:before-project-selection"
    current[0] = replacement  # kicad_set_project triggers service singleton replacement
    assert tools["pcb_begin_commit"].fn() == "begin:after-project-selection"
    assert tools["pcb_push_commit"].fn() == "push:after-project-selection"
    assert tools["pcb_drop_commit"].fn() == "drop:after-project-selection"
    assert tools["pcb_revert"].fn() == "revert:after-project-selection"
    assert json.loads(tools["pcb_get_live_edit_state"].fn()) == {
        "server_generation": "after-project-selection"
    }
