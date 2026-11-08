"""Offline Windows device-pairing acceptance; never touch a real owner vault/Cloud."""

from __future__ import annotations

import base64
import hashlib
import json
import time
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import load_der_public_key

from kicad_mcp import (
    cloud_pair,
    cloud_windows_binding,
    cloud_windows_enrollment,
    cloud_windows_project_record,
)
from kicad_mcp.cloud_pair_keys import LocalApprovalDeniedError

ORIGIN = "https://cloud.example"
DEVICE = "19ee4be9-0aec-448e-9873-721ae113ec02"
OWNER = "provider|owner-42"
SECRET = "A" * 43
CHALLENGE = "29ee4be9-0aec-448e-9873-721ae113ec02"
CODE = "ABCDEF-123456"


@pytest.fixture
def fake_windows_pair(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[dict[tuple[str, str], bytes], list[str], dict[str, Any]]:
    store: dict[tuple[str, str], bytes] = {}
    events: list[str] = []
    state: dict[str, Any] = {"approved": False, "fingerprint": None, "public": None}
    monkeypatch.setattr(cloud_windows_enrollment, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(cloud_windows_binding, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(cloud_windows_project_record, "os", SimpleNamespace(name="nt"))

    def create(record_id: str, part: str, data: bytes) -> None:
        assert len(record_id) == 32
        assert (record_id, part) not in store
        store[(record_id, part)] = data
        events.append("vault:" + part)

    def read(record_id: str, part: str) -> bytes | None:
        return store.get((record_id, part))

    def delete(record_id: str, part: str) -> bool:
        events.append("delete:" + part)
        return store.pop((record_id, part), None) is not None

    monkeypatch.setattr(cloud_windows_enrollment, "create_credential", create)
    monkeypatch.setattr(cloud_windows_enrollment, "read_credential", read)
    monkeypatch.setattr(cloud_windows_enrollment, "delete_credential", delete)
    monkeypatch.setattr(cloud_windows_binding, "read_credential", read)
    monkeypatch.setattr(cloud_windows_project_record, "read_credential", read)
    monkeypatch.setattr(cloud_pair.time, "sleep", lambda _duration: None)

    def check_signature(body: dict[str, object], prefix: bytes) -> None:
        public = state["public"]
        assert public is not None
        encoded = body["signature"]
        assert isinstance(encoded, str)
        signature = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        public.verify(
            signature,
            prefix + CHALLENGE.encode("ascii") + b"\x00" + SECRET.encode("ascii"),
        )

    def response(
        target: tuple[str, int, str],
        path: str,
        body: dict[str, object],
        status: int,
    ) -> dict[str, object]:
        assert target == ("cloud.example", 443, ORIGIN)
        if path.endswith("/challenge"):
            events.append("challenge")
            assert status == 201
            assert body["alias"] == "Lab PC"
            encoded = body["publicKeyDer"]
            assert isinstance(encoded, str)
            der = base64.b64decode(encoded, validate=True)
            public = load_der_public_key(der)
            assert isinstance(public, type(Ed25519PrivateKey.generate().public_key()))
            state["public"] = public
            state["fingerprint"] = hashlib.sha256(der).hexdigest()
            return {
                "challengeId": CHALLENGE,
                "userCode": CODE,
                "deviceCode": SECRET,
                "deviceFingerprint": state["fingerprint"],
                "expiresAtMs": time.time_ns() // 1_000_000 + 90_000,
                "verificationUriComplete": (
                    ORIGIN + "/devices/pairing#challenge=" + CHALLENGE + "&code=" + CODE
                ),
            }
        if path.endswith("/status"):
            events.append("status")
            assert status == 200
            check_signature(body, b"kicad-cloud-pairing-status-v1\x00")
            return {"approved": state["approved"]}
        if path.endswith("/redeem"):
            events.append("redeem")
            assert status == 200
            assert state["approved"]
            check_signature(body, b"kicad-cloud-pairing-proof-v1\x00")
            return {
                "deviceId": DEVICE,
                "deviceFingerprint": state["fingerprint"],
                "ownerSub": OWNER,
                "enabled": False,
            }
        if path.endswith("/project"):
            events.append("project")
            assert status == 200
            assert body["deviceId"] == DEVICE
            assert body["alias"] == "demo_board"
            encoded = body["signature"]
            assert isinstance(encoded, str)
            signature = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
            state["public"].verify(
                signature,
                b"kicad-cloud-device-project-v1\x00"
                + DEVICE.encode("ascii")
                + b"\x00"
                + b"demo_board",
            )
            return {
                "projectId": CHALLENGE,
                "alias": "demo_board",
                "ownerSub": OWNER,
                "enabled": False,
            }
        raise AssertionError(f"unexpected HTTP path {path}")

    monkeypatch.setattr(cloud_pair, "_post", response)
    return store, events, state


def _approval(events: list[str], state: dict[str, Any]) -> Callable[[str, str, str], None]:
    def callback(page: str, challenge: str, code: str) -> None:
        assert page == ORIGIN + "/devices/pairing"
        assert challenge == CHALLENGE and code == CODE
        assert not state["approved"]
        events.append("owner_approval")
        state["approved"] = True

    return callback


def test_windows_enrollment_requires_pending_then_owner_approval_before_redeem(
    fake_windows_pair: tuple[dict[tuple[str, str], bytes], list[str], dict[str, Any]],
    tmp_path,
) -> None:
    store, events, state = fake_windows_pair
    before = list(tmp_path.iterdir())
    result = cloud_windows_enrollment.enroll_windows_device(
        origin=ORIGIN,
        alias="Lab PC",
        owner_approval=_approval(events, state),
    )
    assert result.device_id == DEVICE
    assert result.owner_sub == OWNER
    assert result.origin == ORIGIN
    assert len(result.record_id) == 32
    assert result.fingerprint == state["fingerprint"]
    assert set(store) == {(result.record_id, "key"), (result.record_id, "binding")}
    binding = json.loads(store[(result.record_id, "binding")])
    assert binding == {
        "recordId": result.record_id,
        "origin": ORIGIN,
        "ownerSub": OWNER,
        "deviceId": DEVICE,
        "fingerprint": result.fingerprint,
    }
    assert events == [
        "vault:key",
        "challenge",
        "status",
        "owner_approval",
        "status",
        "redeem",
        "vault:binding",
    ]
    assert list(tmp_path.iterdir()) == before  # no private keys/challenges on disk


def test_windows_forged_preapproval_is_denied_and_key_removed(
    fake_windows_pair,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, events, state = fake_windows_pair
    state["approved"] = True
    with pytest.raises(cloud_windows_enrollment.WindowsEnrollmentError):
        cloud_windows_enrollment.enroll_windows_device(
            origin=ORIGIN,
            alias="Lab PC",
            owner_approval=lambda *_args: pytest.fail("No approval callback expected"),
        )
    assert not store
    assert "redeem" not in events
    assert events[-1] == "delete:key"


def test_windows_owner_approval_expiry_erases_only_the_unredeemed_key(
    fake_windows_pair, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, events, _state = fake_windows_pair

    def expire(*_args: object, **_kwargs: object) -> None:
        raise cloud_pair.CloudPairingTimeoutError("approval expired")

    monkeypatch.setattr(cloud_pair, "_wait_for_owner_approval", expire)
    with pytest.raises(cloud_windows_enrollment.WindowsEnrollmentTimeoutError):
        cloud_windows_enrollment.enroll_windows_device(
            origin=ORIGIN,
            alias="Lab PC",
            owner_approval=lambda *_: pytest.fail("expired challenge cannot be approved"),
        )
    assert not store
    assert events == ["vault:key", "challenge", "delete:key"]


def test_windows_owner_denial_erases_unredeemed_key(
    fake_windows_pair,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, events, _state = fake_windows_pair

    def deny(*_args: object, **_kwargs: object) -> None:
        raise cloud_pair.CloudPairingDeniedError("owner denied")

    monkeypatch.setattr(cloud_pair, "_wait_for_owner_approval", deny)
    with pytest.raises(cloud_windows_enrollment.WindowsEnrollmentDeniedError):
        cloud_windows_enrollment.enroll_windows_device(
            origin=ORIGIN,
            alias="Lab PC",
            owner_approval=lambda *_: None,
        )
    assert not store
    assert events == ["vault:key", "challenge", "delete:key"]


def test_windows_owner_interrupt_cleans_unredeemed_key(
    fake_windows_pair, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, events, _state = fake_windows_pair

    def interrupt(*_args: object, **_kwargs: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(cloud_pair, "_wait_for_owner_approval", interrupt)
    with pytest.raises(KeyboardInterrupt):
        cloud_windows_enrollment.enroll_windows_device(
            origin=ORIGIN,
            alias="Lab PC",
            owner_approval=lambda *_: None,
        )
    assert not store
    assert events == ["vault:key", "challenge", "delete:key"]


def test_windows_vault_binding_failure_does_not_claim_success(
    fake_windows_pair,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, events, state = fake_windows_pair
    original = cloud_windows_enrollment.create_credential

    def fail_binding(record_id: str, part: str, data: bytes) -> None:
        if part == "binding":
            raise LocalApprovalDeniedError("injected")
        original(record_id, part, data)

    monkeypatch.setattr(cloud_windows_enrollment, "create_credential", fail_binding)
    with pytest.raises(cloud_windows_enrollment.WindowsPartialEnrollmentError) as info:
        cloud_windows_enrollment.enroll_windows_device(
            origin=ORIGIN,
            alias="Lab PC",
            owner_approval=_approval(events, state),
        )
    assert "Cloud device may already be registered" in str(info.value)
    assert "redeem" in events
    assert (info.value.record_id, "key") in store  # key retained for owner recovery
    assert (info.value.record_id, "binding") not in store


@pytest.mark.parametrize("name", ["", "bad/name", "X" * 65, "\\n"])
def test_invalid_alias_refused_before_vault_or_http(
    fake_windows_pair,
    name: str,
) -> None:
    store, events, state = fake_windows_pair
    with pytest.raises(cloud_windows_enrollment.WindowsEnrollmentError):
        cloud_windows_enrollment.enroll_windows_device(
            origin=ORIGIN, alias=name, owner_approval=_approval(events, state)
        )
    assert not store and not events


def test_other_platform_cannot_call_windows_pairing(
    fake_windows_pair,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, events, state = fake_windows_pair
    monkeypatch.setattr(cloud_windows_enrollment, "os", SimpleNamespace(name="posix"))
    with pytest.raises(cloud_windows_enrollment.WindowsEnrollmentError):
        cloud_windows_enrollment.enroll_windows_device(
            origin=ORIGIN,
            alias="Lab PC",
            owner_approval=_approval(events, state),
        )
    assert not events and not store


@pytest.mark.parametrize("enabled", [True, False])
def test_windows_project_accepts_boolean_cloud_state_without_enabling_connector(
    fake_windows_pair, monkeypatch: pytest.MonkeyPatch, enabled: bool
) -> None:
    _store, events, state = fake_windows_pair
    device = cloud_windows_enrollment.enroll_windows_device(
        origin=ORIGIN, alias="Lab PC", owner_approval=_approval(events, state)
    )
    original = cloud_pair._post

    def project_reply(target, path, body, status):
        reply = original(target, path, body, status)
        if path.endswith("/project"):
            reply["enabled"] = enabled
        return reply

    monkeypatch.setattr(cloud_pair, "_post", project_reply)
    registered = cloud_windows_enrollment.register_windows_project(
        device, alias="demo_board", filename_stem="demo_board"
    )
    assert registered.project_id == CHALLENGE
    assert not hasattr(registered, "enabled")
    assert not hasattr(registered, "authorized")


@pytest.mark.parametrize("invalid", ["true", 1, None, {}, []])
def test_windows_project_rejects_invalid_cloud_enabled_field(
    fake_windows_pair, monkeypatch: pytest.MonkeyPatch, invalid
) -> None:
    _store, events, state = fake_windows_pair
    device = cloud_windows_enrollment.enroll_windows_device(
        origin=ORIGIN, alias="Lab PC", owner_approval=_approval(events, state)
    )
    original = cloud_pair._post

    def project_reply(target, path, body, status):
        reply = original(target, path, body, status)
        if path.endswith("/project"):
            reply["enabled"] = invalid
        return reply

    monkeypatch.setattr(cloud_pair, "_post", project_reply)
    with pytest.raises(cloud_windows_enrollment.WindowsPartialProjectRegistrationError):
        cloud_windows_enrollment.register_windows_project(
            device, alias="demo_board", filename_stem="demo_board"
        )


def test_windows_project_registration_uses_signed_owner_key_and_vault_reference(
    fake_windows_pair: tuple[dict[tuple[str, str], bytes], list[str], dict[str, Any]],
    tmp_path,
) -> None:
    store, events, state = fake_windows_pair
    device = cloud_windows_enrollment.enroll_windows_device(
        origin=ORIGIN, alias="Lab PC", owner_approval=_approval(events, state)
    )
    before = list(tmp_path.iterdir())
    project = cloud_windows_enrollment.register_windows_project(
        device, alias="demo_board", filename_stem="demo_board"
    )
    assert project.device_id == DEVICE
    assert project.project_id == CHALLENGE
    assert project.owner_sub == OWNER
    assert len(project.registration_id) == 32
    assert project.registration_id != project.record_id
    document = json.loads(store[(project.registration_id, "registration")])
    assert document == {
        "registrationId": project.registration_id,
        "recordId": project.record_id,
        "origin": ORIGIN,
        "ownerSub": OWNER,
        "deviceId": DEVICE,
        "fingerprint": device.fingerprint,
        "projectId": CHALLENGE,
        "filenameStem": "demo_board",
    }
    assert not hasattr(project, "project_directory")
    assert not hasattr(project, "enabled")
    assert not hasattr(project, "authorized")
    assert events[-2:] == ["project", "vault:registration"]
    assert list(tmp_path.iterdir()) == before


@pytest.mark.parametrize("alias,stem", [("bad/alias", "ok"), ("ok", "../bad"), ("ok", "a b")])
def test_invalid_windows_project_selection_never_contacts_cloud(
    fake_windows_pair,
    alias: str,
    stem: str,
) -> None:
    _store, events, state = fake_windows_pair
    device = cloud_windows_enrollment.enroll_windows_device(
        origin=ORIGIN, alias="Lab PC", owner_approval=_approval(events, state)
    )
    events.clear()
    with pytest.raises(cloud_windows_enrollment.WindowsEnrollmentError):
        cloud_windows_enrollment.register_windows_project(device, alias=alias, filename_stem=stem)
    assert not events


def test_windows_project_rejects_forged_owner_selector_before_request(
    fake_windows_pair,
) -> None:
    from dataclasses import replace

    _store, events, state = fake_windows_pair
    device = cloud_windows_enrollment.enroll_windows_device(
        origin=ORIGIN, alias="Lab PC", owner_approval=_approval(events, state)
    )
    events.clear()
    forged = replace(device, owner_sub="attacker-owner")
    with pytest.raises(LocalApprovalDeniedError):
        cloud_windows_enrollment.register_windows_project(
            forged, alias="demo_board", filename_stem="demo_board"
        )
    assert not events


def test_windows_project_vault_failure_does_not_claim_registered(
    fake_windows_pair,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, events, state = fake_windows_pair
    device = cloud_windows_enrollment.enroll_windows_device(
        origin=ORIGIN, alias="Lab PC", owner_approval=_approval(events, state)
    )
    original = cloud_windows_enrollment.create_credential

    def fail_registration(record_id: str, part: str, data: bytes) -> None:
        if part == "registration":
            raise LocalApprovalDeniedError("injected")
        original(record_id, part, data)

    monkeypatch.setattr(cloud_windows_enrollment, "create_credential", fail_registration)
    with pytest.raises(cloud_windows_enrollment.WindowsPartialProjectRegistrationError):
        cloud_windows_enrollment.register_windows_project(
            device, alias="demo_board", filename_stem="demo_board"
        )
    assert "project" in events
    assert all(part != "registration" for _record, part in store)


def test_lost_redeem_response_is_partial_and_keeps_owner_key(
    fake_windows_pair,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, events, state = fake_windows_pair
    original = cloud_pair._post

    def lost_reply(target, path, body, status):
        if path.endswith("/redeem"):
            events.append("redeem_sent")
            raise cloud_pair.CloudPairingError("network response lost")
        return original(target, path, body, status)

    monkeypatch.setattr(cloud_pair, "_post", lost_reply)
    with pytest.raises(cloud_windows_enrollment.WindowsPartialEnrollmentError) as exc:
        cloud_windows_enrollment.enroll_windows_device(
            origin=ORIGIN, alias="Lab PC", owner_approval=_approval(events, state)
        )
    assert "redeem_sent" in events
    assert (exc.value.record_id, "key") in store
    assert "delete:key" not in events


def test_failed_credential_create_does_not_delete_unowned_vault_key(
    fake_windows_pair,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, events, state = fake_windows_pair

    def refuse_create(_record: str, _part: str, _data: bytes) -> None:
        raise LocalApprovalDeniedError("preexisting credential")

    monkeypatch.setattr(cloud_windows_enrollment, "create_credential", refuse_create)
    with pytest.raises(cloud_windows_enrollment.WindowsEnrollmentError):
        cloud_windows_enrollment.enroll_windows_device(
            origin=ORIGIN, alias="Lab PC", owner_approval=_approval(events, state)
        )
    assert not store
    assert not events


def test_credential_substitution_before_redeem_denies_remote_registration(
    fake_windows_pair,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cryptography.hazmat.primitives.serialization import (
        Encoding,
        NoEncryption,
        PrivateFormat,
    )

    store, events, state = fake_windows_pair

    def swap_key(page: str, challenge: str, code: str) -> None:
        _approval(events, state)(page, challenge, code)
        record_id = next(record for record, part in store if part == "key")
        altered = Ed25519PrivateKey.generate().private_bytes(
            Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()
        )
        store[(record_id, "key")] = altered
        events.append("replaced_key")

    with pytest.raises(cloud_windows_enrollment.WindowsEnrollmentError):
        cloud_windows_enrollment.enroll_windows_device(
            origin=ORIGIN, alias="Lab PC", owner_approval=swap_key
        )
    assert "redeem" not in events
    assert "replaced_key" in events
    assert "delete:key" not in events


def test_unexpected_cloud_grant_is_not_claimed_as_valid(
    fake_windows_pair,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, events, state = fake_windows_pair
    original = cloud_pair._post

    def enabled_reply(target, path, body, status):
        result = original(target, path, body, status)
        if path.endswith("/redeem"):
            result["enabled"] = True
        return result

    monkeypatch.setattr(cloud_pair, "_post", enabled_reply)
    with pytest.raises(cloud_windows_enrollment.WindowsPartialEnrollmentError):
        cloud_windows_enrollment.enroll_windows_device(
            origin=ORIGIN, alias="Lab PC", owner_approval=_approval(events, state)
        )
    assert "redeem" in events
    assert len(store) == 1
