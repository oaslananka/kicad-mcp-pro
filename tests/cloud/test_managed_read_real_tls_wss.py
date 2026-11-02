"""Authenticated managed metadata exchange on disposable localhost TLS/WebSocket.

Only ephemeral fixture keys and a self-signed test authority are used. The
production signer, Cloud registration, startup service and real board are untouched.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import ssl
import time
from pathlib import Path
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from test_isolated_tls_websocket_handshake import _synthetic_tls
from websockets.asyncio.client import connect
from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed

from kicad_mcp.cloud_device_proofs import sign_device_challenge, sign_session_challenge
from kicad_mcp.cloud_managed_read_transport import serve_authenticated_reads
from kicad_mcp.cloud_outbound_handshake import (
    CloudHandshakeDeniedError,
    HandshakeReceipt,
)
from kicad_mcp.cloud_read_dispatch import LocalReadDispatch
from kicad_mcp.cloud_readonly_boundary import (
    LocalReadDeniedError,
    OperatorProject,
    VerifiedLocalBinding,
)

DEVICE = "11111111-1111-4111-8111-111111111111"
PROJECT = "22222222-2222-4222-8222-222222222222"
SESSION = "33333333-3333-4333-8333-333333333333"


def _proof_signature(proof: object) -> bytes:
    assert isinstance(proof, dict) and isinstance(proof.get("signature"), str)
    return base64.urlsafe_b64decode(proof["signature"] + "==")


def _request(sequence: int) -> dict[str, object]:
    return {
        "kind": "connector.authorized_read",
        "version": 1,
        "sequence": sequence,
        "request": {
            "kind": "connector.read_request",
            "version": 1,
            "requestId": str(uuid4()),
            "deviceId": DEVICE,
            "projectId": PROJECT,
            "operation": "project_summary",
            "deadlineUnixMs": int(time.time() * 1000) + 20_000,
        },
    }


@pytest.mark.anyio
@pytest.mark.parametrize("revoke_after_first", [False, True])
async def test_signed_tls_wss_two_reads_and_owner_off(
    tmp_path: Path, revoke_after_first: bool
) -> None:
    server_context, ca_pem = _synthetic_tls(tmp_path)
    client_context = ssl.create_default_context(cadata=ca_pem)
    signer = Ed25519PrivateKey.generate()
    public_key = signer.public_key()
    root = tmp_path / "private-design"
    root.mkdir()
    original = b'{"PRIVATE_SCHEMATIC": "NEVER_SEND"}'
    original_file = root / "board.kicad_pro"
    original_file.write_bytes(original)
    original_sha = hashlib.sha256(original).hexdigest()
    grant = [True]
    responses: list[dict[str, object]] = []
    event_order: list[str] = []

    async def server(ws: ServerConnection) -> None:
        hello = json.loads(await ws.recv())
        assert hello == {
            "kind": "device.hello",
            "version": 1,
            "ownerSub": "fixture-owner",
            "deviceId": DEVICE,
        }
        challenge = str(uuid4())
        nonce = base64.urlsafe_b64encode(bytes(range(32))).decode().rstrip("=")
        binding = base64.urlsafe_b64encode(bytes(range(32, 64))).decode().rstrip("=")
        device_challenge = {
            "kind": "device.challenge",
            "version": 1,
            "challengeId": challenge,
            "deviceId": DEVICE,
            "nonce": nonce,
            "expiresAtMs": int(time.time() * 1000) + 25_000,
        }
        await ws.send(json.dumps(device_challenge))
        device_proof = json.loads(await ws.recv())
        public_key.verify(
            _proof_signature(device_proof),
            b"kicad-cloud-device-handshake-v1\0"
            + challenge.encode()
            + b"\0"
            + DEVICE.encode()
            + b"\0"
            + nonce.encode(),
        )
        event_order.append("device-verified")
        session_challenge = {
            "kind": "connector.session_challenge",
            "version": 1,
            "challengeId": str(uuid4()),
            "deviceId": DEVICE,
            "sessionId": SESSION,
            "nonce": nonce,
            "binding": binding,
            "expiresAtMs": int(time.time() * 1000) + 25_000,
        }
        await ws.send(json.dumps(session_challenge))
        session_proof = json.loads(await ws.recv())
        public_key.verify(
            _proof_signature(session_proof),
            b"kicad-cloud-bound-session-v1\0"
            + SESSION.encode()
            + b"\0"
            + session_challenge["challengeId"].encode()
            + b"\0"
            + DEVICE.encode()
            + b"\0"
            + nonce.encode()
            + b"\0"
            + binding.encode(),
        )
        event_order.append("session-verified")
        await ws.send('{"kind":"connector.ready","version":1}')
        for sequence in (1, 2):
            if sequence == 2 and revoke_after_first:
                grant[0] = False
            await ws.send(json.dumps(_request(sequence)))
            if sequence == 2 and revoke_after_first:
                # The server must receive no response once the local grant
                # is turned off, even from a formerly valid signed socket.
                async with asyncio.timeout(5):
                    with pytest.raises(ConnectionClosed):
                        await ws.recv()
                return
            response = json.loads(await ws.recv())
            responses.append(response)
            assert response["kind"] == "connector.read_result"
            assert response["sequence"] == sequence
            result = response["result"]
            assert result["operation"] == "project_summary"
            assert result["files"]["projectPresent"] is True
            assert "PRIVATE_SCHEMATIC" not in json.dumps(response)
            assert str(root) not in json.dumps(response)
            await ws.send(
                json.dumps(
                    {
                        "kind": "connector.read_ack",
                        "version": 1,
                        "sequence": sequence,
                        "requestId": result["requestId"],
                    }
                )
            )

    async with serve(
        server, "127.0.0.1", 0, ssl=server_context, compression=None, max_size=1024
    ) as listener:
        assert listener.sockets
        port = listener.sockets[0].getsockname()[1]
        async with connect(
            f"wss://localhost:{port}/api/v1/connector/ws",
            ssl=client_context,
            compression=None,
            max_size=1024,
        ) as socket:
            await socket.send(
                json.dumps(
                    {
                        "kind": "device.hello",
                        "version": 1,
                        "ownerSub": "fixture-owner",
                        "deviceId": DEVICE,
                    }
                )
            )
            challenge = await socket.recv()
            assert isinstance(challenge, str)
            device_proof = sign_device_challenge(
                challenge.encode(),
                expected_device_id=DEVICE,
                now_unix_ms=int(time.time() * 1000),
                signing_key=signer,
            )
            await socket.send(json.dumps(device_proof))
            session = await socket.recv()
            assert isinstance(session, str)
            session_proof = sign_session_challenge(
                session.encode(),
                expected_device_id=DEVICE,
                now_unix_ms=int(time.time() * 1000),
                signing_key=signer,
            )
            await socket.send(json.dumps(session_proof))
            ready = json.loads(await socket.recv())
            assert ready == {"kind": "connector.ready", "version": 1}

            def dispatcher_factory(receipt: HandshakeReceipt) -> LocalReadDispatch:
                return LocalReadDispatch(
                    verified=VerifiedLocalBinding(
                        device_id=receipt.device_id,
                        project_id=PROJECT,
                        operations=frozenset({"project_summary"}),
                        session_id=receipt.session_id,
                        session_expires_unix_ms=int(time.time() * 1000) + 180_000,
                    ),
                    operator_project=OperatorProject(
                        device_id=DEVICE,
                        project_id=PROJECT,
                        directory=root,
                        filename_stem="board",
                    ),
                    current_authorization=lambda: grant[0],
                    max_reads=2,
                )

            client = serve_authenticated_reads(
                socket,
                HandshakeReceipt(DEVICE, SESSION),
                dispatcher_factory,
                max_reads=2,
            )
            if revoke_after_first:
                with pytest.raises((CloudHandshakeDeniedError, LocalReadDeniedError)):
                    await client
            else:
                assert await client == HandshakeReceipt(DEVICE, SESSION)

    assert event_order == ["device-verified", "session-verified"]
    assert len(responses) == (1 if revoke_after_first else 2)
    assert hashlib.sha256(original_file.read_bytes()).hexdigest() == original_sha
