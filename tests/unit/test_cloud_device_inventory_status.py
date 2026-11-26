"""A failed session must not imply that the owner deleted the device."""

from __future__ import annotations

import base64
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from kicad_mcp import cloud_pair, cloud_user_cli
from kicad_mcp import cloud_windows_device_bootstrap as boot
from kicad_mcp.cloud_windows_enrollment import WindowsEnrolledDevice, WindowsRegisteredProject


@pytest.mark.parametrize(
    "state",
    [
        "active",
        "device_disabled",
        "device_revoked",
        "project_missing",
        "project_disabled",
        "unverified",
        "network",
        "wrong_nonce",
    ],
)
def test_signed_inventory_status(monkeypatch, state) -> None:
    from kicad_mcp.cloud_device_inventory_status import inspect_inventory

    key = Ed25519PrivateKey.generate()
    device, project = str(uuid4()), str(uuid4())

    def post(origin, path, body, status):
        assert origin[2] == cloud_user_cli.DEFAULT_CLOUD_ORIGIN
        assert path == "/api/v1/pairing/device/inventory" and status == 200
        assert body["deviceId"] == device and body["projectId"] == project
        assert body["ownerSub"] == "owner"
        proof = "\0".join(
            (
                "kicad-cloud-device-inventory-v1",
                device,
                "owner",
                project,
                body["nonce"],
                str(body["issuedAtMs"]),
            )
        ).encode()
        key.public_key().verify(base64.urlsafe_b64decode(body["signature"] + "=="), proof)
        if state == "network":
            raise cloud_pair.CloudPairingError("network unavailable")
        return {
            "nonce": "wrong" if state == "wrong_nonce" else body["nonce"],
            "state": "active" if state == "wrong_nonce" else state,
        }

    monkeypatch.setattr(cloud_pair, "_post", post)
    result = inspect_inventory(cloud_user_cli.DEFAULT_CLOUD_ORIGIN, "owner", device, project, key)
    assert result == ("unavailable" if state in {"network", "wrong_nonce"} else state)


@pytest.mark.parametrize(
    "state",
    [
        "active",
        "device_disabled",
        "project_disabled",
        "unavailable",
        "project_missing",
        "device_revoked",
        "unverified",
    ],
)
def test_policy_recovery_routes_by_actual_status(monkeypatch, state) -> None:
    from kicad_mcp import cloud_device_inventory_status as inventory
    from kicad_mcp import cloud_windows_connector as connector

    device = WindowsEnrolledDevice(
        "a" * 32, cloud_user_cli.DEFAULT_CLOUD_ORIGIN, "owner", str(uuid4()), "b" * 64
    )
    monkeypatch.setattr(boot, "selected_device", lambda: device)
    project = WindowsRegisteredProject(
        "c" * 32,
        device.record_id,
        device.origin,
        device.owner_sub,
        device.device_id,
        device.fingerprint,
        str(uuid4()),
        "board",
    )
    monkeypatch.setattr(connector, "selected_project", lambda: project)
    monkeypatch.setattr(boot, "verified_device_key", lambda _: Ed25519PrivateKey.generate())
    monkeypatch.setattr(inventory, "inspect_inventory", lambda *_: state)
    monkeypatch.setattr(cloud_user_cli, "_call_with_owner_connector", lambda fn, *args: fn(*args))
    events = []
    monkeypatch.setattr(boot, "repair_device_only", lambda **_: events.append("pair"))
    monkeypatch.setattr(
        boot, "detach_missing_project", lambda *_: events.append("detach"), raising=False
    )
    result = cloud_user_cli._offer_device_recovery()
    expected = (
        ["pair"]
        if state in {"device_revoked", "unverified"}
        else ["detach"]
        if state == "project_missing"
        else []
    )
    assert events == expected
    assert result is bool(expected)
