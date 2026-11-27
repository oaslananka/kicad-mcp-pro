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


@pytest.mark.parametrize("interruption", ["challenge", "approval", "redeem", "binding", "refused"])
def test_initial_pairing_resumes_without_duplicate_device(
    tmp_path, monkeypatch, interruption
) -> None:
    from kicad_mcp import cloud_pair_keys
    from kicad_mcp.cloud_windows_enrollment import InitialEnrollmentDeniedError

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
        nonlocal challenge, secret
        assert target[2] == ORIGIN
        if endpoint.endswith("/challenge"):
            public = base64.b64decode(payload["publicKeyDer"])
            if interruption == "refused" and issued:
                challenge, secret = str(uuid4()), secrets.token_urlsafe(32)
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
        assert payload["challengeId"] == challenge
        assert payload["deviceCode"] == secret
        if endpoint.endswith("/status"):
            return {"approved": state["approved"]}
        assert endpoint.endswith("/redeem")
        assert state["approved"]
        assert payload["resumeInitial"] is True
        assert payload["connectOnApproval"] is True
        state["public"].verify(
            base64.urlsafe_b64decode(payload["signature"] + "=="),
            b"kicad-cloud-pairing-initial-v1\0" + challenge.encode() + b"\0" + secret.encode(),
        )
        calls.append(payload.copy())
        if interruption == "refused" and len(calls) == 1:
            state["approved"] = False
            return {"initialDenied": True}
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
    with pytest.raises(
        InitialEnrollmentDeniedError if interruption == "refused" else KeyboardInterrupt
    ):
        boot.ensure_device(root, ORIGIN, "PC", approve)
    result = boot.ensure_device(root, ORIGIN, "PC", approve)
    assert result[1]["deviceId"] == device
    assert reviews == ["browser"] * (2 if interruption == "refused" else 1)
    assert len(set(issued)) == 1
    assert len(calls) == (2 if interruption in {"redeem", "refused"} else 1)
    if interruption == "refused":
        assert calls[0]["challengeId"] != calls[1]["challengeId"]
    elif len(calls) == 2:
        assert calls[0] == calls[1]
    assert not (root / "projects").exists()
    assert boot.ensure_device(root, ORIGIN, "PC", approve) == result


@pytest.mark.parametrize(
    "fault",
    [
        "orphan-key",
        "foreign-origin",
        "foreign-key",
        "missing-key",
        "missing-challenge",
        "binding-too-early",
    ],
)
def test_initial_enrollment_refuses_inconsistent_private_journal(
    tmp_path, monkeypatch, fault
) -> None:
    from kicad_mcp import cloud_pair_keys
    from kicad_mcp import cloud_posix_initial_enrollment as initial

    root = tmp_path / "registry"
    root.mkdir(mode=0o700)
    keys = root / "keys"
    keys.mkdir(mode=0o700)
    slot = str(uuid4())
    keyfile = keys / (slot + ".pem")
    if fault != "orphan-key":
        cloud_pair_keys._write_private_json(
            root,
            initial.JOURNAL,
            {
                "origin": "https://other.example" if fault == "foreign-origin" else ORIGIN,
                "slot": slot,
                "phase": "redeem" if fault in {"missing-key", "missing-challenge"} else "waiting",
            },
        )
    if fault != "missing-key":
        cloud_pair._load_or_create(keyfile)
    if fault == "foreign-key":
        cloud_pair._load_or_create(keys / (str(uuid4()) + ".pem"))
    if fault == "binding-too-early":
        cloud_pair_keys._write_private_json(
            keys, keyfile.name + cloud_pair_keys._BINDING_SUFFIX, {}
        )
    before = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    monkeypatch.setattr(cloud_pair, "_post", lambda *_: pytest.fail("unexpected network"))
    with pytest.raises(ValueError):
        initial.enroll_initial(root, ORIGIN, "PC", lambda *_: pytest.fail("unexpected approval"))
    assert {
        str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()
    } == before
