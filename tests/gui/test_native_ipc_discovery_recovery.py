"""Opt-in Windows native discovery and transaction recovery on a private PCB."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from kipy import KiCad
from kipy.board import Board
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from kicad_mcp.config import get_config, reset_config
from kicad_mcp.connection import get_board, reset_connection
from kicad_mcp.pcb.live_edit_runtime import reset_live_edit_service
from kicad_mcp.server import IPC_CAPABILITY_CACHE_TTL_SEC
from tests.conftest import tool_text
from tests.integration.test_mcp_native_v2_protocol import (
    _configure_native_v2_server,
    _running_http_server,
)

FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "packages/kicad-fixtures/fixtures/empty-board/empty-board.kicad_pcb"
)
OPT_IN = "KICAD_NATIVE_WINDOWS_IPC_GUI_BIN"
pytestmark = [
    pytest.mark.gui,
    pytest.mark.slow,
    pytest.mark.skipif(
        sys.platform != "win32" or not os.environ.get(OPT_IN),
        reason=f"Set {OPT_IN} to the installed KiCad 10.0 bin directory on Windows",
    ),
]


@contextmanager
def _private_editor(
    executable: Path, board: Path, env: dict[str, str], endpoint: str
) -> Iterator[None]:
    """Launch and stop only an owned editor with a verified private project."""
    with subprocess.Popen(  # nosec B603
        [str(executable), str(board)],
        cwd=board.parent,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    ) as process:
        try:
            for _ in range(20):
                assert process.poll() is None, "Private PCB Editor exited"
                try:
                    client = KiCad(socket_path=endpoint, timeout_ms=1000)
                    version = client.get_version()
                    native = client.get_board()
                except Exception:
                    time.sleep(1)
                    continue
                assert str(version).startswith("10.")
                identity = native.get_project()
                assert Path(identity.path).resolve() == board.parent.resolve()
                assert identity.name == board.stem
                assert native.name == board.name
                break
            else:
                pytest.fail("Private PCB Editor IPC did not become ready")
            yield
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)


def _configure_private_project(
    scratch: Path, bin_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, dict[str, str], str]:
    profile = scratch / "config/10.0"
    profile.mkdir(parents=True)
    (scratch / "tmp").mkdir()
    (scratch / "docs").mkdir()
    (profile / "kicad_common.json").write_text(
        json.dumps(
            {
                "api": {"enable_server": True},
                "graphics": {"canvas_type": 2},
                "do_not_show_again": {
                    "update_check_prompt": True,
                    "data_collection_prompt": True,
                },
            }
        ),
        encoding="utf-8",
    )
    share = bin_dir.parent / "share/kicad"
    for name in ("sym-lib-table", "fp-lib-table"):
        shutil.copyfile(share / "template" / name, profile / name)
    (profile / "design-block-lib-table").write_text(
        "(design_block_lib_table (version 7))\n", encoding="utf-8"
    )
    project = scratch / "project"
    project.mkdir()
    board = project / "probe.kicad_pcb"
    shutil.copyfile(FIXTURE, board)
    (project / "probe.kicad_pro").write_text("{}\n", encoding="utf-8")
    # Never inherit the caller's project selection, IPC token or remote auth.
    for key in tuple(os.environ):
        if key.startswith(("KICAD_MCP_", "KICAD_API_")):
            monkeypatch.delenv(key)
    editor_env = os.environ.copy()
    editor_env.update(
        KICAD_CONFIG_HOME=str(scratch / "config"),
        KICAD_DOCUMENTS_HOME=str(scratch / "docs"),
        TEMP=str(scratch / "tmp"),
        TMP=str(scratch / "tmp"),
        KICAD10_TEMPLATE_DIR=str(share / "template"),
        KICAD10_SYMBOL_DIR=str(share / "symbols"),
        KICAD10_FOOTPRINT_DIR=str(share / "footprints"),
    )
    endpoint = "ipc://" + str(scratch / "tmp/kicad/api.sock")
    for key in ("KICAD_CONFIG_HOME", "KICAD_DOCUMENTS_HOME"):
        monkeypatch.setenv(key, editor_env[key])
    for key, value in {
        "KICAD_API_SOCKET": endpoint,
        "KICAD_MCP_KICAD_SOCKET_PATH": endpoint,
        "KICAD_MCP_KICAD_CLI": str(bin_dir / "kicad-cli.exe"),
        "KICAD_MCP_PROJECT_DIR": str(project),
        "KICAD_MCP_WORKSPACE_ROOT": str(project),
        "KICAD_MCP_OPERATING_MODE": "write",
        "KICAD_MCP_FILTER_RUNTIME_TOOLS": "true",
        "KICAD_MCP_TELEMETRY_ENABLED": "false",
    }.items():
        monkeypatch.setenv(key, value)
    reset_config()
    reset_connection()
    reset_live_edit_service()
    cfg = get_config()
    cfg.ipc_connection_timeout = 0.5
    cfg.ipc_retries = 1
    cfg.ipc_cache_ttl = 0.5
    return board, editor_env, endpoint


async def _exercise_native_session(
    board: Path, editor: Path, env: dict[str, str], endpoint: str
) -> None:
    server = _configure_native_v2_server(board.parent, profile="pcb_only")
    track = {"x1_mm": 20, "y1_mm": 20, "x2_mm": 25, "y2_mm": 20, "layer": "F_Cu"}

    async def settle() -> None:
        await asyncio.sleep(IPC_CAPABILITY_CACHE_TTL_SEC + 0.2)

    with _running_http_server(server.streamable_http_app()) as url:
        async with streamable_http_client(url + "/mcp") as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize()

                async def catalog() -> dict[str, object]:
                    tools = (await session.list_tools()).tools
                    assert len(tools) == len({tool.name for tool in tools})
                    return {tool.name: tool.model_dump(by_alias=True) for tool in tools}

                async def state() -> dict[str, object]:
                    result = await session.call_tool("pcb_get_live_edit_state", {})
                    assert not result.is_error
                    return json.loads(tool_text(result))

                async def successful_call(name: str, args: dict[str, object] | None = None) -> str:
                    result = await session.call_tool(name, args or {})
                    assert not result.is_error, tool_text(result)
                    return tool_text(result)

                def verified_board() -> Board:
                    native = get_board()
                    identity = native.get_project()
                    assert Path(identity.path).resolve() == board.parent.resolve()
                    assert identity.name == board.stem
                    assert native.name == board.name
                    return native

                offline = await catalog()
                assert "pcb_begin_commit" not in offline
                assert (await state())["transaction_support_status"] == "unknown"
                assert (await session.call_tool("pcb_begin_commit", {})).is_error
                with _private_editor(editor, board, env, endpoint):
                    await settle()
                    online = await catalog()
                    assert "pcb_begin_commit" in online and "pcb_add_track" in online
                    assert set(offline) < set(online)
                    assert all(online[name] == value for name, value in offline.items())
                    live = verified_board()
                    before = live.get_as_string()
                    assert (await state())["transaction_support_status"] == "unknown"
                    assert "Transaction group started" in await successful_call("pcb_begin_commit")
                    assert (await state())["transaction_support_status"] == "supported"
                    assert "staged" in await successful_call("pcb_add_track", track)
                    assert "discarded" in await successful_call("pcb_drop_commit")
                    assert live.get_as_string() == before and len(live.get_tracks()) == 0
                    await successful_call("pcb_begin_commit")
                    await successful_call("pcb_add_track", track)
                    assert "committed successfully" in await successful_call("pcb_push_commit")
                    assert len(live.get_tracks()) == 1
                    live.save()
                    saved = board.read_bytes()
                await settle()
                assert await catalog() == offline
                assert (await state())["transaction_support_status"] == "unknown"
                assert (await session.call_tool("pcb_begin_commit", {})).is_error
                with _private_editor(editor, board, env, endpoint):
                    await settle()
                    assert await catalog() == online
                    assert len(verified_board().get_tracks()) == 1
                    assert (await state())["transaction_support_status"] == "unknown"
                    await successful_call("pcb_begin_commit")
                    assert (await state())["transaction_support_status"] == "supported"
                    second = dict(track, y1_mm=30, y2_mm=30)
                    await successful_call("pcb_add_track", second)
                    assert (await state())["staged_mutation_count"] == 1
                await settle()
                assert await catalog() == offline
                lost = await state()
                assert lost["state"] == "recovery_required"
                assert lost["transaction_support_status"] == "unknown"
                assert lost["recovery_required"] is True
                with _private_editor(editor, board, env, endpoint):
                    await settle()
                    assert await catalog() == online
                    live = verified_board()
                    for name in ("pcb_begin_commit", "pcb_push_commit", "pcb_drop_commit"):
                        refused = await session.call_tool(name, {})
                        assert "reconcile the active KiCad board" in tool_text(refused)
                    denied = await session.call_tool("pcb_add_track", second)
                    assert denied.is_error and "recovery" in tool_text(denied)
                    assert len(live.get_tracks()) == 1
                    assert board.read_bytes() == saved


def test_native_windows_discovery_and_transaction_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Explicitly opt in; no default socket, real project, or shared editor is used."""
    bin_dir = Path(os.environ[OPT_IN]).resolve(strict=True)
    editor = bin_dir / "pcbnew.exe"
    assert editor.is_file() and (bin_dir / "kicad-cli.exe").is_file()
    original = FIXTURE.read_bytes()
    with tempfile.TemporaryDirectory(prefix="kicad-ipc-") as temp:
        try:
            board, env, endpoint = _configure_private_project(Path(temp), bin_dir, monkeypatch)
            asyncio.run(_exercise_native_session(board, editor, env, endpoint))
        finally:
            reset_live_edit_service()
            reset_connection()
            reset_config()
    assert FIXTURE.read_bytes() == original
