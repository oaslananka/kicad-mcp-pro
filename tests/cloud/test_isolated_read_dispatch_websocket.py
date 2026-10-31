"""Synthetic WSS peer exchanges one metadata-only read after verified proofs.

Not a Cloud deployment or production protocol implementation. Current Cloud
server deliberately does not dispatch reads, and this fixture must never be
used as a network transport adapter.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import ssl
from datetime import UTC, datetime
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from test_isolated_tls_websocket_handshake import _synthetic_tls
from websockets.asyncio.client import connect
from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed

from kicad_mcp.cloud_device_proofs import sign_device_challenge, sign_session_challenge
from kicad_mcp.cloud_read_dispatch import LocalReadDispatch
from kicad_mcp.cloud_readonly_boundary import (
    LocalReadDeniedError,
    OperatorProject,
    VerifiedLocalBinding,
)

pytestmark = pytest.mark.skipif(os.name != "posix", reason="Local no-follow file policy POSIX-only")
DEVICE = "11111111-1111-4111-8111-111111111111"
PROJECT = "22222222-2222-4222-8222-222222222222"
SESSION = "44444444-4444-4444-8444-444444444444"
CHALLENGE = "33333333-3333-4333-8333-333333333333"
READ = "55555555-5555-4555-8555-555555555555"
NONCE = base64.urlsafe_b64encode(bytes(range(32))).decode().rstrip("=")
BINDING = base64.urlsafe_b64encode(bytes(range(32, 64))).decode().rstrip("=")


def _signature(frame: dict[str, object]) -> bytes:
    signature = frame["signature"]
    assert isinstance(signature, str)
    return base64.urlsafe_b64decode(signature + "==")


async def _exercise(tmp_path: Path, *, forbidden: bool) -> dict[str, object]:
    server_tls, trusted_pem = _synthetic_tls(tmp_path)
    key = Ed25519PrivateKey.generate()

    def clock() -> int:
        return int(datetime.now(UTC).timestamp() * 1000)

    # Synthetic transport authority is an explicit local fixture, not
    # taken from a socket, server claim, device.hello, or Cloud JSON.
    folder = tmp_path / "synthetic-project"
    folder.mkdir()
    (folder / "demo.kicad_pro").write_text("confidential synthetic data")
    owner_policy = OperatorProject(DEVICE, PROJECT, folder, "demo")
    dispatcher = LocalReadDispatch(
        verified=VerifiedLocalBinding(
            DEVICE, PROJECT, frozenset({"project_summary"}), SESSION, clock() + 60_000
        ),
        operator_project=owner_policy,
        current_authorization=lambda: True,  # Synthetic, no real OAuth grant
    )
    observations: dict[str, object] = {}

    async def synthetic_peer(ws: ServerConnection) -> None:
        hello = json.loads(await ws.recv())
        assert hello == {
            "kind": "device.hello",
            "version": 1,
            "deviceId": DEVICE,
            "ownerSub": "test-only-owner",
        }
        expires = clock() + 40_000
        await ws.send(
            json.dumps(
                {
                    "kind": "device.challenge",
                    "version": 1,
                    "challengeId": CHALLENGE,
                    "deviceId": DEVICE,
                    "nonce": NONCE,
                    "expiresAtMs": expires,
                }
            )
        )
        first = json.loads(await ws.recv())
        assert first["kind"] == "device.proof"
        key.public_key().verify(
            _signature(first),
            b"kicad-cloud-device-handshake-v1\0"
            + CHALLENGE.encode()
            + b"\0"
            + DEVICE.encode()
            + b"\0"
            + NONCE.encode(),
        )
        observations["first_proof"] = True
        await ws.send(
            json.dumps(
                {
                    "kind": "connector.session_challenge",
                    "version": 1,
                    "deviceId": DEVICE,
                    "sessionId": SESSION,
                    "challengeId": CHALLENGE,
                    "nonce": NONCE,
                    "binding": BINDING,
                    "expiresAtMs": expires,
                }
            )
        )
        second = json.loads(await ws.recv())
        key.public_key().verify(
            _signature(second),
            b"kicad-cloud-bound-session-v1\0"
            + SESSION.encode()
            + b"\0"
            + CHALLENGE.encode()
            + b"\0"
            + DEVICE.encode()
            + b"\0"
            + NONCE.encode()
            + b"\0"
            + BINDING.encode(),
        )
        observations["session_proof"] = True
        await ws.send(json.dumps({"kind": "connector.ready", "version": 1}))
        # Test-only relay wrapper, NOT the current Cloud wire protocol.
        # Sequence must come from a future independently verified Cloud
        # grant/read gate, never trust a caller-supplied sequence.
        frame = {
            "kind": "connector.read_request",
            "version": 1,
            "requestId": READ,
            "deviceId": DEVICE,
            "projectId": PROJECT,
            "operation": "run_drc" if forbidden else "project_summary",
            "deadlineUnixMs": clock() + 1500,
        }
        await ws.send(json.dumps({"fixtureRequest": frame, "fixtureSequence": 1}))
        if forbidden:
            try:
                await ws.recv()
                raise AssertionError("unexpected response for disallowed native command")
            except ConnectionClosed:
                observations["no_native_response"] = True
        else:
            answer = json.loads(await ws.recv())
            observations["sanitized"] = answer

    async def local_device(url: str) -> None:
        ctx = ssl.create_default_context(cadata=trusted_pem)
        async with connect(
            url, ssl=ctx, origin=None, compression=None, max_size=1024, open_timeout=3
        ) as ws:
            assert ws.transport.get_extra_info("ssl_object") is not None
            await ws.send(
                json.dumps(
                    {
                        "kind": "device.hello",
                        "version": 1,
                        "deviceId": DEVICE,
                        "ownerSub": "test-only-owner",
                    }
                )
            )
            first = await ws.recv()
            assert isinstance(first, str)
            await ws.send(
                json.dumps(
                    sign_device_challenge(
                        first.encode(),
                        expected_device_id=DEVICE,
                        now_unix_ms=clock(),
                        signing_key=key,
                    )
                )
            )
            second = await ws.recv()
            assert isinstance(second, str)
            await ws.send(
                json.dumps(
                    sign_session_challenge(
                        second.encode(),
                        expected_device_id=DEVICE,
                        now_unix_ms=clock(),
                        signing_key=key,
                    )
                )
            )
            ready = json.loads(await ws.recv())
            assert ready == {"kind": "connector.ready", "version": 1}
            # No real Cloud admission ticket exists: only fixture local authority.
            relay = json.loads(await ws.recv())
            assert set(relay) == {"fixtureRequest", "fixtureSequence"}
            raw = json.dumps(relay["fixtureRequest"], separators=(",", ":")).encode()
            try:
                response = dispatcher.read(raw, sequence=1)
            except LocalReadDeniedError:
                await ws.close(code=1008, reason="policy")
            else:
                await ws.send(json.dumps(response))
        dispatcher.close()

    async with serve(synthetic_peer, "127.0.0.1", 0, ssl=server_tls) as server:
        assert server.sockets
        port = server.sockets[0].getsockname()[1]
        async with asyncio.timeout(6):
            await local_device(f"wss://localhost:{port}/api/v1/connector/ws")
    with pytest.raises(LocalReadDeniedError):
        dispatcher.read(b"{}", sequence=2)
    return observations


def test_tls_signed_session_then_only_presence_is_delivered(tmp_path: Path) -> None:
    result = asyncio.run(_exercise(tmp_path, forbidden=False))
    assert result["first_proof"]
    assert result["session_proof"]

    response = result["sanitized"]
    assert isinstance(response, dict)
    assert response["files"] == {
        "projectPresent": True,
        "boardPresent": False,
        "schematicPresent": False,
    }
    assert "demo" not in json.dumps(response)
    assert "confidential" not in json.dumps(response)


def test_tls_signed_session_still_denies_remote_native_command(tmp_path: Path) -> None:
    result = asyncio.run(_exercise(tmp_path, forbidden=True))
    assert result["first_proof"]
    assert result["session_proof"]

    assert result["no_native_response"]
    assert "sanitized" not in result
