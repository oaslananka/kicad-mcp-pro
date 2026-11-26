"""An initial device-only enrollment must resume the same approved operation."""

from __future__ import annotations

import base64
import hashlib
import os
import secrets
import time
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives.serialization import load_der_public_key

from kicad_mcp import cloud_pair
from kicad_mcp import cloud_posix_device_bootstrap as boot
from kicad_mcp.cloud_windows_write_issuer import _KICAD_CLOUD_ORIGIN as ORIGIN

pytestmark = pytest.mark.skipif(os.name != "posix", reason="POSIX owner-private registry")


@pytest.mark.parametrize("interruption", ["challenge", "approval", "redeem", "binding"])
def test_initial_pairing_resumes_without_duplicate_device(
    tmp_path, monkeypatch, interruption
) -> None:
    from kicad_mcp import cloud_pair_keys

    root = tmp_path / "registry"
    root.mkdir(mode=0o700)
    challenge = str(uuid4())
    device = str(uuid4())
    secret = secrets.token_urlsafe(32)
    state = {"approved": False, "interrupt": True, "public": None, "fingerprint": None}
    calls = []
    reviews = []
    issued = []

    def post(target, endpoint, payload, status):
        assert target[2] == ORIGIN
        if endpoint.endswith("/challenge"):
            public = base64.b64decode(payload["publicKeyDer"])
            issued.append(public)
            state["public"] = load_der_public_key(public)
            state["fingerprint"] = hashlib.sha256(public).hexdigest()
            if interruption == "challenge" and state["interrupt"]:
                state["interrupt"] = False
                raise KeyboardInterrupt
            return {
                "challengeId": challenge,
                "deviceCode": secret,
                "userCode": "ABC123-DEF456",
                "deviceFingerprint": state["fingerprint"],
                "expiresAtMs": time.time_ns() // 1_000_000 + 299_000,
            }
        assert payload["challengeId"] == challenge and payload["deviceCode"] == secret
        if endpoint.endswith("/status"):
            return {"approved": state["approved"]}
        assert endpoint.endswith("/redeem") and state["approved"]
        assert payload["resumeInitial"] is True and payload["connectOnApproval"] is True
        state["public"].verify(
            base64.urlsafe_b64decode(payload["signature"] + "=="),
            b"kicad-cloud-pairing-initial-v1\0" + challenge.encode() + b"\0" + secret.encode(),
        )
        calls.append(payload.copy())
        if interruption == "redeem" and state["interrupt"]:
            state["interrupt"] = False
            raise KeyboardInterrupt
        return {
            "deviceId": device,
            "ownerSub": "owner",
            "deviceFingerprint": state["fingerprint"],
            "enabled": True,
        }

    def approve(*_args: object) -> None:
        reviews.append("browser")
        state["approved"] = True
        if interruption == "approval" and state["interrupt"]:
            state["interrupt"] = False
            raise KeyboardInterrupt

    original = cloud_pair_keys._save_owner_binding

    def save(*args: object, **kwargs: object) -> None:
        original(*args, **kwargs)
        if interruption == "binding" and state["interrupt"]:
            state["interrupt"] = False
            raise KeyboardInterrupt

    monkeypatch.setattr(cloud_pair, "_post", post)
    monkeypatch.setattr(cloud_pair.time, "sleep", lambda _: None)
    monkeypatch.setattr(cloud_pair_keys, "_save_owner_binding", save)
    with pytest.raises(KeyboardInterrupt):
        boot.ensure_device(root, ORIGIN, "PC", approve)
    result = boot.ensure_device(root, ORIGIN, "PC", approve)
    assert result[1]["deviceId"] == device
    assert reviews == ["browser"]
    assert len(set(issued)) == 1
    assert len(calls) == (2 if interruption == "redeem" else 1)
    if len(calls) == 2:
        assert calls[0] == calls[1]
    assert not (root / "projects").exists()
    assert boot.ensure_device(root, ORIGIN, "PC", approve) == result
