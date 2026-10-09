"""Shared optional FastMCP progress signaling for headless tool adapters."""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import Context


async def _report_progress(
    ctx: Context[Any, Any] | None,
    progress: float,
    total: float,
    message: str,
) -> None:
    if ctx is None:
        return
    try:
        await ctx.report_progress(progress, total, message)
    except ValueError:
        return
