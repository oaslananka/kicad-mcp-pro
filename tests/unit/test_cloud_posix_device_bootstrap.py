"""Device-only setup must never infer a project from the terminal directory."""

from __future__ import annotations

import os
from uuid import uuid4

import pytest

from kicad_mcp import cloud_pair, cloud_pair_keys, cloud_posix_recovery

ORIGIN = "https://kicad-mcp-pro.oaslananka.dev"


@pytest.mark.parametrize("existing", [False, True])
def test_device_only_enrollment_and_reuse(tmp_path, monkeypatch, existing) -> None:
    from kicad_mcp import cloud_posix_device_bootstrap as boot

    root = tmp_path / "registry"
    root.mkdir(mode=0o700)
    keyfile = root / "keys" / f"{uuid4()}.pem"
    binding = {
        "origin": ORIGIN,
        "ownerSub": "owner",
        "deviceId": str(uuid4()),
        "fingerprint": "a" * 64,
    }
    state = {"candidate": (keyfile, binding) if existing else None}
    calls = []

    def enroll(origin, alias, path, approval, *, connect_on_approval=False):
        assert origin == ORIGIN and connect_on_approval is True
        assert alias == "PC"
        calls.append("enroll")
        state["candidate"] = (path, binding)
        return binding["deviceId"], binding["fingerprint"]

    def initial(root, origin, alias, approval):
        enroll(origin, alias, keyfile, approval, connect_on_approval=True)
        return state["candidate"]

    monkeypatch.setattr("kicad_mcp.cloud_posix_initial_enrollment.enroll_initial", initial)
    monkeypatch.setattr(cloud_pair, "enroll", enroll)
    monkeypatch.setattr(
        cloud_posix_recovery, "inspect_unbound_device", lambda *_: state["candidate"]
    )
    monkeypatch.setattr(cloud_pair_keys, "_read_owner_binding", lambda _: binding)
    monkeypatch.setattr(
        cloud_pair, "register_device_project", lambda *_: pytest.fail("implicit project")
    )
    result = boot.ensure_device(root, ORIGIN, "PC", lambda *_: None)
    assert result == state["candidate"]
    assert calls == ([] if existing else ["enroll"])
    assert not (root / "projects").exists()


def test_browser_binding_requires_exact_selected_file_and_identity(tmp_path, monkeypatch) -> None:
    from kicad_mcp import cloud_posix_device_bootstrap as boot

    root = tmp_path / "registry"
    root.mkdir(mode=0o700)
    keyfile = root / "keys" / f"{uuid4()}.pem"
    keyfile.parent.mkdir(mode=0o700)
    keyfile.touch(mode=0o600)
    identity = (
        keyfile,
        {"origin": ORIGIN, "ownerSub": "owner", "deviceId": str(uuid4()), "fingerprint": "a" * 64},
    )
    monkeypatch.setattr(cloud_posix_recovery, "inspect_unbound_device", lambda *_: identity)
    board = tmp_path / "board"
    board.mkdir()
    project = board / "board.kicad_pro"
    project.touch()
    pid = str(uuid4())
    with pytest.raises(ValueError):
        boot.adopt_project(root, identity, pid, board / "missing.kicad_pro")
    assert not (root / "projects").exists()
    assert boot.adopt_project(root, identity, pid, project)
    record = boot.read_project(root, identity)
    assert record["projectId"] == pid and record["directory"] == str(board)
    assert record["deviceId"] == identity[1]["deviceId"]
    with pytest.raises(ValueError):
        boot.adopt_project(root, identity, str(uuid4()), project)


