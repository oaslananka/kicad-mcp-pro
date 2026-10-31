"""Real localhost WSS test with browser-paired private key and bound local project.

The browser and pairing HTTP endpoints are synthetic. TLS, WebSocket,
both Ed25519 proof rounds, owner-key persistence and one-shot read are real.
This test never connects outside the disposable localhost TLS fixture.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import ssl
import time
from collections.abc import Callable
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from test_isolated_tls_websocket_handshake import _synthetic_tls
from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed

from kicad_mcp import cloud_once, cloud_outbound_handshake, cloud_pair
from kicad_mcp.cloud_outbound_handshake import HandshakeReceipt, execute_single_approved_read
from kicad_mcp.cloud_read_dispatch import LocalReadDispatch

pytestmark = pytest.mark.skipif(os.name != "posix", reason="Owner-only key binding is POSIX-only")

DEVICE = "11111111-1111-4111-8111-111111111111"
CHALLENGE = "22222222-2222-4222-8222-222222222222"
SESSION = "33333333-3333-4333-8333-333333333333"
SESSION_CHALLENGE = "44444444-4444-4444-8444-444444444444"
PROJECT = "55555555-5555-4555-8555-555555555555"
REQUEST = "66666666-6666-4666-8666-666666666666"
OWNER = "synthetic-owner"
NONCE = base64.urlsafe_b64encode(bytes(range(32))).decode().rstrip("=")
BINDING = base64.urlsafe_b64encode(bytes(range(32, 64))).decode().rstrip("=")
DEVICE_SECRET = base64.urlsafe_b64encode(bytes(range(64, 96))).decode().rstrip("=")


def _signature(message: dict[str, object]) -> bytes:
    value = message.get("signature")
    assert isinstance(value, str)
    return base64.urlsafe_b64decode(value + "==")


async def _scenario(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    expire_during_proof: bool = False,
    expire_after_inspection: bool = False,
) -> list[str]:
    server_tls, ca_pem = _synthetic_tls(tmp_path)
    observations: list[str] = []
    keyfile = tmp_path / "enrolled.pem"
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (project_dir / "demo.kicad_pro").write_text("private fixture file")
    accepted_public_key = None
    approval_clock = {"monotonic_ns": time.monotonic_ns()}
    if expire_during_proof or expire_after_inspection:
        monkeypatch.setattr(
            cloud_once.time,
            "monotonic_ns",
            lambda: approval_clock["monotonic_ns"],
        )
    if expire_after_inspection:
        ordinary_read = LocalReadDispatch.read

        def expire_after_finished_read(
            dispatcher: LocalReadDispatch, frame: bytes, *, sequence: int
        ) -> dict[str, object]:
            result = ordinary_read(dispatcher, frame, sequence=sequence)
            # This runs after read()'s final authorization but before
            # asyncio.to_thread yields the result to the WSS sender.
            approval_clock["monotonic_ns"] += 30_000_000_000
            return result

        monkeypatch.setattr(LocalReadDispatch, "read", expire_after_finished_read)

    async def ws_peer(ws: ServerConnection) -> None:
        hello = json.loads(await ws.recv())
        assert hello == {
            "kind": "device.hello",
            "version": 1,
            "deviceId": DEVICE,
            "ownerSub": OWNER,
        }
        observations.append("device-hello")
        expiry = time.time_ns() // 1_000_000 + 25_000
        await ws.send(
            json.dumps(
                {
                    "kind": "device.challenge",
                    "version": 1,
                    "challengeId": CHALLENGE,
                    "deviceId": DEVICE,
                    "nonce": NONCE,
                    "expiresAtMs": expiry,
                }
            )
        )
        proof = json.loads(await ws.recv())
        assert accepted_public_key is not None
        accepted_public_key.verify(
            _signature(proof),
            b"kicad-cloud-device-handshake-v1\0"
            + CHALLENGE.encode()
            + b"\0"
            + DEVICE.encode()
            + b"\0"
            + NONCE.encode(),
        )
        observations.append("device-proof")
        await ws.send(
            json.dumps(
                {
                    "kind": "connector.session_challenge",
                    "version": 1,
                    "challengeId": SESSION_CHALLENGE,
                    "deviceId": DEVICE,
                    "sessionId": SESSION,
                    "nonce": NONCE,
                    "binding": BINDING,
                    "expiresAtMs": expiry,
                }
            )
        )
        session_proof = json.loads(await ws.recv())
        accepted_public_key.verify(
            _signature(session_proof),
            b"kicad-cloud-bound-session-v1\0"
            + SESSION.encode()
            + b"\0"
            + SESSION_CHALLENGE.encode()
            + b"\0"
            + DEVICE.encode()
            + b"\0"
            + NONCE.encode()
            + b"\0"
            + BINDING.encode(),
        )
        observations.append("session-proof")
        if expire_during_proof:
            # A valid remote proof must not reset an expired local approval.
            approval_clock["monotonic_ns"] += 30_000_000_000
            await ws.send('{"kind":"connector.ready","version":1}')
            # Build the single awaitable outside the exception assertion so
            # the raises block contains no nested function calls.
            pending_close = asyncio.wait_for(ws.recv(), timeout=3)
            with pytest.raises(ConnectionClosed):
                await pending_close
            observations.append("denied-before-summary")
            return
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
                        "operation": "project_summary",
                        "deadlineUnixMs": time.time_ns() // 1_000_000 + 5_000,
                    },
                }
            )
        )
        if expire_after_inspection:
            try:
                await asyncio.wait_for(ws.recv(), timeout=3)
                observations.append("unexpected-metadata-delivery")
            except ConnectionClosed:
                observations.append("denied-before-delivery")
            return
        result = json.loads(await ws.recv())
        assert result["kind"] == "connector.read_result"
        assert result["result"]["requestId"] == REQUEST
        assert result["result"]["files"] == {
            "projectPresent": True,
            "boardPresent": False,
            "schematicPresent": False,
        }
        observations.append("metadata-only")
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

    async with serve(ws_peer, "127.0.0.1", 0, ssl=server_tls, compression=None) as server:
        assert server.sockets
        port = server.sockets[0].getsockname()[1]
        origin = f"https://localhost:{port}"
        fingerprint = ""
        status_checks = 0
        monkeypatch.setattr(cloud_pair.time, "sleep", lambda _: None)

        def local_enrollment_http(
            destination: tuple[str, int, str], endpoint: str, body: dict[str, object], status: int
        ) -> dict[str, object]:
            nonlocal accepted_public_key, fingerprint, status_checks
            assert destination == ("localhost", port, origin)
            if endpoint.endswith("/challenge"):
                assert status == 201
                public_der = base64.b64decode(str(body["publicKeyDer"]), validate=True)
                fingerprint = hashlib.sha256(public_der).hexdigest()
                accepted_public_key = cloud_once._load_owner_key(keyfile).public_key()
                assert (
                    accepted_public_key.public_bytes(
                        Encoding.DER, PublicFormat.SubjectPublicKeyInfo
                    )
                    == public_der
                )
                observations.append("pairing-challenge")
                return {
                    "challengeId": CHALLENGE,
                    "userCode": "ABCDEF-123456",
                    "deviceCode": DEVICE_SECRET,
                    "deviceFingerprint": fingerprint,
                    "expiresAtMs": time.time_ns() // 1_000_000 + 25_000,
                }
            if endpoint.endswith("/status"):
                assert status == 200
                assert observations == (
                    ["pairing-challenge"]
                    if status_checks == 0
                    else ["pairing-challenge", "status-ready", "browser-approved"]
                )
                assert accepted_public_key is not None
                proof = (
                    b"kicad-cloud-pairing-status-v1\0"
                    + CHALLENGE.encode()
                    + b"\0"
                    + DEVICE_SECRET.encode()
                )
                accepted_public_key.verify(_signature(body), proof)
                status_checks += 1
                observations.append(
                    "status-ready" if status_checks == 1 else "approval-status-verified"
                )
                return {"approved": status_checks == 2}
            assert endpoint.endswith("/redeem")
            assert status == 200
            assert observations == [
                "pairing-challenge",
                "status-ready",
                "browser-approved",
                "approval-status-verified",
            ]
            expected = (
                b"kicad-cloud-pairing-proof-v1\0"
                + CHALLENGE.encode()
                + b"\0"
                + DEVICE_SECRET.encode()
            )
            assert accepted_public_key is not None
            accepted_public_key.verify(_signature(body), expected)
            observations.append("pairing-redeemed")
            return {"deviceId": DEVICE, "deviceFingerprint": fingerprint, "enabled": False}

        def fake_browser(url: str, challenge: str, code: str) -> None:
            assert url == origin + "/devices/pairing"
            assert challenge == CHALLENGE
            assert code == "ABCDEF-123456"
            observations.append("browser-approved")

        monkeypatch.setattr(cloud_pair, "_post", local_enrollment_http)
        enrolled_device, fp = cloud_pair.enroll(origin, "Fixture", keyfile, fake_browser)
        assert enrolled_device == DEVICE
        assert fp == fingerprint
        assert cloud_once._read_owner_binding(keyfile) == {
            "origin": origin,
            "deviceId": DEVICE,
            "fingerprint": fingerprint,
        }
        assert keyfile.stat().st_mode & 0o777 == 0o600
        trust = ssl.create_default_context(cadata=ca_pem)

        async def use_real_verified_transport(
            *,
            origin: str,
            trusted_origin: str,
            owner_sub: str,
            device_id: str,
            signing_key: Ed25519PrivateKey,
            dispatcher_factory: Callable[[HandshakeReceipt], LocalReadDispatch],
        ) -> HandshakeReceipt:
            return await execute_single_approved_read(
                origin=origin,
                trusted_origin=trusted_origin,
                owner_sub=owner_sub,
                device_id=device_id,
                signing_key=signing_key,
                dispatcher_factory=dispatcher_factory,
                tls_context=trust,
            )

        # Isolated real-WSS fixture: no independent human owner verifier exists.
        monkeypatch.setattr(
            cloud_outbound_handshake, "_require_independent_read_authority", lambda: None
        )
        # Synthetic acceptance only; the real CLI denies without an owner authority.
        monkeypatch.setattr(cloud_once, "_require_independent_owner_authority", lambda: None)
        monkeypatch.setattr(cloud_once, "execute_single_approved_read", use_real_verified_transport)
        monkeypatch.setattr(cloud_once.sys.stdin, "isatty", lambda: True)
        monkeypatch.setattr(cloud_once.sys.stdout, "isatty", lambda: True)
        monkeypatch.setattr(cloud_once.secrets, "token_hex", lambda _: "cafebabe")
        monkeypatch.setattr("builtins.input", lambda *_: "APPROVE CAFEBABE")
        from kicad_mcp import cloud_local_registry

        monkeypatch.setattr(
            cloud_local_registry,
            "resolve_registered_read",
            lambda **_: cloud_local_registry.LocalRegisteredRead(keyfile, project_dir, "demo"),
        )
        args = [
            "--cloud-origin",
            origin,
            "--owner-sub",
            OWNER,
            "--device-id",
            DEVICE,
            "--project-id",
            PROJECT,
            "--allow-once",
        ]
        exit_status = await asyncio.to_thread(cloud_once.main, args)
        assert exit_status == (1 if expire_during_proof or expire_after_inspection else 0)

    return observations


def test_browser_enrollment_then_real_tls_wss_single_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert asyncio.run(_scenario(tmp_path, monkeypatch)) == [
        "pairing-challenge",
        "status-ready",
        "browser-approved",
        "approval-status-verified",
        "pairing-redeemed",
        "device-hello",
        "device-proof",
        "session-proof",
        "metadata-only",
    ]


def test_real_tls_wss_expired_foreground_consent_never_sends_project_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert asyncio.run(_scenario(tmp_path, monkeypatch, expire_during_proof=True)) == [
        "pairing-challenge",
        "status-ready",
        "browser-approved",
        "approval-status-verified",
        "pairing-redeemed",
        "device-hello",
        "device-proof",
        "session-proof",
        "denied-before-summary",
    ]


def test_real_tls_wss_expiry_between_read_and_delivery_denies_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert asyncio.run(_scenario(tmp_path, monkeypatch, expire_after_inspection=True)) == [
        "pairing-challenge",
        "status-ready",
        "browser-approved",
        "approval-status-verified",
        "pairing-redeemed",
        "device-hello",
        "device-proof",
        "session-proof",
        "denied-before-delivery",
    ]
