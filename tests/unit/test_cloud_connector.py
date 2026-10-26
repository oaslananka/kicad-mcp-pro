from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from kicad_mcp.cloud_connector import (
    CloudConnectorError,
    CloudIdentity,
    _first_proof,
    _second_proof,
    load_private_key,
    perform_handshake,
    validate_wss_endpoint,
)


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


class FakeSocket:
    def __init__(self, replies: list[object]) -> None:
        self.replies = replies
        self.sent: list[dict[str, object]] = []

    async def send(self, message: str) -> None:
        self.sent.append(json.loads(message))

    async def recv(self) -> str | bytes:
        if not self.replies:
            raise AssertionError("unexpected frame")
        reply = self.replies.pop(0)
        return reply if isinstance(reply, (str, bytes)) else json.dumps(reply)


def ids() -> CloudIdentity:
    return CloudIdentity("trusted-owner", str(uuid4()))


def challenge(identity: CloudIdentity) -> tuple[dict[str, object], dict[str, object]]:
    import time

    now = int(time.time() * 1000)
    return (
        {
            "kind": "device.challenge",
            "version": 1,
            "challengeId": str(uuid4()),
            "deviceId": identity.device_id,
            "nonce": b64(os.urandom(32)),
            "expiresAtMs": now + 48_000,
        },
        {
            "kind": "connector.session_challenge",
            "version": 1,
            "sessionId": str(uuid4()),
            "challengeId": str(uuid4()),
            "deviceId": identity.device_id,
            "nonce": b64(os.urandom(32)),
            "binding": b64(os.urandom(32)),
            "expiresAtMs": now + 47_000,
        },
    )


@pytest.mark.asyncio
async def test_two_proofs_bind_exact_device_session_nonce_and_connection() -> None:
    ident = ids()
    first, second = challenge(ident)
    key = Ed25519PrivateKey.generate()
    socket = FakeSocket([first, second, {"kind": "connector.ready", "version": 1}])
    await perform_handshake(socket, ident, key)
    assert [f["kind"] for f in socket.sent] == [
        "device.hello",
        "device.proof",
        "connector.session_proof",
    ]
    assert socket.sent[0]["ownerSub"] == ident.owner_sub
    signature1 = base64.urlsafe_b64decode(str(socket.sent[1]["signature"]) + "==")
    key.public_key().verify(
        signature1, _first_proof(str(first["challengeId"]), ident.device_id, str(first["nonce"]))
    )
    signature2 = base64.urlsafe_b64decode(str(socket.sent[2]["signature"]) + "==")
    key.public_key().verify(
        signature2,
        _second_proof(
            str(second["sessionId"]),
            str(second["challengeId"]),
            ident.device_id,
            str(second["nonce"]),
            str(second["binding"]),
        ),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["wrong-device", "extra-field", "expired", "binary"])
async def test_bad_challenge_never_receives_device_proof(change: str) -> None:
    ident = ids()
    first, second = challenge(ident)
    if change == "wrong-device":
        first["deviceId"] = str(uuid4())
    if change == "extra-field":
        first["projectPath"] = "private_board.kicad_pcb"
    if change == "expired":
        first["expiresAtMs"] = 0
    socket = FakeSocket([b"binary" if change == "binary" else first, second])
    with pytest.raises(CloudConnectorError):
        await perform_handshake(socket, ident, Ed25519PrivateKey.generate())
    assert [f["kind"] for f in socket.sent] == ["device.hello"]


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["wrong-device", "invalid-binding", "extra-field"])
async def test_bad_session_challenge_never_receives_session_proof(change: str) -> None:
    ident = ids()
    first, second = challenge(ident)
    if change == "wrong-device":
        second["deviceId"] = str(uuid4())
    if change == "invalid-binding":
        second["binding"] = "not-base64"
    if change == "extra-field":
        second["operation"] = "run_drc"
    socket = FakeSocket([first, second])
    with pytest.raises(CloudConnectorError):
        await perform_handshake(socket, ident, Ed25519PrivateKey.generate())
    assert [f["kind"] for f in socket.sent] == ["device.hello", "device.proof"]


@pytest.mark.parametrize(
    "url",
    [
        "".join(("w", "s", ":", "/", "/")) + "cloud.example/api/v1/connector/ws",
        "https://cloud.example/api/v1/connector/ws",
        "wss://user:token@cloud.example/api/v1/connector/ws",
        "wss://cloud.example/api/v1/connector/ws?device=bad",
        "wss://cloud.example/api/v1/connector/ws#bad",
        "wss://cloud.example/",
        "wss://cloud.example/api/v1/connector/ws ",
    ],
)
def test_unsafe_endpoints_denied(url: str) -> None:
    with pytest.raises(CloudConnectorError):
        validate_wss_endpoint(url)


def test_valid_wss_endpoint() -> None:
    endpoint = "wss://cloud.example/api/v1/connector/ws"
    assert validate_wss_endpoint(endpoint) == endpoint


def test_key_file_rejects_public_permissions_and_symlinks(tmp_path: Path) -> None:
    key = Ed25519PrivateKey.generate()
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    path = tmp_path / "device.pem"
    path.write_bytes(pem)
    path.chmod(0o600)
    assert isinstance(load_private_key(path), Ed25519PrivateKey)
    path.chmod(0o644)
    with pytest.raises(CloudConnectorError):
        load_private_key(path)
    path.chmod(0o600)
    link = tmp_path / "symlink.pem"
    link.symlink_to(path)
    with pytest.raises(CloudConnectorError):
        load_private_key(link)


def test_cannot_claim_arbitrary_device_identity() -> None:
    with pytest.raises(CloudConnectorError):
        CloudIdentity("owner", "not-a-uuid")


@pytest.mark.asyncio
async def test_duplicate_json_identity_never_receives_a_signature() -> None:
    ident = ids()
    first, _ = challenge(ident)
    frame = json.dumps(first)
    frame = frame.replace('"deviceId": ', '"deviceId": "spoofed", "deviceId": ', 1)
    socket = FakeSocket([frame])
    with pytest.raises(CloudConnectorError):
        await perform_handshake(socket, ident, Ed25519PrivateKey.generate())
    assert [item["kind"] for item in socket.sent] == ["device.hello"]
