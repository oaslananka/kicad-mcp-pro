"""Thin FastMCP adapter for FreeRouting autorouter orchestration."""

# pyright: reportUnusedFunction=false

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from mcp.server.mcpserver import Context
from mcp.server.mcpserver import MCPServer as FastMCP

from ..config import get_config
from ..models.tool_result import ToolResult
from ..routing.autorouter import RoutingAutorouterService
from ..routing.specctra_staging import relative_project_path
from ..utils.freerouting import FreeRoutingRunner
from .export_support import _get_pcb_file
from .metadata import headless_compatible, requires_dependency
from .pcb import _transactional_board_write
from .progress import _report_progress


@dataclass(frozen=True)
class RoutingAutorouterDependencies:
    service: RoutingAutorouterService


def _default_dependencies() -> RoutingAutorouterDependencies:
    return RoutingAutorouterDependencies(
        service=RoutingAutorouterService(
            runner_factory=FreeRoutingRunner,
            get_pcb_file=_get_pcb_file,
            resolve_within_project=lambda path: get_config().resolve_within_project(path),
            relative_project_path=lambda path: relative_project_path(
                path,
                get_config().project_root,
            ),
            transactional_board_write=_transactional_board_write,
        )
    )


def register(
    mcp: FastMCP,
    dependencies: RoutingAutorouterDependencies | None = None,
) -> None:
    """Register the FreeRouting autorouter tool."""
    deps = dependencies or _default_dependencies()

    @mcp.tool()
    @headless_compatible
    @requires_dependency("freerouting")
    async def route_autoroute_freerouting(
        dsn_path: str = "output/routing/board.dsn",
        ses_path: str = "output/routing/board.ses",
        net_classes_to_ignore: list[str] | None = None,
        exclude_nets: list[str] | None = None,
        max_passes: int = 100,
        thread_count: int = 4,
        use_docker: bool = True,
        freerouting_jar_path: str | None = None,
        drc_report_path: str = "output/routing/freerouting.drc.json",
        ctx: Context[Any, Any] | None = None,
    ) -> ToolResult:
        """Run FreeRouting after placement, then surface the KiCad import step.

        DSN export is attempted headlessly; FreeRouting runs via Docker or a local JAR.
        Applying the routed SES session back to the board has no headless path in KiCad,
        so this returns a human-gated result (``human_gate_required=True``) describing the
        File > Import > Specctra Session step \u2014 it does not claim the board is routed when
        the session has only been staged. If headless DSN export is unavailable, the
        manual export step is surfaced instead of failing opaquely.

        When the experimental MCP Tasks extension is enabled
        (``KICAD_MCP_ENABLE_TASKS=1``), the routing runs in the background and a
        task reference is returned immediately. The caller can poll ``tasks/get``
        for completion and ``tasks/cancel`` to abort routing.
        """
        return await deps.service.autoroute(
            dsn_path=dsn_path,
            ses_path=ses_path,
            net_classes_to_ignore=net_classes_to_ignore,
            exclude_nets=exclude_nets,
            max_passes=max_passes,
            thread_count=thread_count,
            use_docker=use_docker,
            freerouting_jar_path=freerouting_jar_path,
            drc_report_path=drc_report_path,
            report_progress=lambda progress, total, message: _report_progress(
                ctx,
                progress,
                total,
                message,
            ),
        )
