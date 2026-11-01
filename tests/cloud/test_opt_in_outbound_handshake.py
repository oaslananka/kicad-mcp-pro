"""Real opt-in client, synthetic localhost TLS and Ed25519 Cloud proof peer."""

from __future__ import annotations

import asyncio
import base64
import json
import ssl
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from unittest.mock import patch

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from test_isolated_tls_websocket_handshake import _synthetic_tls
from websockets.asyncio.client import ClientConnection
from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed

from kicad_mcp import cloud_outbound_handshake
from kicad_mcp.cloud_outbound_handshake import (
    CloudHandshakeDeniedError,
    HandshakeReceipt,
    _endpoint,
    establish_proof_only_handshake,
    execute_operator_presence_once,
    execute_single_approved_read,
)
from kicad_mcp.cloud_read_dispatch import LocalReadDispatch
from kicad_mcp.cloud_readonly_boundary import OperatorProject, VerifiedLocalBinding

DEVICE = "11111111-1111-4111-8111-111111111111"
OTHER_DEVICE = "22222222-2222-4222-8222-222222222222"
CHALLENGE = "33333333-3333-4333-8333-333333333333"
SESSION = "44444444-4444-4444-8444-444444444444"
SESSION_CHALLENGE = "55555555-5555-4555-8555-555555555555"
OWNER = "fixture-owner"
NONCE = base64.urlsafe_b64encode(bytes(range(32))).decode().rstrip("=")
BINDING = base64.urlsafe_b64encode(bytes(range(32, 64))).decode().rstrip("=")
PROJECT = "66666666-6666-4666-8666-666666666666"
READ = "77777777-7777-4777-8777-777777777777"


@pytest.mark.parametrize(
    "entrypoint", ["execute_single_approved_read", "_perform_outbound_session"]
)
def test_unverified_direct_read_transport_denies_before_any_network(
    monkeypatch: pytest.MonkeyPatch, entrypoint: str
) -> None:
    """Even callers bypassing the CLI must not open a read-capable WSS."""
    monkeypatch.setattr(
        cloud_outbound_handshake,
        "connect",
        lambda *_args, **_kwargs: pytest.fail("ownerless read reached a socket"),
    )
    runner = getattr(cloud_outbound_handshake, entrypoint)(
        origin="https://localhost",
        trusted_origin="https://localhost",
        owner_sub=OWNER,
        device_id=DEVICE,
        signing_key=Ed25519PrivateKey.generate(),
        dispatcher_factory=lambda *_: None,
    )
    with pytest.raises(CloudHandshakeDeniedError, match="handshake denied"):
        asyncio.run(runner)


def test_direct_read_completion_requires_independent_owner_before_dispatch() -> None:
    """A ready-socket helper must not bypass the read transport owner gate."""
    receipt = HandshakeReceipt(device_id=DEVICE, session_id=SESSION)

    def unauthorized_dispatcher(_: HandshakeReceipt) -> LocalReadDispatch:
        pytest.fail("unverified owner caused a dispatcher invocation")

    task = cloud_outbound_handshake._complete_authorized_read(
        cast(ClientConnection, None), receipt, unauthorized_dispatcher
    )
    with pytest.raises(CloudHandshakeDeniedError, match="handshake denied"):
        asyncio.run(task)


def _sig(reply: dict[str, object]) -> bytes:
    value = reply.get("signature")
    assert isinstance(value, str)
    return base64.urlsafe_b64decode(value + "==")


