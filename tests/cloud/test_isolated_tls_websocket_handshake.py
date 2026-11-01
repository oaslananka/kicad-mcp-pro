"""Isolated localhost TLS/WebSocket integration fixture for Cloud v1 signatures.

This is NOT an installed connector or production client. Server certificate,
TLS key and device key are ephemeral and synthetic. No internet, production
Cloud, production DB or real KiCad project is contacted.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import ssl
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.x509.oid import NameOID
from websockets.asyncio.client import connect
from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed

from kicad_mcp.cloud_device_proofs import (
    OfflineProofDeniedError,
    sign_device_challenge,
    sign_session_challenge,
)

DEVICE = "11111111-1111-4111-8111-111111111111"
FOREIGN_DEVICE = "22222222-2222-4222-8222-222222222222"
CHALLENGE = "33333333-3333-4333-8333-333333333333"
SESSION = "44444444-4444-4444-8444-444444444444"
SESSION_CHALLENGE = "55555555-5555-4555-8555-555555555555"
NONCE = base64.urlsafe_b64encode(bytes(range(32))).decode().rstrip("=")
BINDING = base64.urlsafe_b64encode(bytes(range(32, 64))).decode().rstrip("=")
OWNER = "synthetic-owner"


def _synthetic_tls(tmp_path: Path) -> tuple[ssl.SSLContext, str]:
    """Create an ephemeral, name-bound synthetic server root/leaf for localhost."""
    signing_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(signing_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(hours=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False)
        .sign(signing_key, hashes.SHA256())
    )
    pem = cert.public_bytes(serialization.Encoding.PEM)
    key_file = tmp_path / "temporary-test-server.key"
    cert_file = tmp_path / "temporary-test-server.crt"
    key_file.write_bytes(
        signing_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    os.chmod(key_file, 0o600)
    cert_file.write_bytes(pem)
    server_tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_tls.load_cert_chain(certfile=cert_file, keyfile=key_file)
    return server_tls, pem.decode("ascii")


def _decode_sig(frame: dict[str, object]) -> bytes:
    signature = frame["signature"]
    assert isinstance(signature, str)
    assert len(signature) == 86

    return base64.urlsafe_b64decode(signature + "==")


async def _verified_local_test_handshake(
    url: str, trust_pem: str, test_signer: Ed25519PrivateKey
) -> None:
    """Strictly test TLS-to-proof ordering; no production integration."""
    address = urlsplit(url)
    if (
        address.scheme != "wss"
        or address.hostname not in {"localhost", "127.0.0.1"}
        or address.username
        or address.password
        or address.query
        or address.fragment
        or address.path != "/api/v1/connector/ws"
    ):
        raise OfflineProofDeniedError("test-only destination denied")
    # TLS trust comes from the local test fixture, never from WS JSON.
    tls = ssl.create_default_context(cadata=trust_pem)
    assert tls.verify_mode == ssl.CERT_REQUIRED
    assert tls.check_hostname

    async with asyncio.timeout(5):
        async with connect(
            url, ssl=tls, origin=None, compression=None, max_size=1024, open_timeout=3
        ) as socket:
            assert socket.transport.get_extra_info("ssl_object") is not None
            await socket.send(
                json.dumps(
                    {
                        "kind": "device.hello",
                        "version": 1,
                        "ownerSub": OWNER,
                        "deviceId": DEVICE,
                    }
                )
            )
            first = await socket.recv()
            if not isinstance(first, str):
                raise OfflineProofDeniedError("binary challenge denied")
            reply = sign_device_challenge(
                first.encode(),
                expected_device_id=DEVICE,
                now_unix_ms=int(datetime.now(UTC).timestamp() * 1000),
                signing_key=test_signer,
            )
            await socket.send(json.dumps(reply))
            second = await socket.recv()
            if not isinstance(second, str):
                raise OfflineProofDeniedError("binary challenge denied")
            reply = sign_session_challenge(
                second.encode(),
                expected_device_id=DEVICE,
                now_unix_ms=int(datetime.now(UTC).timestamp() * 1000),
                signing_key=test_signer,
            )
            await socket.send(json.dumps(reply))
            ready = await socket.recv()
            if not isinstance(ready, str) or json.loads(ready) != {
                "kind": "connector.ready",
                "version": 1,
            }:
                raise OfflineProofDeniedError("unexpected ready frame")
            # No read requests or native KiCad operations are sent or accepted.


async def _scenario(tmp_path: Path, mode: str) -> list[str]:
    tls, pem = _synthetic_tls(tmp_path)
    test_signer = Ed25519PrivateKey.generate()
    accepted_key = test_signer.public_key()
    observations: list[str] = []

    async def fake_cloud(ws: ServerConnection) -> None:
        # Host-side fake Cloud server with byte-exact Cloud v1 verification.
        try:
            hello = json.loads(await ws.recv())
            assert hello == {
                "kind": "device.hello",
                "version": 1,
                "ownerSub": OWNER,
                "deviceId": DEVICE,
            }
            observations.append("hello")
            if mode == "wrong-phase":
                await ws.send('{"kind":"connector.ready","version":1}')
                return
            device = FOREIGN_DEVICE if mode == "wrong-device" else DEVICE
            expiry = int(datetime.now(UTC).timestamp() * 1000) + 35_000
            await ws.send(
                json.dumps(
                    {
                        "kind": "device.challenge",
                        "version": 1,
                        "challengeId": CHALLENGE,
                        "deviceId": device,
                        "nonce": NONCE,
                        "expiresAtMs": expiry,
                    }
                )
            )
            response = json.loads(await ws.recv())
            assert response["kind"] == "device.proof"
            payload = (
                b"kicad-cloud-device-handshake-v1\0"
                + CHALLENGE.encode()
                + b"\0"
                + DEVICE.encode()
                + b"\0"
                + NONCE.encode()
            )
            accepted_key.verify(_decode_sig(response), payload)
            observations.append("device-proof")
            await ws.send(
                json.dumps(
                    {
                        "kind": "connector.session_challenge",
                        "version": 1,
                        "sessionId": SESSION,
                        "challengeId": SESSION_CHALLENGE,
                        "deviceId": DEVICE,
                        "nonce": NONCE,
                        "binding": BINDING,
                        "expiresAtMs": expiry,
                    }
                )
            )
            response = json.loads(await ws.recv())
            payload = (
                b"kicad-cloud-bound-session-v1\0"
                + SESSION.encode()
                + b"\0"
                + SESSION_CHALLENGE.encode()
                + b"\0"
                + DEVICE.encode()
                + b"\0"
                + NONCE.encode()
                + b"\0"
                + BINDING.encode()
            )
            accepted_key.verify(_decode_sig(response), payload)
            observations.append("session-proof")
            if mode == "wrong-ready":
                await ws.send('{"kind":"connector.ready","version":2}')
            else:
                await ws.send('{"kind":"connector.ready","version":1}')
        except ConnectionClosed:
            # Aborts are expected; assertion failures must remain visible.
            return

    async with serve(
        fake_cloud, "127.0.0.1", 0, ssl=tls, compression=None, max_size=1024
    ) as server:
        assert server.sockets
        port = server.sockets[0].getsockname()[1]
        endpoint_host = "127.0.0.1" if mode == "bad-hostname" else "localhost"
        url = f"wss://{endpoint_host}:{port}/api/v1/connector/ws"
        if mode == "untrusted-cert":
            _, pem = _synthetic_tls(tmp_path / "independent-ca")
        try:
            await _verified_local_test_handshake(url, pem, test_signer)
        except (ssl.SSLError, OSError, OfflineProofDeniedError, ConnectionClosed) as error:
            if mode == "success":
                raise
            observations.append(f"blocked:{type(error).__name__}")
        else:
            if mode != "success":
                raise AssertionError("negative TLS/WS challenge was incorrectly allowed")
    return observations


def test_local_tls_and_both_real_signature_roundtrips(tmp_path: Path) -> None:
    result = asyncio.run(_scenario(tmp_path, "success"))
    assert result == ["hello", "device-proof", "session-proof"]


@pytest.mark.parametrize(
    "mode", ["untrusted-cert", "bad-hostname", "wrong-device", "wrong-phase", "wrong-ready"]
)
def test_fail_closed_tls_identity_and_challenge_sequence(tmp_path: Path, mode: str) -> None:
    if mode == "untrusted-cert":
        (tmp_path / "independent-ca").mkdir()
    result = asyncio.run(_scenario(tmp_path, mode))
    assert result[-1].startswith("blocked:")
    if mode in {"untrusted-cert", "bad-hostname"}:
        assert result == [result[-1]], "no application handshake before verified TLS"
    elif mode in {"wrong-device", "wrong-phase"}:
        assert "device-proof" not in result
    elif mode == "wrong-ready":
        assert result[:3] == ["hello", "device-proof", "session-proof"]


@pytest.mark.parametrize(
    "url",
    [
        "ws://localhost:443/api/v1/connector/ws",
        "wss://example.com:443/api/v1/connector/ws",
        "wss://localhost:443/not-connector",
        "wss://user@localhost:443/api/v1/connector/ws",
        "wss://localhost:443/api/v1/connector/ws?from=untrusted",
        "wss://localhost:443/api/v1/connector/ws#untrusted",
    ],
)
def test_test_harness_cannot_connect_to_external_cloud_or_other_paths(url: str) -> None:
    # Rejected before DNS, TCP, TLS, or any device signature is attempted.
    _raise_argument_1 = _verified_local_test_handshake(url, "", Ed25519PrivateKey.generate())
    with pytest.raises(OfflineProofDeniedError):
        asyncio.run(_raise_argument_1)