@pytest.mark.parametrize("enabled", [True, False])
def test_posix_redeem_connect_only_proof(tmp_path, monkeypatch, enabled) -> None:
    import base64
    import time

    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    key = Ed25519PrivateKey.generate()
    keyfile = tmp_path / "device.pem"
    challenge, device = str(uuid4()), str(uuid4())
    secret = base64.urlsafe_b64encode(bytes(range(32))).decode().rstrip("=")
    fingerprint = "a" * 64
    challenge_file = keyfile.with_suffix(cloud_pair._CHALLENGE_SUFFIX)
    challenge_file.touch()
    monkeypatch.setattr(cloud_pair, "_load_owner_key", lambda _: key)
    monkeypatch.setattr(
        cloud_pair,
        "_read_private_json",
        lambda *_: {
            "challenge": challenge,
            "secret": secret,
            "expiry": time.time_ns() // 1_000_000 + 60000,
            "fingerprint": fingerprint,
        },
    )
    bindings = []

    def post(_target, path, payload, status):
        assert path == "/api/v1/pairing/device/redeem" and status == 200
        assert set(payload) == {"challengeId", "deviceCode", "signature", "connectOnApproval"}
        assert payload["connectOnApproval"] is True
        proof = b"kicad-cloud-pairing-proof-v1\x00" + challenge.encode() + b"\x00" + secret.encode()
        key.public_key().verify(base64.urlsafe_b64decode(payload["signature"] + "=="), proof)
        return {
            "deviceId": device,
            "deviceFingerprint": fingerprint,
            "ownerSub": "owner",
            "enabled": enabled,
        }

    monkeypatch.setattr(cloud_pair, "_post", post)
    monkeypatch.setattr(
        cloud_pair, "_save_owner_binding", lambda *args, **kwargs: bindings.append(kwargs)
    )
    if enabled:
        assert cloud_pair.redeem_enrollment(ORIGIN, keyfile, connect_on_approval=True) == (
            device,
            fingerprint,
        )
        assert len(bindings) == 1
        assert not challenge_file.exists()
    else:
        with pytest.raises(cloud_pair.CloudPairingError):
            cloud_pair.redeem_enrollment(ORIGIN, keyfile, connect_on_approval=True)
        assert not bindings and challenge_file.exists()


@pytest.mark.asyncio
async def test_device_only_session_waits_for_explicit_browser_bind(tmp_path, monkeypatch) -> None:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from kicad_mcp import cloud_posix_device_bootstrap as boot

    root = tmp_path / "registry"
    root.mkdir(mode=0o700)
    keyfile = root / "keys" / f"{uuid4()}.pem"
    keyfile.parent.mkdir(mode=0o700)
    keyfile.touch(mode=0o600)
    identity = (
        keyfile,
        {"origin": ORIGIN, "ownerSub": "owner", "deviceId": str(uuid4()), "fingerprint": "a" * 64},
    )
    monkeypatch.setattr(cloud_posix_recovery, "inspect_unbound_device", lambda *_: identity)
    monkeypatch.setattr(boot, "_load_bound_owner_key", lambda *_: Ed25519PrivateKey.generate())
    monkeypatch.setattr(boot, "default_bindings_file", lambda: root / "folder-bindings.json")
    board = tmp_path / "board"
    board.mkdir()
    (board / "board.kicad_pro").touch()
    monkeypatch.setattr(boot, "_posix_owner_native_picker", lambda: board)
    project_id = str(uuid4())
    status = []

    async def run(**kwargs: object) -> None:
        assert not (root / "projects").exists()
        assert "dispatcher_factory" not in kwargs and "native_write" not in kwargs
        kwargs["on_ready"](None)
        service = kwargs["folder_service_factory"](None)
        chosen = service.choose()
        assert chosen["status"] == "selected"
        assert not (root / "projects").exists()
        assert service.bind(chosen["projects"][0]["id"], project_id)

    monkeypatch.setattr(boot, "execute_owner_folder_only_session", run)
    record = await boot._wait_for_project(root, identity, status.append)
    assert record["projectId"] == project_id
    assert status == ["Connecting", "Cloud acknowledged this device's signed session"]


