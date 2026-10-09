"""Cross-adapter alias stability for pure helper deduplication."""

from __future__ import annotations

from typing import Any, cast

import pytest
from mcp.server.mcpserver import Context

from kicad_mcp.tools import (
    export,
    pcb,
    progress,
    routing_autorouter,
    schematic_transfer,
    simulation,
)


def test_netlist_parser_keeps_one_canonical_function() -> None:
    assert pcb._parse_netlist_text is schematic_transfer._parse_netlist_text


def test_progress_function_is_shared_by_all_three_tools() -> None:
    assert export._report_progress is progress._report_progress
    assert simulation._report_progress is progress._report_progress
    assert routing_autorouter._report_progress is progress._report_progress


@pytest.mark.anyio
async def test_progress_preserves_optional_and_unsupported_behavior() -> None:
    messages: list[tuple[float, float, str]] = []

    class FakeContext:
        async def report_progress(self, current: float, total: float, message: str) -> None:
            messages.append((current, total, message))

    await progress._report_progress(None, 1, 3, "ignored")
    await progress._report_progress(cast(Context[Any, Any], FakeContext()), 1, 3, "hello")
    assert messages == [(1, 3, "hello")]

    class NoProgressContext:
        async def report_progress(self, *_args: object) -> None:
            raise ValueError("notifications unavailable")

    await progress._report_progress(cast(Context[Any, Any], NoProgressContext()), 1, 3, "ok")
