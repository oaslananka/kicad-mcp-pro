"""Fail-closed coverage for the superseded MCP Tasks draft on SDK v2."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from kicad_mcp.config import KiCadMCPConfig
from kicad_mcp.server import build_server


def test_legacy_tasks_flag_is_rejected_on_sdk_v2() -> None:
    with pytest.raises(
        ValidationError,
        match="Legacy MCP Tasks are unavailable on MCP Python SDK v2",
    ):
        KiCadMCPConfig(enable_tasks=True)


def test_sdk_v2_server_does_not_expose_legacy_experimental_task_runtime(
    sample_project,
) -> None:
    _ = sample_project
    server = build_server("minimal")

    assert not hasattr(server._mcp_server, "experimental")
    assert not hasattr(server, "_task_manager")