@pytest.mark.parametrize(
    "state",
    [
        "project_missing",
        "active",
        "unverified",
        "unavailable",
        "device_disabled",
        "foreign_archive",
    ],
)
@pytest.mark.skipif(os.name != "posix", reason="POSIX private registry lock")
def test_posix_deleted_project_reuses_device_without_pairing(tmp_path, monkeypatch, state) -> None:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from kicad_mcp import cloud_device_inventory_status as inventory
    from kicad_mcp import cloud_posix_device_bootstrap as boot

    root = tmp_path / "registry"
    root.mkdir(mode=0o700)
    keyfile = root / "keys" / f"{uuid4()}.pem"
    keyfile.parent.mkdir(mode=0o700)
    keyfile.touch(mode=0o600)
    identity = (
        keyfile,
        {"origin": ORIGIN, "ownerSub": "owner", "deviceId": str(uuid4()), "fingerprint": "a" * 64},
    )
    monkeypatch.setattr(cloud_posix_recovery, "inspect_unbound_device", lambda *_: identity)
    board = tmp_path / "board"
    board.mkdir()
    project = board / "board.kicad_pro"
    project.write_text("{}")
    pid = str(uuid4())
    boot.adopt_project(root, identity, pid, project)
    record = boot.read_project(root, identity)
    monkeypatch.setattr(boot, "_load_bound_owner_key", lambda *_: Ed25519PrivateKey.generate())
    monkeypatch.setattr(
        inventory,
        "inspect_inventory",
        lambda *_: "project_missing" if state == "foreign_archive" else state,
    )
    monkeypatch.setattr(cloud_pair, "enroll", lambda *_: pytest.fail("unexpected pairing"))
    if state == "foreign_archive":
        archive = root / "detached-projects"
        archive.mkdir(mode=0o700)
        cloud_pair_keys._write_private_json(archive, pid + ".json", {"foreign": "record"})
        with pytest.raises(ValueError):
            boot.recover_missing_project(root, record)
    else:
        assert boot.recover_missing_project(root, record) == (state == "project_missing")
    assert boot.read_project(root, identity) == (None if state == "project_missing" else record)
    assert project.read_text() == "{}"
    assert keyfile.is_file()
    if state == "project_missing":
        assert (
            cloud_pair_keys._read_private_json(root / "detached-projects", pid + ".json") == record
        )


@pytest.mark.parametrize("recovered", [True, False])
@pytest.mark.skipif(os.name != "posix", reason="POSIX registry lock")
def test_device_only_recovery_reconnects_once(tmp_path, monkeypatch, recovered) -> None:
    from kicad_mcp import cloud_posix_device_bootstrap as boot
    from kicad_mcp import cloud_posix_replacement as replacement

    root = tmp_path / "registry"
    root.mkdir(mode=0o700)
    identities = [(root / "old", {"origin": ORIGIN}), (root / "new", {"origin": ORIGIN})]
    events = []
    result = {"projectId": str(uuid4())}

    def ensure(*_args: object):
        identity = identities.pop(0)
        events.append(identity[0].name)
        return identity

    async def wait(_root, identity, _status):
        events.append("connect-" + identity[0].name)
        if identity[0].name == "old":
            raise boot.DeviceSessionRejectedError("policy")
        return result

    def recover(*_args: object) -> bool:
        events.append("diagnosis")
        return recovered

    monkeypatch.setattr(boot, "ensure_device", ensure)
    monkeypatch.setattr(boot, "_wait_for_project", wait)
    monkeypatch.setattr(replacement, "recover_device_locked", recover)
    if recovered:
        assert (
            boot.connect_device_only(root, ORIGIN, "PC", lambda *_: None, lambda _: None) == result
        )
        assert events == ["old", "connect-old", "diagnosis", "new", "connect-new"]
    else:
        with pytest.raises(boot.DeviceSessionRejectedError):
            boot.connect_device_only(root, ORIGIN, "PC", lambda *_: None, lambda _: None)
        assert events == ["old", "connect-old", "diagnosis"]


