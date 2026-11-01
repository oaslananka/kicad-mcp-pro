"""Real localhost TLS/WSS, signed device proof and local MCP-worker inspection.

No live Cloud endpoint, production identities, database, or hardware writes.
The TLS peer simulates a server after signed authentication. This test does
not replace the separate Node/PostgreSQL Connector contract tests.
"""

from __future__ import annotations

import asyncio
import base64
import json
import ssl
import time
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from test_isolated_tls_websocket_handshake import _synthetic_tls
from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed

from kicad_mcp.cloud_outbound_handshake import (
    CloudHandshakeDeniedError,
    HandshakeReceipt,
    execute_operator_inspection_once,
)
from kicad_mcp.cloud_project_worker_bridge import BoundConnectorProjectWorker
from kicad_mcp.cloud_readonly_boundary import OperatorProject, VerifiedLocalBinding

DEVICE = "11111111-1111-4111-8111-111111111111"
PROJECT = "55555555-5555-4555-8555-555555555555"
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
@pytest.mark.parametrize("operation", ["project_worker_inspection", "run_drc"])
async def test_signed_real_tls_wss_reaches_scoped_mcp_without_exposing_paths(
    tmp_path: Path, operation: str
) -> None:
    tls_server, ca_pem = _synthetic_tls(tmp_path)
    tls_client = ssl.create_default_context(cadata=ca_pem)
    signer = Ed25519PrivateKey.generate()
    verified = signer.public_key()
    project_dir = tmp_path / "secret project"
    project_dir.mkdir()
    (project_dir / "board.kicad_pro").write_text('{"confidential": "BOARD_SECRET"}')
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
                        "projectId": PROJECT,
                        "operation": operation,
                        "deadlineUnixMs": int(time.time() * 1000) + 20_000,
                    },
                }
            )
        )
        if operation != "project_worker_inspection":
            with pytest.raises(ConnectionClosed):
                await asyncio.wait_for(ws.recv(), 8)
            seen.append("operation-denied")
            return
        response = json.loads(await ws.recv())
        delivered.append(response)
        assert response["kind"] == "connector.read_result"
        assert response["sequence"] == 1
        payload = response["result"]
        assert payload["requestId"] == REQUEST
        assert payload["projectId"] == PROJECT
        assert payload["operation"] == "project_worker_inspection"
        assert isinstance(payload["status"]["engineVersion"], str)
        assert type(payload["status"]["cliAvailable"]) is bool
        assert type(payload["status"]["ipcAvailable"]) is bool
        assert str(project_dir) not in json.dumps(response)
        assert "BOARD_SECRET" not in json.dumps(response)
        assert "cliPath" not in json.dumps(response)
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
        return BoundConnectorProjectWorker(
            verified=VerifiedLocalBinding(
                device_id=DEVICE,
                project_id=PROJECT,
                operations=frozenset({"project_worker_inspection"}),
                session_id=SESSION,
                session_expires_unix_ms=int(time.time() * 1000) + 35_000,
            ),
            operator_project=OperatorProject(
                device_id=DEVICE,
                project_id=PROJECT,
                directory=project_dir,
                filename_stem="board",
            ),
            current_authorization=lambda: True,
        )

    async with serve(
        server, "127.0.0.1", 0, ssl=tls_server, compression=None, max_size=1024
    ) as listener:
        assert listener.sockets
        origin = f"https://localhost:{listener.sockets[0].getsockname()[1]}"
        session = execute_operator_inspection_once(
            origin=origin,
            trusted_origin=origin,
            owner_sub="test-owner",
            device_id=DEVICE,
            signing_key=signer,
            tls_context=tls_client,
            inspector_factory=inspector,
        )
        if operation == "project_worker_inspection":
            assert await session == HandshakeReceipt(DEVICE, SESSION)
        else:
            with pytest.raises(CloudHandshakeDeniedError):
                await session

    assert seen == (
        ["hello", "proof", "session", "metadata-only"]
        if operation == "project_worker_inspection"
        else ["hello", "proof", "session", "operation-denied"]
    )
    assert len(delivered) == int(operation == "project_worker_inspection")
