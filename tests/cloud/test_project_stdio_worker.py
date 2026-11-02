"""Real stdio-process boundaries without remote Cloud access or board mutation."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from kicad_mcp.project.stdio_worker import (
    LocalProjectWorkerRouter,
    ProjectWorkerDeniedError,
    project_stdio_worker,
    project_worker_parameters,
)


def test_worker_uses_scoped_project_and_forces_readonly_stdio(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    project = tmp_path / "Board A"
    project.mkdir()
    monkeypatch.setenv("KICAD_MCP_TRANSPORT", "streamable-http")
    monkeypatch.setenv("KICAD_MCP_OPERATING_MODE", "experimental")
    monkeypatch.setenv("KICAD_MCP_PROJECT_DIR", str(tmp_path / "wrong"))
    monkeypatch.setenv("KICAD_MCP_STUDIO_WATCH_DIR", str(tmp_path))
    params = project_worker_parameters(project)
    assert params.command == os.sys.executable
    assert params.env is not None
    assert params.env["KICAD_MCP_PROJECT_DIR"] == str(project)
    assert params.env["KICAD_MCP_TRANSPORT"] == "stdio"
    assert params.env["KICAD_MCP_OPERATING_MODE"] == "readonly"
    assert params.env["KICAD_MCP_PROFILE"] == "review"
    assert "KICAD_MCP_STUDIO_WATCH_DIR" not in params.env
    assert "--project-dir" not in params.args
    with pytest.raises(FileNotFoundError):
        project_worker_parameters(tmp_path / "missing")


@pytest.mark.anyio
async def test_independent_projects_have_independent_mcp_processes(
    tmp_path: Path,
) -> None:
    projects = [tmp_path / "alpha", tmp_path / "beta"]
    for root in projects:
        root.mkdir()
        (root / f"{root.name}.kicad_pro").write_text("{}", encoding="utf-8")

    async def inspect(root: Path) -> tuple[str, str]:
        async with project_stdio_worker(root) as client:
            result = await client.call_tool("kicad_get_project_info", {})
            return str(root), str(result)

    first, second = await asyncio.gather(*(inspect(root) for root in projects))
    assert str(projects[0]) in first[1]
    assert str(projects[1]) in second[1]
    assert str(projects[1]) not in first[1]
    assert str(projects[0]) not in second[1]


@pytest.mark.anyio
async def test_router_isolates_two_granted_projects_and_denies_foreign_tools(
    tmp_path: Path,
) -> None:
    projects = {"project-alpha": tmp_path / "alpha", "project-beta": tmp_path / "beta"}
    for root in projects.values():
        root.mkdir()
        (root / f"{root.name}.kicad_pro").write_text("{}", encoding="utf-8")
    grants = {project_id: True for project_id in projects}
    router = LocalProjectWorkerRouter(
        projects, current_authorization=lambda project_id: grants[project_id]
    )

    async def inspect(project_id: str) -> str:
        async with router.connect(project_id) as worker:
            with pytest.raises(ProjectWorkerDeniedError):
                await worker.inspect("kicad_set_project")
            result = await worker.inspect("kicad_get_project_info")
            assert result.is_error is not True
            return str(result)

    first, second = await asyncio.gather(inspect("project-alpha"), inspect("project-beta"))
    assert str(projects["project-alpha"]) in first
    assert str(projects["project-beta"]) in second
    assert str(projects["project-alpha"]) not in second
    assert str(projects["project-beta"]) not in first
    with pytest.raises(ProjectWorkerDeniedError):
        async with router.connect("unregistered"):
            pass


@pytest.mark.anyio
async def test_router_rechecks_revoked_project_grant(tmp_path: Path) -> None:
    project = tmp_path / "approved"
    project.mkdir()
    (project / "approved.kicad_pro").write_text("{}", encoding="utf-8")
    granted = True
    router = LocalProjectWorkerRouter(
        {"approved": project}, current_authorization=lambda _project: granted
    )
    async with router.connect("approved") as worker:
        assert (await worker.inspect("kicad_get_version")).is_error is not True
        granted = False
        with pytest.raises(ProjectWorkerDeniedError):
            await worker.inspect("kicad_get_project_info")
    with pytest.raises(ProjectWorkerDeniedError):
        async with router.connect("approved"):
            pass


@pytest.mark.anyio
async def test_project_inspection_denies_result_if_grant_revoked_in_flight() -> None:
    """A read started while approved cannot deliver after permission revocation."""
    from kicad_mcp.project.stdio_worker import ProjectInspectionSession

    approved = True

    class RevokingSession:
        async def call_tool(self, name: str, arguments: dict[str, object]) -> object:
            nonlocal approved
            approved = False
            return object()

    worker = ProjectInspectionSession(  # type: ignore[arg-type]  # Minimal session fixture.
        RevokingSession(), "board-a", lambda _project_id: approved
    )
    with pytest.raises(ProjectWorkerDeniedError):
        await worker.inspect("kicad_get_version")


def test_project_worker_refuses_untrusted_paths(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        project_worker_parameters(Path("relative-project"))
    with pytest.raises(FileNotFoundError):
        project_worker_parameters(tmp_path / "missing")
    filename = tmp_path / "not-a-directory"
    filename.write_text("not a project", encoding="utf-8")
    with pytest.raises(ValueError):
        project_worker_parameters(filename)


@pytest.mark.anyio
async def test_inspection_timeout_cancels_stalled_tool_call() -> None:
    """Slow or orphaned workers cannot occupy a request forever."""
    from kicad_mcp.project.stdio_worker import ProjectInspectionSession

    cancelled = False

    class UnresponsiveSession:
        async def call_tool(self, name: str, arguments: dict[str, object]) -> object:
            nonlocal cancelled
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled = True
                raise

    worker = ProjectInspectionSession(  # type: ignore[arg-type]
        UnresponsiveSession(), "project-a", lambda _project: True, timeout_seconds=0.02
    )
    with pytest.raises(TimeoutError):
        await worker.inspect("kicad_get_version")
    assert cancelled


def test_inspection_timeout_rejects_invalid_limits() -> None:
    from kicad_mcp.project.stdio_worker import ProjectInspectionSession

    for value in (0, -5, 31, float("inf"), float("nan")):
        with pytest.raises(ValueError):
            ProjectInspectionSession(  # type: ignore[arg-type]
                object(), "a", lambda _: True, timeout_seconds=value
            )
