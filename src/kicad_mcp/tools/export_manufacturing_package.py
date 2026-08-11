"""Thin FastMCP adapter for the gated manufacturing release package."""

# pyright: reportUnusedFunction=false

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from ..export.manufacturing_package import ExportManufacturingPackageService
from .metadata import headless_compatible


@dataclass(frozen=True)
class ExportManufacturingPackageDependencies:
    """Manufacturing package service and MCP progress bridge."""

    service: ExportManufacturingPackageService
    report_progress: Callable[[Context[Any, Any, Any] | None, float, float, str], Awaitable[None]]


def register(mcp: FastMCP, dependencies: ExportManufacturingPackageDependencies) -> None:
    """Register the gated manufacturing package export tool."""
    service = dependencies.service
    report_progress = dependencies.report_progress

    @mcp.tool()
    @headless_compatible
    async def export_manufacturing_package(
        variant: str = "",
        approval_evidence_path: str = "",
        ctx: Context[Any, Any, Any] | None = None,
    ) -> str:
        """Generate the gated manufacturing release package."""
        from .validation import _evaluate_project_gate, _render_project_gate_report

        async def progress(current: int, total: int, message: str) -> None:
            await report_progress(ctx, current, total, message)

        return await service.export(
            variant=variant,
            approval_evidence_path=approval_evidence_path,
            evaluate_project_gate=_evaluate_project_gate,
            render_gate_report=lambda outcomes, summary: _render_project_gate_report(
                outcomes,
                summary=summary,
            ),
            report_progress=progress,
        )
