"""Real localhost TLS/WSS, signed device proof and local MCP-worker inspection.

No live Cloud endpoint, production identities, database, or hardware writes.
The TLS peer simulates a server after signed authentication. This test does
not replace the separate Node/PostgreSQL Connector contract tests.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import ssl
import time
from pathlib import Path
from shutil import copyfile

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from test_isolated_tls_websocket_handshake import _synthetic_tls
from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed

from kicad_mcp.cloud_outbound_handshake import (
    CloudHandshakeDeniedError,
    HandshakeReceipt,
    execute_operator_board_counts_once,
    execute_operator_inspection_once,
)
from kicad_mcp.cloud_project_worker_bridge import BoundConnectorProjectWorker
from kicad_mcp.cloud_readonly_boundary import OperatorProject, VerifiedLocalBinding
from kicad_mcp.connection import reset_connection
from kicad_mcp.project.stdio_worker import project_stdio_worker
from kicad_mcp.server import build_server
from tests.conftest import call_tool_text
from tests.gui.test_kicad_gui_live_context import (
    _discover_executables,
    _launch_process,
    _stop_process,
    _wait_for_live_context,
)

DEVICE = "11111111-1111-4111-8111-111111111111"
PROJECT = "55555555-5555-4555-8555-555555555555"
FOREIGN_PROJECT = "77777777-7777-4777-8777-777777777777"
SESSION = "33333333-3333-4333-8333-333333333333"
CHALLENGE = "22222222-2222-4222-8222-222222222222"
SECOND_CHALLENGE = "44444444-4444-4444-8444-444444444444"
REQUEST = "66666666-6666-4666-8666-666666666666"
NONCE = base64.urlsafe_b64encode(bytes(range(32))).decode().rstrip("=")
BINDING = base64.urlsafe_b64encode(bytes(range(32, 64))).decode().rstrip("=")


def _signature(frame: dict[str, object]) -> bytes:
    raw = frame["signature"]
    assert isinstance(raw, str)
    return base64.urlsafe_b64decode(raw + "==")


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("operation", "requested_project", "live_gui"),
    [
        ("project_worker_inspection", PROJECT, False),
        ("project_board_counts", PROJECT, False),
        ("project_board_counts", FOREIGN_PROJECT, False),
        ("run_drc", PROJECT, False),
        pytest.param(
            "project_board_counts",
            PROJECT,
            True,
            id="signed-wss-native-gui-ready-worker",
            marks=[pytest.mark.gui, pytest.mark.slow],
        ),
    ],
)
async def test_signed_real_tls_wss_reaches_scoped_mcp_without_exposing_paths(
    tmp_path: Path,
    operation: str,
    requested_project: str,
    live_gui: bool,
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
) -> None:
    if live_gui and os.environ.get("KICAD_MCP_ENABLE_CLOUD_WORKER_GUI") != "1":
        pytest.skip("Set KICAD_MCP_ENABLE_CLOUD_WORKER_GUI=1 for signed WSS native GUI test")
    tls_server, ca_pem = _synthetic_tls(tmp_path)
    tls_client = ssl.create_default_context(cadata=ca_pem)
    signer = Ed25519PrivateKey.generate()
    verified = signer.public_key()
    project_dir = tmp_path / "secret project"
    project_dir.mkdir()
    if live_gui:
        fixture_dir = (
            Path(__file__).resolve().parents[2]
            / "packages/kicad-fixtures/fixtures/clean-led-kicad10"
        )
        for suffix in (".kicad_pro", ".kicad_pcb", ".kicad_sch"):
            copyfile(
                fixture_dir / f"clean-led-kicad10{suffix}",
                project_dir / f"clean-led-kicad10{suffix}",
            )
    else:
        if operation == "project_board_counts":
            fixture = Path(__file__).resolve().parents[1] / (
                "fixtures/benchmark_projects/pass_minimal_mcu_board/demo.kicad_pcb"
            )
            copyfile(fixture, project_dir / "board.kicad_pcb")
        (project_dir / "board.kicad_pro").write_text('{"confidential": "BOARD_SECRET"}')
    if live_gui:
        executables = _discover_executables()
        assert executables.pcb_editor is not None, "Explicit GUI test requires real KiCad"
        for name, value in {
            "KICAD_MCP_PROJECT_DIR": project_dir,
            "KICAD_MCP_PROJECT_FILE": project_dir / "clean-led-kicad10.kicad_pro",
            "KICAD_MCP_PCB_FILE": project_dir / "clean-led-kicad10.kicad_pcb",
            "KICAD_MCP_SCH_FILE": project_dir / "clean-led-kicad10.kicad_sch",
            "KICAD_MCP_OUTPUT_DIR": tmp_path / "mcp-output",
        }.items():
            monkeypatch.setenv(name, str(value))
        pcb_server = build_server("pcb")
        await call_tool_text(pcb_server, "kicad_set_project", {"project_dir": str(project_dir)})
        editor = _launch_process(
            "signed-wss-live-pcb",
            executables.pcb_editor,
            project_dir / "clean-led-kicad10.kicad_pcb",
            tmp_path / "pcb-process",
        )

        def stop_editor() -> None:
            try:
                _stop_process(editor)
            finally:
                reset_connection()

        request.addfinalizer(stop_editor)
        await _wait_for_live_context(pcb_server, tmp_path / "gui-readiness", editor)
    seen: list[str] = []
    delivered: list[dict[str, object]] = []

    async def server(ws: ServerConnection) -> None:
        hello = json.loads(await ws.recv())
        assert hello == {
            "kind": "device.hello",
            "version": 1,
            "ownerSub": "test-owner",
            "deviceId": DEVICE,
        }
        seen.append("hello")
        await ws.send(
            json.dumps(
                {
                    "kind": "device.challenge",
                    "version": 1,
                    "challengeId": CHALLENGE,
                    "deviceId": DEVICE,
                    "nonce": NONCE,
                    "expiresAtMs": int(time.time() * 1000) + 25_000,
                }
            )
        )
        proof = json.loads(await ws.recv())
        verified.verify(
            _signature(proof),
            b"kicad-cloud-device-handshake-v1\0"
            + CHALLENGE.encode()
            + b"\0"
            + DEVICE.encode()
            + b"\0"
            + NONCE.encode(),
        )
        seen.append("proof")
        await ws.send(
            json.dumps(
                {
                    "kind": "connector.session_challenge",
                    "version": 1,
                    "challengeId": SECOND_CHALLENGE,
                    "deviceId": DEVICE,
                    "sessionId": SESSION,
                    "nonce": NONCE,
                    "binding": BINDING,
                    "expiresAtMs": int(time.time() * 1000) + 25_000,
                }
            )
        )
        signed = json.loads(await ws.recv())
        verified.verify(
            _signature(signed),
            b"kicad-cloud-bound-session-v1\0"
            + SESSION.encode()
            + b"\0"
            + SECOND_CHALLENGE.encode()
            + b"\0"
            + DEVICE.encode()
            + b"\0"
            + NONCE.encode()
            + b"\0"
            + BINDING.encode(),
        )
        seen.append("session")
        await ws.send('{"kind":"connector.ready","version":1}')
        await ws.send(
            json.dumps(
                {
                    "kind": "connector.authorized_read",
                    "version": 1,
                    "sequence": 1,
                    "request": {
                        "kind": "connector.read_request",
                        "version": 1,
                        "requestId": REQUEST,
                        "deviceId": DEVICE,
                        "projectId": requested_project,
                        "operation": operation,
                        "deadlineUnixMs": int(time.time() * 1000) + 20_000,
                    },
                }
            )
        )
        if operation == "run_drc" or requested_project != PROJECT:
            receive = ws.recv()
            with pytest.raises(ConnectionClosed):
                await asyncio.wait_for(receive, 8)
            seen.append("operation-denied")
            return
        response = json.loads(await ws.recv())
        delivered.append(response)
        assert response["kind"] == "connector.read_result"
        assert response["sequence"] == 1
        payload = response["result"]
        assert payload["requestId"] == REQUEST
        assert payload["projectId"] == PROJECT
        assert payload["operation"] == operation
        if operation == "project_board_counts":
            assert payload["kind"] == "connector.local_board_counts"
            assert payload["source"] == ("live-gui" if live_gui else "file-backed")
            if live_gui:
                assert payload["counts"]["footprints"] > 0
            else:
                assert payload["counts"]["footprints"] == 3
            assert set(payload["counts"]) == {
                "tracks",
                "vias",
                "footprints",
                "zones",
                "nets",
                "shapes",
            }
            assert all(type(value) is int and value >= 0 for value in payload["counts"].values())
        else:
            assert isinstance(payload["status"]["engineVersion"], str)
            assert type(payload["status"]["cliAvailable"]) is bool
            assert type(payload["status"]["ipcAvailable"]) is bool
            caps = payload["status"]["capabilities"]
            assert set(caps) == {
                "fileBackedDrc",
                "fileBackedErc",
                "livePcbRead",
                "liveSchematicRead",
            }
            assert all(type(value) is bool for value in caps.values())
        assert str(project_dir) not in json.dumps(response)
        assert "BOARD_SECRET" not in json.dumps(response)
        assert "cliPath" not in json.dumps(response)
        if live_gui:
            assert "LED_A" not in json.dumps(response)
            assert "clean-led-kicad10.kicad_pcb" not in json.dumps(response)
        await ws.send(
            json.dumps(
                {
                    "kind": "connector.read_ack",
                    "version": 1,
                    "sequence": 1,
                    "requestId": REQUEST,
                }
            )
        )
        seen.append("metadata-only")

    def inspector(receipt: HandshakeReceipt) -> BoundConnectorProjectWorker:
        assert receipt == HandshakeReceipt(DEVICE, SESSION)
        allowed_operation = (
            "project_board_counts"
            if operation == "project_board_counts"
            else "project_worker_inspection"
        )
        return BoundConnectorProjectWorker(
            verified=VerifiedLocalBinding(
                device_id=DEVICE,
                project_id=PROJECT,
                operations=frozenset({allowed_operation}),
                session_id=SESSION,
                session_expires_unix_ms=int(time.time() * 1000) + 35_000,
            ),
            operator_project=OperatorProject(
                device_id=DEVICE,
                project_id=PROJECT,
                directory=project_dir,
                filename_stem="clean-led-kicad10" if live_gui else "board",
            ),
            current_authorization=lambda: True,
        )

    async with serve(
        server, "127.0.0.1", 0, ssl=tls_server, compression=None, max_size=1024
    ) as listener:
        assert listener.sockets
        origin = f"https://localhost:{listener.sockets[0].getsockname()[1]}"
        if live_gui:
            # This is a warm-worker transport acceptance, NOT cold-start acceptance.
            # First-use stdio initialization can exceed the signed 40-second
            # one-shot window. Prove the local worker is ready independently
            # before exercising TLS/device/session binding over the same PCB.
            async with asyncio.timeout(16):
                async with project_stdio_worker(project_dir) as local_client:
                    result = await local_client.call_tool("pcb_get_board_summary", {})
                    assert not result.is_error
        reader = (
            execute_operator_board_counts_once
            if operation == "project_board_counts"
            else execute_operator_inspection_once
        )
        session = reader(
            origin=origin,
            trusted_origin=origin,
            owner_sub="test-owner",
            device_id=DEVICE,
            signing_key=signer,
            tls_context=tls_client,
            inspector_factory=inspector,
        )
        if operation != "run_drc" and requested_project == PROJECT:
            assert await session == HandshakeReceipt(DEVICE, SESSION)
        else:
            with pytest.raises(CloudHandshakeDeniedError):
                await session

    assert seen == (
        ["hello", "proof", "session", "metadata-only"]
        if operation != "run_drc" and requested_project == PROJECT
        else ["hello", "proof", "session", "operation-denied"]
    )
    assert len(delivered) == int(operation != "run_drc" and requested_project == PROJECT)