async def _scenario(tmp_path: Path, mode: str = "success", *, pilot: bool = False) -> list[str]:
    tls, pem = _synthetic_tls(tmp_path)
    signing_key = Ed25519PrivateKey.generate()
    observations: list[str] = []

    async def peer(ws: ServerConnection) -> None:
        try:
            hello = json.loads(await ws.recv())
            assert hello == {
                "kind": "device.hello",
                "version": 1,
                "ownerSub": OWNER,
                "deviceId": DEVICE,
            }
            observations.append("hello")
            expiry = int(datetime.now(UTC).timestamp() * 1000) + 30_000
            if mode == "premature-ready":
                await ws.send('{"kind":"connector.ready","version":1}')
                return
            await ws.send(
                json.dumps(
                    {
                        "kind": "device.challenge",
                        "version": 1,
                        "challengeId": CHALLENGE,
                        "deviceId": OTHER_DEVICE if mode == "wrong-device" else DEVICE,
                        "nonce": NONCE,
                        "expiresAtMs": expiry,
                    }
                )
            )
            proof = json.loads(await ws.recv())
            signing_key.public_key().verify(
                _sig(proof),
                b"kicad-cloud-device-handshake-v1\0"
                + CHALLENGE.encode()
                + b"\0"
                + DEVICE.encode()
                + b"\0"
                + NONCE.encode(),
            )
            observations.append("device_verified")
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
            second = json.loads(await ws.recv())
            signing_key.public_key().verify(
                _sig(second),
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
            observations.append("session_verified")
            if mode == "bad-ready":
                await ws.send('{"kind":"connector.ready","version":2}')
            elif mode == "binary-ready":
                await ws.send(b'{"kind":"connector.ready","version":1}')
            else:
                await ws.send('{"kind":"connector.ready","version":1}')
            if mode in {"approved-read", "denied-operation", "revoked", "wrong-session"}:
                request = {
                    "kind": "connector.read_request",
                    "version": 1,
                    "requestId": READ,
                    "deviceId": DEVICE,
                    "projectId": PROJECT,
                    "operation": "run_drc" if mode == "denied-operation" else "project_summary",
                    "deadlineUnixMs": int(datetime.now(UTC).timestamp() * 1000) + 5_000,
                }
                await ws.send(
                    json.dumps(
                        {
                            "kind": "connector.authorized_read",
                            "version": 1,
                            "sequence": 1,
                            "request": request,
                        }
                    )
                )
                try:
                    answer = await ws.recv()
                    observations.append("answer:" + str(answer))
                    reply = json.loads(answer)
                    assert reply["kind"] == "connector.read_result"
                    await ws.send(
                        json.dumps(
                            {
                                "kind": "connector.read_ack",
                                "version": 1,
                                "sequence": 1,
                                "requestId": READ,
                            }
                        )
                    )
                except ConnectionClosed:
                    observations.append("read_denied")
        except ConnectionClosed:
            # Expected only when the negative client deliberately closes.
            # Assertions and signature failures must fail the test, not disappear.
            return

    async with serve(peer, "127.0.0.1", 0, ssl=tls) as server:
        assert server.sockets
        port = server.sockets[0].getsockname()[1]
        origin = f"https://localhost:{port}"
        trust = ssl.create_default_context(cadata=pem)
        if mode == "untrusted-ca":
            trust = ssl.create_default_context()
        if mode == "wrong-host":
            origin = f"https://127.0.0.1:{port}"
        try:
            if mode in {"approved-read", "denied-operation", "revoked", "wrong-session"}:
                folder = tmp_path / "approved-project"
                folder.mkdir(exist_ok=True)
                (folder / "demo.kicad_pro").write_text("private contents")

                def local_dispatcher(receipt):
                    return LocalReadDispatch(
                        verified=VerifiedLocalBinding(
                            DEVICE,
                            PROJECT,
                            frozenset({"project_summary"}),
                            SESSION if mode != "wrong-session" else READ,
                            int(datetime.now(UTC).timestamp() * 1000) + 30_000,
                        ),
                        operator_project=OperatorProject(DEVICE, PROJECT, folder, "demo"),
                        current_authorization=lambda: mode != "revoked",
                    )

                # A pilot can exercise actual TLS/WSS without disabling the
                # stricter independent-authority reader. This is synthetic.
                if pilot:
                    receipt = await execute_operator_presence_once(
                        origin=origin,
                        trusted_origin=origin,
                        owner_sub=OWNER,
                        device_id=DEVICE,
                        signing_key=signing_key,
                        tls_context=trust,
                        dispatcher_factory=local_dispatcher,
                    )
                else:
                    with patch.object(
                        cloud_outbound_handshake,
                        "_require_independent_read_authority",
                        return_value=None,
                    ):
                        receipt = await execute_single_approved_read(
                            origin=origin,
                            trusted_origin=origin,
                            owner_sub=OWNER,
                            device_id=DEVICE,
                            signing_key=signing_key,
                            tls_context=trust,
                            dispatcher_factory=local_dispatcher,
                        )
            else:
                receipt = await establish_proof_only_handshake(
                    origin=origin,
                    trusted_origin=origin,
                    owner_sub=OWNER,
                    device_id=DEVICE,
                    signing_key=signing_key,
                    tls_context=trust,
                )
        except CloudHandshakeDeniedError:
            if mode == "success":
                raise
            observations.append("denied")
        else:
            assert mode in {"success", "approved-read"}, "a negative scenario was admitted"
            assert receipt.device_id == DEVICE
            assert receipt.session_id == SESSION

            if mode == "success":
                observations.append("completed")
    return observations


def test_secure_opt_in_real_wss_exchange(tmp_path: Path) -> None:
    assert asyncio.run(_scenario(tmp_path)) == [
        "hello",
        "device_verified",
        "session_verified",
        "completed",
    ]


@pytest.mark.parametrize(
    "mode",
    [
        "untrusted-ca",
        "wrong-host",
        "wrong-device",
        "premature-ready",
        "bad-ready",
        "binary-ready",
    ],
)
def test_security_denies_without_unsafe_fallback(tmp_path: Path, mode: str) -> None:
    got = asyncio.run(_scenario(tmp_path, mode))
    assert got[-1] == "denied"
    if mode in ("untrusted-ca", "wrong-host"):
        assert got == ["denied"], "TLS must verify before any secret-key signing"
    if mode in ("wrong-device", "premature-ready"):
        assert "device_verified" not in got


@pytest.mark.parametrize(
    "origin",
    [
        "http://localhost:443",
        "ws://localhost:443",
        "wss://localhost:443/api/v1/connector/ws",
        "https://example.com:443/not-allowed",
        "https://user@localhost:443",
        "https://localhost:443/?secret",
        "https://localhost:443/#fragment",
        "https://localhost:443",
    ],
)
def test_refuse_untrusted_or_malformed_origin_before_network(origin: str) -> None:
    _raise_argument_1 = establish_proof_only_handshake(
        origin=origin,
        trusted_origin="https://localhost:444",
        owner_sub=OWNER,
        device_id=DEVICE,
        signing_key=Ed25519PrivateKey.generate(),
    )
    with pytest.raises(CloudHandshakeDeniedError):
        asyncio.run(_raise_argument_1)


@pytest.mark.parametrize(
    "origin",
    [
        "https://localhost:443?",
        "https://localhost:443#",
        "https://localhost:443/?",
        "https://localhost:443/#",
    ],
)
def test_empty_query_or_fragment_delimiters_never_change_ws_path(origin: str) -> None:
    # urlsplit() reports an empty query/fragment; string concatenation then
    # misroutes /api/v1/connector/ws into a query or fragment on the wire.
    with pytest.raises(CloudHandshakeDeniedError):
        _endpoint(origin=origin, trusted_origin=origin)


@pytest.mark.parametrize(
    "origin",
    [
        "https://local\thost:443",
        "https://localhost:443\n",
        "https://localhost:443/\r",
        "https://localhost:443\x00",
        "\x1fhttps://localhost:443",
        "https://localhost:443\x7f",
        "https://caf\u00e9.example",
    ],
)
def test_url_parser_control_character_normalization_is_denied(origin: str) -> None:
    # urlsplit silently strips CR/LF/tab. The WSS endpoint must never be
    # assembled from those untrusted original bytes after parsing.
    with pytest.raises(CloudHandshakeDeniedError):
        _endpoint(origin=origin, trusted_origin=origin)


def test_no_trust_verification_optout_even_for_localhost() -> None:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    _raise_argument_2 = establish_proof_only_handshake(
        origin="https://localhost:445",
        trusted_origin="https://localhost:445",
        owner_sub=OWNER,
        device_id=DEVICE,
        signing_key=Ed25519PrivateKey.generate(),
        tls_context=context,
    )
    with pytest.raises(CloudHandshakeDeniedError):
        asyncio.run(_raise_argument_2)


@pytest.mark.parametrize(
    ("owner", "device"),
    [
        ("", DEVICE),
        ("  ", DEVICE),
        ("wrong-owner ", DEVICE),
        ("x" * 257, DEVICE),
        (OWNER, "bogus-device"),
        (OWNER, DEVICE.upper()),
    ],
)
def test_refuse_invalid_local_identity_before_network(owner: str, device: str) -> None:
    _raise_argument_3 = establish_proof_only_handshake(
        origin="https://localhost:445",
        trusted_origin="https://localhost:445",
        owner_sub=owner,
        device_id=device,
        signing_key=Ed25519PrivateKey.generate(),
    )
    with pytest.raises(CloudHandshakeDeniedError):
        asyncio.run(_raise_argument_3)


@pytest.mark.skipif(__import__("os").name != "posix", reason="POSIX no-follow required")
def test_operator_pilot_real_tls_presence_without_changing_strict_gate(tmp_path: Path) -> None:
    got = asyncio.run(_scenario(tmp_path, "approved-read", pilot=True))
    answer = next(item for item in got if item.startswith("answer:"))
    result = json.loads(answer.removeprefix("answer:"))
    assert result["result"]["files"] == {
        "projectPresent": True,
        "boardPresent": False,
        "schematicPresent": False,
    }
    assert "private contents" not in answer
    assert "approved-project" not in answer


@pytest.mark.skipif(__import__("os").name != "posix", reason="POSIX no-follow required")
@pytest.mark.parametrize("mode", ["denied-operation", "revoked", "wrong-session"])
def test_operator_pilot_denies_other_commands_or_expired_grants(tmp_path: Path, mode: str) -> None:
    got = asyncio.run(_scenario(tmp_path, mode, pilot=True))
    assert "read_denied" in got
    assert not any(item.startswith("answer:") for item in got)


@pytest.mark.skipif(__import__("os").name != "posix", reason="POSIX no-follow required")
def test_one_shot_tls_relay_delivers_only_owner_approved_presence(tmp_path: Path) -> None:
    got = asyncio.run(_scenario(tmp_path, "approved-read"))
    answer = next(item for item in got if item.startswith("answer:"))
    result = json.loads(answer.removeprefix("answer:"))
    assert result["kind"] == "connector.read_result"
    assert result["sequence"] == 1
    assert result["result"]["files"] == {
        "projectPresent": True,
        "boardPresent": False,
        "schematicPresent": False,
    }
    assert "private contents" not in answer
    assert "approved-project" not in answer


@pytest.mark.skipif(__import__("os").name != "posix", reason="POSIX no-follow required")
@pytest.mark.parametrize("mode", ["denied-operation", "revoked", "wrong-session"])
def test_one_shot_tls_relay_denies_native_revoked_or_unbound_request(
    tmp_path: Path, mode: str
) -> None:
    got = asyncio.run(_scenario(tmp_path, mode))
    assert "read_denied" in got
    assert not any(item.startswith("answer:") for item in got)
