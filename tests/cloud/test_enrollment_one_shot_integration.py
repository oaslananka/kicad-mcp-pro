"""End-to-end *local* pairing-to-read contract with synthetic Cloud transport.

Only test-owned keys and files are used. Browser consent and both network
requests are simulated, so this does not prove real OAuth or production TLS.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import time
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from kicad_mcp import cloud_once, cloud_pair
from kicad_mcp.cloud_outbound_handshake import HandshakeReceipt
from kicad_mcp.cloud_readonly_boundary import LocalReadDeniedError

pytestmark = pytest.mark.skipif(os.name != "posix", reason="Owner-only key binding is POSIX only")

ORIGIN = "https://cloud.example"
OWNER = "synthetic-owner"
DEVICE = "11111111-1111-4111-8111-111111111111"
PROJECT = "22222222-2222-4222-8222-222222222222"
SESSION = "33333333-3333-4333-8333-333333333333"
REQUEST = "44444444-4444-4444-8444-444444444444"
CHALLENGE = "55555555-5555-4555-8555-555555555555"
DEVICE_SECRET = base64.urlsafe_b64encode(bytes(range(32))).decode().rstrip("=")


def test_browser_paired_identity_completes_only_one_local_project_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    private_key_path = tmp_path / "owner.pem"
    selected_project = tmp_path / "chosen-project"
    selected_project.mkdir()
    (selected_project / "board.kicad_pro").touch()
    events: list[str] = []
    enrolled_fingerprint = ""

    def synthetic_pairing_http(
        origin: tuple[str, int, str], path: str, body: dict[str, object], expected_status: int
    ) -> dict[str, object]:
        nonlocal enrolled_fingerprint
        assert origin == ("cloud.example", 443, ORIGIN)
        if path.endswith("/challenge"):
            assert expected_status == 201
            der = base64.b64decode(str(body["publicKeyDer"]), validate=True)
            enrolled_fingerprint = hashlib.sha256(der).hexdigest()
            events.append("challenge")
            return {
                "challengeId": CHALLENGE,
                "userCode": "ABCDEF-123456",
                "deviceCode": DEVICE_SECRET,
                "deviceFingerprint": enrolled_fingerprint,
                "expiresAtMs": time.time_ns() // 1_000_000 + 60_000,
            }
        if path.endswith("/status"):
            assert expected_status == 200
            assert events == ["challenge", "owner-consented"]
            proof = (
                b"kicad-cloud-pairing-status-v1\0"
                + CHALLENGE.encode()
                + b"\0"
                + DEVICE_SECRET.encode()
            )
            signed = base64.urlsafe_b64decode(str(body["signature"]) + "==")
            cloud_once._load_owner_key(private_key_path).public_key().verify(signed, proof)
            events.append("approval-status-verified")
            return {"approved": True}
        assert path.endswith("/redeem")
        assert expected_status == 200
        assert events == ["challenge", "owner-consented", "approval-status-verified"]
        assert body["challengeId"] == CHALLENGE
        assert body["deviceCode"] == DEVICE_SECRET
        proof = (
            b"kicad-cloud-pairing-proof-v1\0" + CHALLENGE.encode() + b"\0" + DEVICE_SECRET.encode()
        )
        signature = base64.urlsafe_b64decode(str(body["signature"]) + "==")
        cloud_once._load_owner_key(private_key_path).public_key().verify(signature, proof)
        events.append("redeemed")
        return {
            "deviceId": DEVICE,
            "deviceFingerprint": enrolled_fingerprint,
            "enabled": False,
        }

    def simulated_browser_approval(page: str, challenge: str, code: str) -> None:
        assert page == ORIGIN + "/devices/pairing"
        assert challenge == CHALLENGE
        assert code == "ABCDEF-123456"
        events.append("owner-consented")

    monkeypatch.setattr(cloud_pair, "_post", synthetic_pairing_http)
    device, fingerprint = cloud_pair.enroll(
        ORIGIN, "Test Fixture", private_key_path, simulated_browser_approval
    )
    assert device == DEVICE
    assert fingerprint == enrolled_fingerprint
    assert events == ["challenge", "owner-consented", "approval-status-verified", "redeemed"]

    binding = cloud_once._read_owner_binding(private_key_path)
    assert binding == {"origin": ORIGIN, "deviceId": DEVICE, "fingerprint": fingerprint}
    assert private_key_path.stat().st_mode & 0o777 == 0o600

    async def synthetic_one_shot_transport(**kwargs: object) -> HandshakeReceipt:
        assert kwargs["origin"] == ORIGIN
        assert kwargs["trusted_origin"] == ORIGIN
        assert kwargs["owner_sub"] == OWNER
        assert kwargs["device_id"] == DEVICE
        key = kwargs["signing_key"]
        der = key.public_key().public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
        assert hashlib.sha256(der).hexdigest() == fingerprint
        factory = kwargs["dispatcher_factory"]
        assert callable(factory)
        dispatcher = factory(HandshakeReceipt(DEVICE, SESSION))
        try:
            request = json.dumps(
                {
                    "kind": "connector.read_request",
                    "version": 1,
                    "deviceId": DEVICE,
                    "projectId": PROJECT,
                    "requestId": REQUEST,
                    "operation": "project_summary",
                    "deadlineUnixMs": time.time_ns() // 1_000_000 + 1000,
                }
            ).encode()
            summary = dispatcher.read(request, sequence=1)
            assert summary["files"] == {
                "projectPresent": True,
                "boardPresent": False,
                "schematicPresent": False,
            }
            with pytest.raises(LocalReadDeniedError):
                dispatcher.read(request, sequence=2)
        finally:
            dispatcher.close()
        events.append("one-local-summary")
        return HandshakeReceipt(DEVICE, SESSION)

    monkeypatch.setattr(cloud_once, "execute_single_approved_read", synthetic_one_shot_transport)
    monkeypatch.setattr(cloud_once.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(cloud_once.sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(cloud_once.secrets, "token_hex", lambda _: "cafebabe")
    monkeypatch.setattr("builtins.input", lambda *_: "APPROVE CAFEBABE")
    from kicad_mcp import cloud_local_registry

    monkeypatch.setattr(
        cloud_local_registry,
        "resolve_registered_read",
        lambda **_: cloud_local_registry.LocalRegisteredRead(
            private_key_path, selected_project, "board"
        ),
    )
    options = [
        "--cloud-origin",
        ORIGIN,
        "--owner-sub",
        OWNER,
        "--device-id",
        DEVICE,
        "--project-id",
        PROJECT,
        "--allow-once",
    ]
    assert cloud_once.main(options) == 0
    assert events == [
        "challenge",
        "owner-consented",
        "approval-status-verified",
        "redeemed",
        "one-local-summary",
    ]