@pytest.mark.parametrize("state", ["active", "project_missing", "project_disabled", "unavailable"])
@pytest.mark.skipif(os.name != "posix", reason="POSIX registry lock")
def test_deleted_primary_uses_existing_secondary_without_picker(
    tmp_path, monkeypatch, state
) -> None:
    from kicad_mcp import cloud_posix_device_bootstrap as boot
    from kicad_mcp import cloud_posix_project_bindings as bindings
    from kicad_mcp.cloud_local_registry import LocalRegisteredRead

    root = tmp_path / "registry"
    root.mkdir(mode=0o700)
    keyfile = root / "keys" / f"{uuid4()}.pem"
    keyfile.parent.mkdir(mode=0o700)
    keyfile.touch(mode=0o600)
    identity = (
        keyfile,
        {"origin": ORIGIN, "ownerSub": "owner", "deviceId": str(uuid4()), "fingerprint": "a" * 64},
    )
    monkeypatch.setattr(cloud_posix_recovery, "inspect_unbound_device", lambda *_: identity)
    monkeypatch.setattr(boot, "_load_bound_owner_key", lambda *_: object())
    primary, secondary = tmp_path / "primary", tmp_path / "secondary"
    for path in (primary, secondary):
        path.mkdir()
        (path / "board.kicad_pro").write_text("{}")
    first, second = str(uuid4()), str(uuid4())
    boot.adopt_project(root, identity, first, primary / "board.kicad_pro")
    record = boot.read_project(root, identity)
    service = bindings.folder_service(
        root,
        record,
        LocalRegisteredRead(keyfile, primary, "board"),
        lambda: True,
        native_picker=lambda: secondary,
    )
    assert service.bind(service.choose()["projects"][0]["id"], second)
    calls = []

    def status(_origin, _owner, _device, pid, _key):
        calls.append(pid)
        return "project_missing" if pid == first else state

    monkeypatch.setattr("kicad_mcp.cloud_device_inventory_status.inspect_inventory", status)
    monkeypatch.setattr(cloud_pair, "enroll", lambda *_: pytest.fail("unexpected pairing"))
    assert boot.recover_missing_project(root, record)
    assert boot.read_project(root, identity) is None

    async def wait(*_args: object):
        assert state != "active"
        return None

    monkeypatch.setattr(boot, "_wait_for_project", wait)
    result = boot.connect_device_only(
        root, ORIGIN, "PC", lambda *_: pytest.fail("unexpected approval"), lambda _: None
    )
    if state == "active":
        assert result["projectId"] == second
        assert result["directory"] == str(secondary)
        assert boot.read_project(root, identity) == result
    else:
        assert result is None
        assert boot.read_project(root, identity) is None
    assert calls == [first, second]
    assert (primary / "board.kicad_pro").read_text() == "{}"
    assert (secondary / "board.kicad_pro").read_text() == "{}"
    assert keyfile.exists()


@pytest.mark.asyncio
async def test_device_only_update_drain_preserves_identity(tmp_path, monkeypatch) -> None:
    import asyncio

    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from kicad_mcp import cloud_posix_device_bootstrap as boot

    root = tmp_path / "registry"
    root.mkdir(mode=0o700)
    keyfile = root / "key.pem"
    keyfile.touch()
    identity = (keyfile, {"origin": ORIGIN, "ownerSub": "owner", "deviceId": str(uuid4())})
    monkeypatch.setattr(boot, "read_project", lambda *_: None)
    monkeypatch.setattr(cloud_posix_recovery, "inspect_unbound_device", lambda *_: identity)
    monkeypatch.setattr(boot, "_load_bound_owner_key", lambda *_: Ed25519PrivateKey.generate())
    drain = asyncio.Event()
    calls = []

    async def session(**kwargs: object) -> None:
        assert kwargs["drain"] is drain
        calls.append("socket")
        drain.set()

    monkeypatch.setattr(boot, "execute_owner_folder_only_session", session)
    assert (
        await asyncio.wait_for(boot._wait_for_project(root, identity, lambda _: None, drain), 2)
        is None
    )
    assert calls == ["socket"]
    assert keyfile.exists() and not (root / "projects").exists()
