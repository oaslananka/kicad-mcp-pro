"""Failures reported by tools must be MCP errors, not successful no-ops.

Regression for lewisfab issue #1771.
"""

from __future__ import annotations

import pytest
from mcp.types import CallToolResult, TextContent

from kicad_mcp.server import _promote_failed_tool_result, _tool_failure_message


def test_missing_schematic_and_pcb_targets_are_errors() -> None:
    for tool, message in (
        ("sch_add_symbol", "Symbol 'Device:NoSuchPart' was not found in the library."),
        ("sch_delete_symbol", "Reference 'R999' was not found in the schematic."),
        ("pcb_move_footprint", "Footprint 'NOPE' was not found on the active board."),
        ("pcb_set_footprint_layer", "Footprint 'NOPE' was not found on the active board."),
    ):
        assert _tool_failure_message(tool, message) == message


def test_unavailable_net_class_mutation_is_an_error() -> None:
    for text in (
        "Net class assignment is experimental. Enable experimental tools to try it.",
        "Direct net class assignment is not exposed as a stable KiCad 10.x IPC operation.",
    ):
        assert _tool_failure_message("pcb_set_net_class", text) == text


def test_unrelated_messages_remain_non_errors() -> None:
    for text in (
        "No subcircuit templates are available.",
        "Sheet is already A3. No change made.",
        "The symbol was not found in this external index, but a fallback was used.",
    ):
        assert _tool_failure_message("sch_add_symbol", text) is None


def test_failed_structured_result_sets_is_error_and_keeps_content() -> None:
    original = CallToolResult(
        content=[TextContent(type="text", text='{"ok":false,"errors":["DSN missing"]}')],
        structuredContent={"result": {"ok": False, "errors": ["DSN missing"]}},
    )
    updated = _promote_failed_tool_result(original)
    assert isinstance(updated, CallToolResult)
    assert updated.is_error is True
    assert updated.structured_content == original.structured_content
    assert updated.content == original.content


def test_successful_and_already_failed_results_are_unchanged() -> None:
    ok = CallToolResult(
        content=[TextContent(type="text", text="Done")],
        structuredContent={"result": {"ok": True}},
    )
    error = CallToolResult(content=[TextContent(type="text", text="Error")], isError=True)
    assert _promote_failed_tool_result(ok) is ok
    assert _promote_failed_tool_result(error) is error


@pytest.mark.anyio
async def test_unknown_schematic_reference_is_mcp_error(sample_project) -> None:
    from kicad_mcp.config import get_config
    from kicad_mcp.server import build_server

    get_config().operating_mode = "write"
    server = build_server("schematic")
    result = await server.call_tool("sch_delete_symbol", {"reference": "R999"})
    assert isinstance(result, CallToolResult)
    assert result.is_error is True
    assert "R999" in result.content[0].text
