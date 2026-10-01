"""Error transient-class and tool idempotency contract (work order P1-T5, K9).

Agents need to know *why* an error is retryable and *whether* a tool is safe to retry.
These tests pin both halves of that contract.
"""

from __future__ import annotations

from kicad_mcp.errors import (
    KiCadBoardNotOpenError,
    KiCadConnectionTimeoutError,
    KiCadNotRunningError,
    ToolValidationError,
    error_payload,
)
from kicad_mcp.server import build_server
from kicad_mcp.tools.metadata import infer_tool_annotations, is_tool_idempotent

# --- error transient classification ----------------------------------------


def test_network_error_carries_backoff() -> None:
    payload = error_payload(KiCadNotRunningError("down"))
    assert payload["retryable"] is True
    assert payload["transient_class"] == "network"
    assert payload["retry_after_ms"] == 1000


def test_timeout_error_class() -> None:
    payload = KiCadConnectionTimeoutError("slow").to_payload()
    assert payload["transient_class"] == "timeout"
    assert payload["retry_after_ms"] == 2000


def test_board_not_open_is_state_reconcile_first() -> None:
    payload = KiCadBoardNotOpenError("no board").to_payload()
    assert payload["retryable"] is True
    assert payload["transient_class"] == "state"
    assert payload["retry_after_ms"] is None


def test_non_retryable_error_is_not_transient() -> None:
    payload = ToolValidationError("bad arg").to_payload()
    assert payload["retryable"] is False
    assert payload["transient_class"] == "none"


def test_internal_error_fallback_has_transient_fields() -> None:
    payload = error_payload(RuntimeError("boom"))
    assert payload["transient_class"] == "none"
    assert payload["retry_after_ms"] is None


# --- tool idempotency classification ---------------------------------------


def test_read_only_tools_are_idempotent() -> None:
    for name in (
        "pcb_get_board_summary",
        "sch_get_symbols",
        "run_drc",
        "lib_search_symbols",
        "schematic_quality_gate",
    ):
        assert is_tool_idempotent(name), name


def test_additive_writes_are_not_idempotent() -> None:
    for name in (
        "pcb_add_track",
        "pcb_add_via",
        "sch_add_symbol",
        "pcb_place_component",
        "route_single_track",
    ):
        assert not is_tool_idempotent(name), name


def test_converging_writes_are_idempotent() -> None:
    for name in (
        "pcb_set_stackup",
        "pcb_save",
        "pcb_refill_zones",
        "export_gerber",
        "fp_upgrade",
        "erc_reset_rules",
    ):
        assert is_tool_idempotent(name), name


def test_every_registered_tool_has_idempotency_annotation() -> None:
    server = build_server("agent_full")
    server.ensure_registered()
    for tool in server._tool_manager.list_tools():
        annotations = infer_tool_annotations(tool.name)
        assert annotations.idempotent_hint is not None, (
            f"{tool.name} lacks an idempotency annotation"
        )
