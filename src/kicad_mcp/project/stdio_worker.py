"""Project-scoped MCP subprocesses for trusted local callers.

Each subprocess has its own KiCad configuration, IPC connection and tool
registry. Cloud IDs must be resolved to locally approved paths *before* using
this module. It does not expose a network endpoint or authorize remote calls.
"""

from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.types import CallToolResult

# Never inherit a dashboard/Cloud remote transport into a local worker.
_WORKER_SETTINGS = {
    "KICAD_MCP_TRANSPORT": "stdio",
    "KICAD_MCP_PROFILE": "review",
    "KICAD_MCP_OPERATING_MODE": "readonly",
    "KICAD_MCP_ENABLE_EXPERIMENTAL_TOOLS": "false",
}


def project_worker_parameters(project_directory: Path) -> StdioServerParameters:
    """Construct argv-based stdio transport for one trusted, existing project."""
    if not isinstance(project_directory, Path) or not project_directory.is_absolute():
        raise ValueError("Project worker requires a local absolute project directory.")
    resolved = project_directory.resolve(strict=True)
    if not resolved.is_dir():
        raise ValueError("Project worker requires an existing project directory.")
    env = os.environ.copy()
    env.update(_WORKER_SETTINGS)
    # Empty values for Path settings are interpreted as "." by Pydantic;
    # never create a repo-wide file watcher just to disable project switching.
    env.pop("KICAD_MCP_STUDIO_WATCH_DIR", None)
    env["KICAD_MCP_PROJECT_DIR"] = str(resolved)
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "kicad_mcp.server", "--transport", "stdio"],
        env=env,
    )


@asynccontextmanager
async def project_stdio_worker(
    project_directory: Path, *, timeout_seconds: float = 40
) -> AsyncIterator[ClientSession]:
    """Launch and close a project-specific MCP process without global switching."""
    params = project_worker_parameters(project_directory)
    async with (
        stdio_client(params) as streams,
        ClientSession(*streams) as session,
    ):
        # Timeout applies to initialization, not the engineering session.
        async with asyncio.timeout(timeout_seconds):
            await session.initialize()
        yield session


class ProjectWorkerDeniedError(ValueError):
    """A project or tool is not authorized for this local worker."""


# Explicitly approved local inspection tools; general remote MCP tool
# forwarding requires a separate, verified operation-level contract.
_SCOPED_INSPECTION_TOOLS = frozenset(
    {
        "kicad_get_version",
        "kicad_get_project_info",
        "kicad_get_server_info",
        "pcb_get_board_summary",
        "sch_get_population_status",
    }
)


class ProjectInspectionSession:
    """A single local project subprocess, with authorization rechecked per call."""

    def __init__(
        self,
        session: ClientSession,
        project_id: str,
        current_authorization: Callable[[str], bool],
        timeout_seconds: float = 12,
    ) -> None:
        if not isinstance(timeout_seconds, (int, float)) or not 0 < timeout_seconds <= 30:
            raise ValueError("Invalid project inspection timeout")
        self._timeout_seconds = timeout_seconds
        self._session = session
        self._project_id = project_id
        self._authorized = current_authorization

    def _check_grant(self) -> None:
        try:
            accepted = self._authorized(self._project_id)
        except Exception as exc:
            raise ProjectWorkerDeniedError("project not authorized") from exc
        if accepted is not True:
            raise ProjectWorkerDeniedError("project not authorized")

    async def inspect(self, name: str) -> CallToolResult:
        """Execute only an explicit read-only project inspection operation."""
        if name not in _SCOPED_INSPECTION_TOOLS:
            raise ProjectWorkerDeniedError("tool not authorized")
        self._check_grant()
        async with asyncio.timeout(self._timeout_seconds):
            response = await self._session.call_tool(name, arguments={})
        self._check_grant()
        return response


class LocalProjectWorkerRouter:
    """Map already locally approved opaque project IDs to independent processes.

    No Cloud-provided filesystem path is used here. The upstream connector
    must authenticate the client and provide current_authorization from its
    independently trusted grant/session state.
    """

    def __init__(
        self,
        approved_projects: Mapping[str, Path],
        *,
        current_authorization: Callable[[str], bool],
    ) -> None:
        if not callable(current_authorization):
            raise ValueError("Current project authorization is required.")
        # Fail at setup time, not halfway through the first tool call.
        self._projects: dict[str, Path] = {}
        for project_id, directory in approved_projects.items():
            project_worker_parameters(directory)
            self._projects[project_id] = directory.resolve(strict=True)
        self._authorized = current_authorization

    @asynccontextmanager
    async def connect(self, project_id: str) -> AsyncIterator[ProjectInspectionSession]:
        """Connect to a fresh project-local stdio engine, never a shared singleton."""
        if not isinstance(project_id, str):
            raise ProjectWorkerDeniedError("project not authorized")
        directory = self._projects.get(project_id)
        if directory is None:
            raise ProjectWorkerDeniedError("project not authorized")
        try:
            granted = self._authorized(project_id)
        except Exception as exc:
            raise ProjectWorkerDeniedError("project not authorized") from exc
        if granted is not True:
            raise ProjectWorkerDeniedError("project not authorized")
        async with project_stdio_worker(directory) as session:
            worker = ProjectInspectionSession(session, project_id, self._authorized)
            worker._check_grant()
            yield worker
