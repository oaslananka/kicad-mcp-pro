"""Opt-in real KiCad GUI acceptance for the *local*, scoped Cloud worker bridge.

This does NOT exercise a production Cloud transport or grant remote authority.
Only disposable repository fixtures are used; raw PCB data and private paths
must never be serialized into a bounded project-board-counts result.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from kicad_mcp.cloud_outbound_handshake import (
    CloudHandshakeDeniedError,
    HandshakeReceipt,
    _complete_authorized_inspection,
)
from kicad_mcp.connection import reset_connection
from kicad_mcp.project.stdio_worker import ProjectWorkerDeniedError
from kicad_mcp.server import build_server
from tests.cloud.test_cloud_worker_inspection_transport import (
    DEVICE,
    PROJECT,
    SESSION,
    RecordingSocket,
    bound_worker,
    frame,
)
from tests.conftest import call_tool_text
from tests.gui.test_kicad_gui_live_context import (
    _configure_project,
    _copy_fixture,
    _discover_executables,
    _launch_process,
    _stop_process,
    _wait_for_live_context,
)

pytestmark = [pytest.mark.anyio, pytest.mark.gui, pytest.mark.slow]
BOARD_COUNTS_OPERATION = "project_board_counts"


async def test_scoped_cloud_board_counts_use_live_kicad_gui_without_leaking_design(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify a project-bound worker's *local* native GUI read and result scrub."""
    if os.environ.get("KICAD_MCP_ENABLE_CLOUD_WORKER_GUI") != "1":
        pytest.skip(
            "Set KICAD_MCP_ENABLE_CLOUD_WORKER_GUI=1 for real local Cloud worker GUI acceptance"
        )
    executables = _discover_executables()
    if executables.pcb_editor is None:
        pytest.fail("KiCad PCB Editor unavailable for explicitly enabled Cloud bridge GUI test")

    project = _copy_fixture(tmp_path, "cloud-bridge-disposable")
    env = _configure_project(monkeypatch, project)
    server = build_server("pcb")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(project)})
    editor = _launch_process(
        "cloud-bridge-pcb-editor",
        executables.pcb_editor,
        Path(env["KICAD_MCP_PCB_FILE"]),
        tmp_path / "processes",
    )
    try:
        # A live GUI must be proven before inspecting through another stdio worker.
        await _wait_for_live_context(server, tmp_path / "readiness", editor)
        socket = RecordingSocket(frame(operation=BOARD_COUNTS_OPERATION))
        receipt = HandshakeReceipt(DEVICE, SESSION)
        assert (
            await _complete_authorized_inspection(
                socket,
                receipt,
                lambda _receipt: bound_worker(project, BOARD_COUNTS_OPERATION),
                board_counts=True,
            )
            == receipt
        )
        assert len(socket.sent) == 1
        result = socket.sent[0]["result"]
        assert result["kind"] == "connector.local_board_counts"
        assert result["operation"] == BOARD_COUNTS_OPERATION
        assert result["projectId"] == PROJECT
        assert result["source"] == "live-gui", "Local worker must not silently fall back to disk"
        counts = result["counts"]
        assert set(counts) == {"tracks", "vias", "footprints", "zones", "nets", "shapes"}
        assert counts["footprints"] > 0
        assert all(type(value) is int and 0 <= value <= 1_000_000 for value in counts.values())

        # The read transport sees only sanitized numeric counts and opaque IDs.
        payload = json.dumps(socket.sent)
        assert str(project) not in payload
        assert "LED_A" not in payload
        assert "clean-led-kicad10.kicad_pcb" not in payload

        wrong_project = RecordingSocket(
            frame(
                operation=BOARD_COUNTS_OPERATION,
                projectId="55555555-5555-4555-8555-555555555555",
            )
        )
        with pytest.raises((CloudHandshakeDeniedError, ProjectWorkerDeniedError)):
            await _complete_authorized_inspection(
                wrong_project,
                receipt,
                lambda _receipt: bound_worker(project, BOARD_COUNTS_OPERATION),
                board_counts=True,
            )
        assert wrong_project.sent == []
    finally:
        _stop_process(editor)
        reset_connection()
