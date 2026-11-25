"""Outside-in MCP save-path acceptance for the opt-in physical state."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from kicad_mcp.config import get_config
from kicad_mcp.ir import IRCircuit
from kicad_mcp.pcb.live_edit_runtime import reset_live_edit_service
from kicad_mcp.project.incremental_state import (
    NativeHierarchySnapshot,
    source_digests,
)
from kicad_mcp.server import build_server
from tests.conftest import call_tool_text

STAMP = "10000000-0000-4000-8000-000000000001"
PROJECT = "10000000-0000-4000-8000-000000000002"
SOURCES = ("demo.kicad_pcb", "demo.kicad_pro", "demo.kicad_sch")


def _board(x: int) -> str:
    return (
        "(kicad_pcb (version 20241229) "
        f'(footprint "Test:R" (uuid "{STAMP}") (layer "F.Cu") '
        f'(at {x} 20) (property "Reference" "R1") (property "Value" "10k")))'
    )


@pytest.fixture
def saved_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mock_board: MagicMock
) -> Iterator[tuple[SimpleNamespace, Path]]:
    reset_live_edit_service()
    cfg = get_config()
    cfg.project_dir = tmp_path
    cfg.project_file = tmp_path / "demo.kicad_pro"
    cfg.pcb_file = tmp_path / "demo.kicad_pcb"
    cfg.sch_file = tmp_path / "demo.kicad_sch"
    cfg.workspace_root = tmp_path
    cfg.transport = "stdio"
    cfg.kicad_socket_path = None
    cfg.enable_persistent_pcb_state = True
    cfg.project_file.write_text("{}")
    cfg.sch_file.write_text("(kicad_sch (version 20250114))")
    cfg.pcb_file.write_text(_board(10))
    mock_board.name = "demo.kicad_pcb"
    mock_board.get_project.return_value = SimpleNamespace(path=str(cfg.project_file), name="demo")
    live = SimpleNamespace(x=10)

    def native_save():
        cfg.pcb_file.write_text(_board(live.x))

    mock_board.save.side_effect = native_save
    mock_board.get_footprints.side_effect = lambda: [
        SimpleNamespace(
            id=SimpleNamespace(value=STAMP),
            position=SimpleNamespace(x=live.x * 1_000_000, y=20_000_000),
        )
    ]

    def capture(root, root_name, sources, *, run_cli):
        return NativeHierarchySnapshot(
            root,
            tuple(source_digests(root, sources).items()),
            IRCircuit(source_uuid=PROJECT, source_path=root_name, title="demo"),
        )

    # The CLI seam stands in for native hierarchy export, not the PCB file reader.
    monkeypatch.setattr("kicad_mcp.tools.pcb._run_cli", lambda *args, **kw: (0, "10.0.8", ""))
    monkeypatch.setattr("kicad_mcp.project.incremental_state.capture_native_hierarchy", capture)
    try:
        yield live, tmp_path / ".kicad-mcp-cache/physical.json"
    finally:
        reset_live_edit_service()


@pytest.mark.anyio
@pytest.mark.mcp_mode("write")
async def test_explicit_save_builds_then_updates_persistent_state(
    saved_project: tuple[SimpleNamespace, Path], mock_board: MagicMock
) -> None:
    live, path = saved_project
    server = build_server("full")
    assert not path.exists()
    result = await call_tool_text(server, "pcb_save", {})
    assert "Board saved." in result
    assert "rebuilt" in result
    before = json.loads(path.read_text())
    assert before["generation"] == 0
    live.x = 11
    assert json.loads(path.read_text()) == before
    result = await call_tool_text(server, "pcb_save", {})
    assert "Board saved." in result
    assert "1 updated" in result
    after = json.loads(path.read_text())
    assert after["generation"] == 1
    assert after["journal"][0]["work_units"] == 1
    assert mock_board.save.call_count == 2


@pytest.mark.anyio
@pytest.mark.mcp_mode("write")
async def test_disabled_save_never_creates_cache(
    saved_project: tuple[SimpleNamespace, Path], mock_board: MagicMock
) -> None:
    _, path = saved_project
    get_config().enable_persistent_pcb_state = False
    result = await call_tool_text(build_server("full"), "pcb_save", {})
    assert result == "Board saved."
    assert not path.exists()
    mock_board.save.assert_called_once()


@pytest.mark.anyio
@pytest.mark.mcp_mode("write")
async def test_save_reopens_verified_state_after_server_restart(
    saved_project: tuple[SimpleNamespace, Path], mock_board: MagicMock
) -> None:
    live, path = saved_project
    server = build_server("full")
    assert "rebuilt" in await call_tool_text(server, "pcb_save", {})
    live.x = 11
    assert "1 updated" in await call_tool_text(server, "pcb_save", {})
    before = json.loads(path.read_text())
    assert "reopened" in await call_tool_text(build_server("full"), "pcb_save", {})
    assert json.loads(path.read_text()) == before
    assert mock_board.save.call_count == 3


@pytest.mark.anyio
@pytest.mark.mcp_mode("write")
async def test_external_edit_rebuilds_instead_of_reusing_stale_state(
    saved_project: tuple[SimpleNamespace, Path],
) -> None:
    live, path = saved_project
    server = build_server("full")
    assert "rebuilt" in await call_tool_text(server, "pcb_save", {})
    cfg = get_config()
    cfg.pcb_file.write_text(_board(12))
    live.x = 13
    assert "rebuilt" in await call_tool_text(server, "pcb_save", {})
    assert json.loads(path.read_text())["generation"] == 0


@pytest.mark.anyio
@pytest.mark.mcp_mode("write")
async def test_save_cache_failure_does_not_retry_native_save(
    saved_project: tuple[SimpleNamespace, Path],
    mock_board: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    live, path = saved_project
    server = build_server("full")
    assert "rebuilt" in await call_tool_text(server, "pcb_save", {})
    before = path.read_bytes()
    live.x = 11

    def fail(*args: object, **kwargs: object) -> None:
        raise PermissionError("read-only cache")

    monkeypatch.setattr(
        "kicad_mcp.project.incremental_state.PersistentProjectState.save_atomic", fail
    )
    result = await call_tool_text(server, "pcb_save", {})
    assert "Board saved." in result
    assert "unavailable" in result
    assert mock_board.save.call_count == 2
    assert path.read_bytes() == before
    assert get_config().pcb_file.read_text() == _board(11)


@pytest.mark.anyio
@pytest.mark.mcp_mode("write")
async def test_cache_write_failure_rebuilds_on_next_explicit_save(
    saved_project: tuple[SimpleNamespace, Path],
    mock_board: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    live, path = saved_project
    server = build_server("full")
    assert "rebuilt" in await call_tool_text(server, "pcb_save", {})
    original = path.read_bytes()
    live.x = 11
    with monkeypatch.context() as patch:
        patch.setattr(
            "kicad_mcp.project.incremental_state.PersistentProjectState.save_atomic",
            MagicMock(side_effect=OSError("interrupted sidecar write")),
        )
        assert "rebuild required" in await call_tool_text(server, "pcb_save", {})
    assert path.read_bytes() == original
    assert mock_board.save.call_count == 2
    assert "rebuilt" in await call_tool_text(server, "pcb_save", {})
    assert json.loads(path.read_text())["generation"] == 0
    assert "reopened" in await call_tool_text(build_server("full"), "pcb_save", {})
    live.x = 12
    assert "1 updated" in await call_tool_text(server, "pcb_save", {})
    assert mock_board.save.call_count == 5


@pytest.mark.anyio
@pytest.mark.mcp_mode("write")
async def test_saved_graph_switches_between_projects_without_reusing_prior_state(
    saved_project: tuple[SimpleNamespace, Path],
    mock_board: MagicMock,
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    live, first_cache = saved_project
    cfg = get_config()
    server = build_server("full")
    assert "rebuilt" in await call_tool_text(server, "pcb_save", {})
    live.x = 11
    assert "1 updated" in await call_tool_text(server, "pcb_save", {})
    first_bytes = first_cache.read_bytes()
    first_board = cfg.pcb_file
    assert first_board is not None
    second = tmp_path_factory.mktemp("physical-project")
    with monkeypatch.context() as patch:
        patch.setattr(cfg, "project_dir", second)
        patch.setattr(cfg, "workspace_root", second)
        for attr, suffix in (("project_file", "pro"), ("pcb_file", "pcb"), ("sch_file", "sch")):
            source = getattr(cfg, attr)
            destination = second / f"demo.kicad_{suffix}"
            destination.write_bytes(source.read_bytes())
            patch.setattr(cfg, attr, destination)
        patch.setattr(mock_board.get_project.return_value, "path", str(cfg.project_file))
        live.x = 42
        assert "rebuilt" in await call_tool_text(server, "pcb_save", {})
        second_cache = second / ".kicad-mcp-cache/physical.json"
        assert json.loads(second_cache.read_text())["generation"] == 0
        assert first_cache.read_bytes() == first_bytes
        assert first_board.read_text() == _board(11)
    live.x = 11
    assert "reopened" in await call_tool_text(server, "pcb_save", {})
    assert first_cache.read_bytes() == first_bytes
    assert (second / "demo.kicad_pcb").read_text() == _board(42)


@pytest.mark.anyio
@pytest.mark.mcp_mode("write")
async def test_failed_native_save_never_publishes_sidecar(
    saved_project: tuple[SimpleNamespace, Path], mock_board: MagicMock
) -> None:
    _, path = saved_project
    mock_board.save.side_effect = TimeoutError("native save response lost")
    result = await call_tool_text(build_server("full"), "pcb_save", {})
    assert "Board saved." not in result
    assert not path.exists()
    mock_board.save.assert_called_once()


@pytest.mark.anyio
@pytest.mark.mcp_mode("write")
@pytest.mark.parametrize("mismatch", ["board", "project", "remote", "transport"])
async def test_save_refuses_cache_for_wrong_scope(
    saved_project: tuple[SimpleNamespace, Path], mock_board: MagicMock, mismatch: str
) -> None:
    _, path = saved_project
    cfg = get_config()
    if mismatch == "board":
        mock_board.name = "other.kicad_pcb"
    elif mismatch == "project":
        mock_board.get_project.return_value.path = str(cfg.project_dir.parent / "other.kicad_pro")
    elif mismatch == "remote":
        cfg.kicad_socket_path = "tcp://127.0.0.1:12345"
    else:
        cfg.transport = "streamable-http"
    result = await call_tool_text(build_server("full"), "pcb_save", {})
    assert "Board saved." in result
    assert "unavailable" in result
    assert not path.exists()
    mock_board.save.assert_called_once()


@pytest.mark.anyio
@pytest.mark.mcp_mode("readonly")
async def test_readonly_never_executes_save(
    saved_project: tuple[SimpleNamespace, Path], mock_board: MagicMock
) -> None:
    _, path = saved_project
    result = await call_tool_text(build_server("full"), "pcb_save", {})
    assert "Board saved." not in result
    assert not path.exists()
    mock_board.save.assert_not_called()


@pytest.mark.anyio
@pytest.mark.mcp_mode("write")
async def test_active_transaction_blocks_save_before_cache_work(
    saved_project: tuple[SimpleNamespace, Path], mock_board: MagicMock
) -> None:
    _, path = saved_project
    server = build_server("full")
    result = await call_tool_text(server, "pcb_begin_commit", {})
    assert "Transaction group started" in result
    result = await call_tool_text(server, "pcb_save", {})
    assert "does not participate" in result
    assert not path.exists()
    mock_board.save.assert_not_called()
