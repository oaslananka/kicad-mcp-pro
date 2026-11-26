"""Interrupted first setup must never create an unrelated second device."""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
from types import SimpleNamespace
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives.serialization import load_der_public_key

from kicad_mcp import cloud_pair, cloud_windows_binding, cloud_windows_device_bootstrap
from kicad_mcp.cloud_windows_write_issuer import _KICAD_CLOUD_ORIGIN as ORIGIN


@pytest.mark.parametrize("stage", ["key", "challenge", "approval", "redeem", "binding", "selected"])
def test_windows_initial_restart(monkeypatch, stage) -> None:
    from kicad_mcp import cloud_windows_enrollment as enrollment
    from kicad_mcp import cloud_windows_initial_enrollment as initial

    boot = cloud_windows_device_bootstrap
    store = {}
    state = {"interrupt": True, "approved": False}
    issued, approved, redeemed = [], [], []
    challenge, device = str(uuid4()), str(uuid4())
    secret = secrets.token_urlsafe(32)

    def interrupt(at: str) -> None:
        if stage == at and state["interrupt"]:
            state["interrupt"] = False
            raise KeyboardInterrupt

    def read(slot, part):
        return store.get((slot, part))

    def create(slot, part, data) -> None:
        assert (slot, part) not in store
        store[slot, part] = data
        interrupt(part)

    def delete(slot, part) -> bool:
        return store.pop((slot, part), None) is not None

    for module in (initial, boot, enrollment):
        monkeypatch.setattr(module, "read_credential", read)
        monkeypatch.setattr(module, "create_credential", create)
    monkeypatch.setattr(initial, "delete_credential", delete)
    monkeypatch.setattr(cloud_windows_binding, "read_credential", read)
    for module in (boot, enrollment, cloud_windows_binding):
        monkeypatch.setattr(module, "os", SimpleNamespace(name="nt"))

    def post(target, endpoint, payload, status):
        assert target[2] == ORIGIN
        if endpoint.endswith("/challenge"):
            public = base64.b64decode(payload["publicKeyDer"])
            issued.append(public)
            state["public"] = load_der_public_key(public)
            state["fingerprint"] = hashlib.sha256(public).hexdigest()
            interrupt("challenge")
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
        assert payload["resumeInitial"] is True
        state["public"].verify(
            base64.urlsafe_b64decode(payload["signature"] + "=="),
            b"kicad-cloud-pairing-initial-v1\0" + challenge.encode() + b"\0" + secret.encode(),
        )
        redeemed.append(payload.copy())
        interrupt("redeem")
        return {
            "deviceId": device,
            "ownerSub": "owner",
            "deviceFingerprint": state["fingerprint"],
            "enabled": True,
        }

    def approve(*_args: object) -> None:
        approved.append(True)
        state["approved"] = True
        interrupt("approval")

    monkeypatch.setattr(cloud_pair, "_post", post)
    monkeypatch.setattr(cloud_pair.time, "sleep", lambda _: None)
    with pytest.raises(KeyboardInterrupt):
        initial.ensure_device(ORIGIN, "PC", approve)
    result = initial.ensure_device(ORIGIN, "PC", approve)
    assert result.device_id == device and boot.selected_device() == result
    assert initial.ensure_device(ORIGIN, "PC", approve) == result
    assert approved == [True] and len(set(issued)) == 1
    assert len(redeemed) == (2 if stage == "redeem" else 1)
    assert all(payload == redeemed[0] for payload in redeemed)
    assert {part for _, part in store} == {"key", "binding", "selected"}


@pytest.mark.parametrize("variant", ["foreign", "reserved", "malformed", "missing-key"])
def test_invalid_initial_journal_never_issues_challenge(monkeypatch, variant) -> None:
    from kicad_mcp import cloud_windows_enrollment as enrollment
    from kicad_mcp import cloud_windows_initial_enrollment as initial

    slot = uuid4().hex
    pointer = {"origin": ORIGIN, "recordId": slot}
    if variant == "foreign":
        pointer["origin"] = "https://other.example"
    elif variant == "reserved":
        pointer["recordId"] = "2" * 32
    elif variant == "malformed":
        pointer["unexpected"] = "value"
    store = {(initial._DEVICE_SELECTION_SLOT, initial._POINTER): json.dumps(pointer).encode()}
    if variant == "missing-key":
        store[slot, initial._CHALLENGE] = b"{}"
    original = store.copy()
    monkeypatch.setattr(enrollment, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(initial, "selected_device", lambda: None)
    monkeypatch.setattr(initial, "read_credential", lambda slot, part: store.get((slot, part)))
    monkeypatch.setattr(
        initial, "create_credential", lambda *_: pytest.fail("unexpected vault write")
    )
    monkeypatch.setattr(
        initial, "delete_credential", lambda *_: pytest.fail("unexpected vault deletion")
    )
    monkeypatch.setattr(cloud_pair, "_post", lambda *_: pytest.fail("unexpected pairing request"))
    with pytest.raises(enrollment.WindowsEnrollmentError):
        initial.ensure_device(ORIGIN, "PC", lambda *_: pytest.fail("unexpected browser"))
    assert store == original
