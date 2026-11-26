"""A new Cloud user should pair one device, choose no project until the UI asks."""

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

from kicad_mcp import cloud_windows_device_bootstrap as boot
from kicad_mcp.cloud_pair_keys import LocalApprovalDeniedError
from kicad_mcp.cloud_windows_enrollment import WindowsEnrolledDevice


@pytest.fixture
def saved_device(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[WindowsEnrolledDevice, dict[tuple[str, str], bytes]]:
    key = Ed25519PrivateKey.generate()
    der = key.public_key().public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
    device = WindowsEnrolledDevice(
        "a" * 32,
        "https://cloud.example",
        "owner",
        "11111111-1111-4111-8111-111111111111",
        hashlib.sha256(der).hexdigest(),
    )
    store = {
        (device.record_id, "key"): key.private_bytes(
            Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()
        )
    }
    monkeypatch.setattr(boot, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(boot, "read_credential", lambda record, part: store.get((record, part)))

    def create(record: str, part: str, data: bytes) -> None:
        if (record, part) in store:
            raise LocalApprovalDeniedError("existing")
        store[(record, part)] = data

    monkeypatch.setattr(boot, "create_credential", create)
    monkeypatch.setattr(
        boot,
        "inspect_local_binding",
        lambda **_kwargs: SimpleNamespace(fingerprint=device.fingerprint),
    )
    return device, store


def test_existing_approved_device_is_reused_without_a_second_pairing(saved_device) -> None:
    device, store = saved_device
    assert boot.selected_device() is None
    boot.remember_device(device)
    boot.remember_device(device)
    assert boot.selected_device() == device
    assert len(store) == 2
    assert isinstance(boot.verified_device_key(device), Ed25519PrivateKey)
    with pytest.raises(LocalApprovalDeniedError):
        boot.remember_device(
            WindowsEnrolledDevice(
                "b" * 32, device.origin, device.owner_sub, str(uuid4()), device.fingerprint
            )
        )
    assert boot.selected_device() == device


def test_native_owner_project_binding_uses_original_device_identity(
    saved_device, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    device, store = saved_device
    boot.remember_device(device)
    folder = tmp_path / "Board"
    folder.mkdir()
    file = folder / "Board.kicad_pro"
    file.write_text("{}", encoding="utf-8")
    project_id = str(uuid4())
    registered = []
    monkeypatch.setattr(
        boot, "read_windows_project_presence", lambda _folder, _stem: {"project": True}
    )
    monkeypatch.setattr(boot, "inspect_project_reference", lambda **_kwargs: None)
    import kicad_mcp.cloud_windows_connector as connector

    monkeypatch.setattr(connector, "selected_project", lambda: None)
    monkeypatch.setattr(
        connector,
        "remember_selected_project",
        lambda project: registered.append(("selected", project)),
    )
    monkeypatch.setattr(
        connector,
        "activate",
        lambda project, owner_confirm: registered.append(("activated", project)),
    )
    monkeypatch.setattr(
        boot,
        "bind_owner_selected_project",
        lambda project, directory, owner_confirm: registered.append(("folder", directory)),
    )
    assert boot.adopt_browser_project(device, project_id, file)
    refs = [json.loads(blob) for (record, part), blob in store.items() if part == "registration"]
    assert len(refs) == 1
    assert refs[0]["deviceId"] == device.device_id
    assert refs[0]["projectId"] == project_id
    assert refs[0]["filenameStem"] == "Board"
    assert "directory" not in refs[0]
    assert [op for op, _ in registered] == ["folder", "selected", "activated"]


def test_unbound_device_cannot_adopt_unselected_or_nonproject_path(
    saved_device, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    device, store = saved_device
    boot.remember_device(device)
    import kicad_mcp.cloud_windows_connector as connector

    monkeypatch.setattr(connector, "selected_project", lambda: None)
    bad = tmp_path / "no-project.txt"
    bad.write_text("secret", encoding="utf-8")
    with pytest.raises(LocalApprovalDeniedError):
        boot.adopt_browser_project(device, str(uuid4()), bad)
    assert not any(part == "registration" for _record, part in store)


def test_verified_legacy_project_can_be_reused_as_the_same_device(
    saved_device, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kicad_mcp import cloud_windows_connector as connector
    from kicad_mcp.cloud_windows_enrollment import WindowsRegisteredProject

    device, store = saved_device
    project = WindowsRegisteredProject(
        registration_id="b" * 32,
        record_id=device.record_id,
        origin=device.origin,
        owner_sub=device.owner_sub,
        device_id=device.device_id,
        fingerprint=device.fingerprint,
        project_id=str(uuid4()),
        filename_stem="Test",
    )
    monkeypatch.setattr(connector, "selected_project", lambda: project)
    boot.remember_existing_project_device(project)
    boot.remember_existing_project_device(project)
    assert boot.selected_device() == device
    assert len(store) == 2
    monkeypatch.setattr(connector, "selected_project", lambda: None)
    with pytest.raises(LocalApprovalDeniedError):
        boot.remember_existing_project_device(project)


def test_unbound_connector_serves_owner_folder_until_project_binding(
    saved_device, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One signed device-only session transitions after a real binding."""
    import asyncio
    from contextlib import nullcontext

    from kicad_mcp import cloud_windows_connector as connector

    device, _store = saved_device
    state = {"project": None, "calls": 0}
    activity: list[str] = []
    folder = object()
    key = Ed25519PrivateKey.generate()
    monkeypatch.setattr(connector, "selected_project", lambda: state["project"])
    monkeypatch.setattr(boot, "selected_device", lambda: device)
    monkeypatch.setattr(boot, "verified_device_key", lambda _device: key)
    monkeypatch.setattr(boot, "_folder_service", lambda _device: folder)
    monkeypatch.setattr(boot, "owner_connector_instance", lambda **_: nullcontext())

    async def connect(**kwargs: object) -> None:
        assert kwargs["origin"] == device.origin
        assert kwargs["trusted_origin"] == device.origin
        assert kwargs["owner_sub"] == device.owner_sub
        assert kwargs["device_id"] == device.device_id
        assert kwargs["signing_key"] is key
        assert kwargs["folder_service_factory"](object()) is folder
        kwargs["on_ready"](object())
        kwargs["on_activity"]("Folder picker opened")
        state["calls"] += 1
        state["project"] = object()

    monkeypatch.setattr(boot, "execute_owner_folder_only_session", connect)
    asyncio.run(boot.run_device_only(device, status_callback=activity.append))
    assert state["calls"] == 1
    assert activity == [
        "Connecting",
        "Cloud acknowledged this device's signed session",
        "Folder picker opened",
        "Project selected in Cloud; switching to local KiCad MCP tools",
    ]


def test_unbound_connector_retries_network_without_repairing_device(
    saved_device, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A transient socket failure must not delete a credential or open browser approval."""
    import asyncio
    from contextlib import nullcontext

    from kicad_mcp import cloud_windows_connector as connector

    device, store = saved_device
    state = {"project": None, "attempts": 0}
    activity: list[str] = []
    sleeps: list[int] = []
    monkeypatch.setattr(connector, "selected_project", lambda: state["project"])
    monkeypatch.setattr(connector, "_is_remote_policy_rejection", lambda _exc: False)
    monkeypatch.setattr(boot, "selected_device", lambda: device)
    monkeypatch.setattr(boot, "verified_device_key", lambda _device: object())
    monkeypatch.setattr(boot, "owner_connector_instance", lambda **_: nullcontext())
    monkeypatch.setattr(boot, "_folder_service", lambda _device: object())

    async def connect(**_kwargs: object) -> None:
        state["attempts"] += 1
        if state["attempts"] == 1:
            raise OSError("Temporary network outage")
        state["project"] = object()

    async def sleep(delay: int) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(boot, "execute_owner_folder_only_session", connect)
    monkeypatch.setattr(boot.asyncio, "sleep", sleep)
    asyncio.run(boot.run_device_only(device, status_callback=activity.append))
    assert state["attempts"] == 2
    assert sleeps == [3]
    assert "Connection interrupted; retrying" in activity
    assert len(store) == 1, "A network reconnect must not change the owner vault"


def test_unbound_connector_hard_denial_never_retries_or_reapproves(
    saved_device, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio
    from contextlib import nullcontext

    from kicad_mcp import cloud_windows_connector as connector
    from kicad_mcp.cloud_outbound_handshake import CloudHandshakeDeniedError

    device, _store = saved_device
    activity: list[str] = []
    monkeypatch.setattr(connector, "selected_project", lambda: None)
    monkeypatch.setattr(connector, "_is_remote_policy_rejection", lambda _exc: True)
    monkeypatch.setattr(boot, "selected_device", lambda: device)
    monkeypatch.setattr(boot, "verified_device_key", lambda _device: object())
    monkeypatch.setattr(boot, "owner_connector_instance", lambda **_: nullcontext())
    monkeypatch.setattr(boot, "_folder_service", lambda _device: object())

    async def rejected(**_kwargs: object) -> None:
        raise CloudHandshakeDeniedError("owner policy revoked")

    monkeypatch.setattr(boot, "execute_owner_folder_only_session", rejected)
    with pytest.raises(connector.CloudOwnerReapprovalRequiredError):
        asyncio.run(boot.run_device_only(device, status_callback=activity.append))
    assert activity == ["Connecting"]


def test_unbound_connector_rejects_changed_device_identity_before_network(
    saved_device, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio
    from contextlib import nullcontext

    from kicad_mcp import cloud_windows_connector as connector

    device, _store = saved_device
    monkeypatch.setattr(connector, "selected_project", lambda: None)
    monkeypatch.setattr(boot, "selected_device", lambda: None)
    monkeypatch.setattr(boot, "owner_connector_instance", lambda **_: nullcontext())

    async def must_not_connect(**_kwargs: object) -> None:
        pytest.fail("Unverified device must never open a signed socket")

    monkeypatch.setattr(boot, "execute_owner_folder_only_session", must_not_connect)
    with pytest.raises(LocalApprovalDeniedError):
        asyncio.run(boot.run_device_only(device, status_callback=lambda _msg: None))


@pytest.mark.parametrize(
    "malformed",
    [
        b"{" + b'"recordId":"a","recordId":"b"' + b"}",
        b"not-json",
        b'{"recordId":"only-one-field"}',
        b"A" * 1025,
    ],
)
def test_saved_device_marker_rejects_duplicate_malformed_or_oversized_data(
    saved_device, monkeypatch: pytest.MonkeyPatch, malformed: bytes
) -> None:
    device, _store = saved_device
    monkeypatch.setattr(boot, "read_credential", lambda _record, _part: malformed)
    with pytest.raises(LocalApprovalDeniedError):
        boot.selected_device()


def test_saved_device_marker_rejects_invalid_platform_and_fingerprint(
    saved_device, monkeypatch: pytest.MonkeyPatch
) -> None:
    device, store = saved_device
    boot.remember_device(device)
    monkeypatch.setattr(
        boot,
        "inspect_local_binding",
        lambda **_kwargs: SimpleNamespace(fingerprint="0" * 64),
    )
    with pytest.raises(LocalApprovalDeniedError):
        boot.selected_device()
    monkeypatch.setattr(boot, "os", SimpleNamespace(name="posix"))
    with pytest.raises(LocalApprovalDeniedError):
        boot.selected_device()
    with pytest.raises(LocalApprovalDeniedError):
        boot.remember_device(device)
    assert len(store) == 2


def test_saved_device_marker_rejects_post_save_identity_change(
    saved_device, monkeypatch: pytest.MonkeyPatch
) -> None:
    device, store = saved_device
    monkeypatch.setattr(boot, "selected_device", lambda: None)
    with pytest.raises(LocalApprovalDeniedError):
        boot.remember_device(device)
    assert len(store) == 2, "A failed verification is never advertised as paired"


@pytest.mark.parametrize("mode", ["legacy", "bound", "device-only"])
@pytest.mark.parametrize(
    "fault",
    [
        "none",
        "foreign-owner",
        "cancel",
        "stop",
        "switch",
        "crash-active",
        "crash-project",
        "crash-device",
        "crash-selected",
    ],
)
def test_device_repair_archives_without_adding_project(
    saved_device, monkeypatch: pytest.MonkeyPatch, mode: str, fault: str
) -> None:
    from dataclasses import replace

    from kicad_mcp import cloud_windows_connector as connector
    from kicad_mcp import cloud_windows_credentials as credentials
    from kicad_mcp import cloud_windows_enrollment as enrollment

    previous, store = saved_device
    replacement = replace(
        previous, record_id="b" * 32, device_id=str(uuid4()), fingerprint="b" * 64
    )
    if fault == "foreign-owner":
        replacement = replace(replacement, owner_sub="other")
    project = enrollment.WindowsRegisteredProject(
        "c" * 32,
        previous.record_id,
        previous.origin,
        previous.owner_sub,
        previous.device_id,
        previous.fingerprint,
        str(uuid4()),
        "Existing Board",
    )
    device_slot = (boot._DEVICE_SELECTION_SLOT, "selected")
    project_slot = (connector._SELECTED_RECORD_ID, "selected")
    active_slot = (connector._ACTIVE_RECORD_ID, "active")
    if mode != "legacy":
        boot.remember_device(previous)
    if mode != "device-only":
        store[project_slot] = b"previous project"
        store[active_slot] = b"previous active"
    for identity in (previous, replacement):
        store[(identity.record_id, "binding")] = boot._device_marker_payload(identity)
    before = dict(store)
    crash = {"enabled": True}

    def delete(record: str, part: str) -> bool:
        removed = store.pop((record, part), None) is not None
        target = {
            "crash-active": active_slot,
            "crash-project": project_slot,
            "crash-device": device_slot,
        }.get(fault)
        if crash["enabled"] and removed and (record, part) == target:
            raise KeyboardInterrupt
        return removed

    monkeypatch.setattr(credentials, "delete_credential", delete)
    monkeypatch.setattr(
        connector, "selected_project", lambda: project if project_slot in store else None
    )
    monkeypatch.setattr(
        connector,
        "_active",
        lambda: SimpleNamespace(project=project) if active_slot in store else None,
    )
    monkeypatch.setattr(
        boot,
        "inspect_local_binding",
        lambda **kwargs: SimpleNamespace(
            fingerprint=replacement.fingerprint
            if kwargs["record_id"] == replacement.record_id
            else previous.fingerprint
        ),
    )

    def enroll(**kwargs: object) -> WindowsEnrolledDevice:
        assert kwargs["origin"] == previous.origin
        assert kwargs["recovery_device_id"] == previous.device_id
        assert kwargs["recovery_owner_sub"] == previous.owner_sub
        kwargs["owner_approval"]("https://cloud.example/pair", "challenge", "code")
        if fault == "cancel":
            raise LocalApprovalDeniedError("cancelled")
        return replacement

    monkeypatch.setattr(enrollment, "enroll_windows_device", enroll)
    monkeypatch.setattr(
        enrollment,
        "register_windows_project",
        lambda *_args, **_kwargs: pytest.fail("device repair must not register any project"),
    )
    original_create = boot.create_credential

    def create(record, part, data):
        if (
            fault == "switch"
            and (record, part) == device_slot
            and data == boot._device_marker_payload(replacement)
        ):
            raise OSError("failed to save new marker")
        original_create(record, part, data)
        if (
            crash["enabled"]
            and fault == "crash-selected"
            and (record, part) == device_slot
            and data == boot._device_marker_payload(replacement)
        ):
            raise KeyboardInterrupt

    monkeypatch.setattr(boot, "create_credential", create)
    approval_events = []
    options = dict(
        origin=previous.origin,
        alias="PC",
        approval=lambda *_: approval_events.append("browser"),
        stop_previous=lambda: fault != "stop",
    )
    if fault.startswith("crash"):
        target_exists = (
            fault == "crash-selected"
            or (fault == "crash-device" and mode != "legacy")
            or (fault in {"crash-active", "crash-project"} and mode != "device-only")
        )
        if not target_exists:
            pytest.skip("marker does not exist in this mode")
        with pytest.raises(KeyboardInterrupt):
            boot.repair_device_only(**options)
        crash["enabled"] = False
        journal = store[(device_slot[0], "recovery_switch")]
        # A foreign edit must not be removed or partially applied.
        old = store.get(project_slot)
        store[project_slot] = b"foreign project"
        before_resume = dict(store)
        with pytest.raises(LocalApprovalDeniedError):
            boot.resume_device_switch(previous.origin)
        assert store == before_resume
        if old is None:
            store.pop(project_slot)
        else:
            store[project_slot] = old
        assert store[(device_slot[0], "recovery_switch")] == journal
        assert boot.resume_device_switch(previous.origin)
        assert boot.selected_device() == replacement
        assert project_slot not in store
        assert active_slot not in store
        assert not boot.resume_device_switch(previous.origin)
    elif fault != "none":
        with pytest.raises((OSError, LocalApprovalDeniedError)):
            boot.repair_device_only(**options)
        for slot in (device_slot, project_slot, active_slot):
            assert store.get(slot) == before.get(slot)
    else:
        assert boot.repair_device_only(**options) == replacement
        assert boot.selected_device() == replacement
        assert project_slot not in store
        assert active_slot not in store
        for slot, archive in (
            (device_slot, "archived_device_selected"),
            (project_slot, "archived_selected"),
            (active_slot, "archived_active"),
        ):
            if slot in before:
                assert store[(replacement.record_id, archive)] == before[slot]
    assert store[(previous.record_id, "key")] == before[(previous.record_id, "key")]
    assert approval_events == ["browser"]
    assert not any(part == "registration" for _, part in store)


@pytest.mark.parametrize("fault", ["none", "crash", "foreign", "stop"])
def test_detach_deleted_project_retains_device_and_archives(
    saved_device, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    from kicad_mcp import cloud_windows_connector as connector
    from kicad_mcp import cloud_windows_credentials as credentials
    from kicad_mcp.cloud_windows_enrollment import WindowsRegisteredProject

    device, store = saved_device
    boot.remember_device(device)
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
    selected = (connector._SELECTED_RECORD_ID, "selected")
    active = (connector._ACTIVE_RECORD_ID, "active")
    store[selected] = b"selected project"
    store[active] = b"active project"
    key = store[(device.record_id, "key")]
    store[(project.registration_id, "registration")] = b"saved registration"
    monkeypatch.setattr(
        connector, "selected_project", lambda: project if selected in store else None
    )
    monkeypatch.setattr(
        connector, "_active", lambda: SimpleNamespace(project=project) if active in store else None
    )
    crash = fault == "crash"

    def delete(record: str, part: str) -> bool:
        nonlocal crash
        removed = store.pop((record, part), None) is not None
        if crash and (record, part) == active:
            crash = False
            raise KeyboardInterrupt
        return removed

    monkeypatch.setattr(credentials, "delete_credential", delete)
    if fault == "foreign":
        store[(project.registration_id, "detached_selected")] = b"foreign"
    if fault in {"foreign", "stop"}:
        with pytest.raises(LocalApprovalDeniedError):
            boot.detach_missing_project(device, project, lambda: fault != "stop")
        assert store[selected] == b"selected project"
        assert store[active] == b"active project"
    else:
        if fault == "crash":
            with pytest.raises(KeyboardInterrupt):
                boot.detach_missing_project(device, project, lambda: True)
            assert selected in store
            assert active not in store
        boot.detach_missing_project(device, project, lambda: True)
        assert selected not in store
        assert active not in store
        assert store[(project.registration_id, "detached_selected")] == b"selected project"
        assert store[(project.registration_id, "detached_active")] == b"active project"
    assert boot.selected_device() == device
    assert store[(device.record_id, "key")] == key
    assert store[(project.registration_id, "registration")] == b"saved registration"


@pytest.mark.parametrize("state", ["active", "project_missing", "project_disabled", "unavailable"])
def test_restore_existing_secondary_uses_same_device_without_picker(
    saved_device, monkeypatch, tmp_path, state
) -> None:
    from kicad_mcp import cloud_windows_connector as connector
    from kicad_mcp import cloud_windows_scoped_projects as scoped
    from kicad_mcp.cloud_readonly_boundary import OperatorProject

    device, _ = saved_device
    boot.remember_device(device)
    monkeypatch.setattr(connector, "selected_project", lambda: None)
    board = tmp_path / "board"
    board.mkdir()
    file = board / "board.kicad_pro"
    file.touch()
    pid = str(uuid4())
    target = OperatorProject(device.device_id, pid, board, "board")
    monkeypatch.setattr(scoped, "existing_targets", lambda _: [target])
    monkeypatch.setattr(scoped, "resolve", lambda *_: target)
    monkeypatch.setattr(
        "kicad_mcp.cloud_device_inventory_status.inspect_inventory", lambda *_: state
    )
    events = []

    def adopt(identity, project_id, chosen):
        events.append((identity, project_id, chosen))
        return True

    monkeypatch.setattr(boot, "adopt_browser_project", adopt)
    assert boot.restore_existing_project(device) == (state == "active")
    assert events == ([(device, pid, file)] if state == "active" else [])


@pytest.mark.asyncio
async def test_device_only_update_drain_preserves_windows_identity(
    saved_device, monkeypatch
) -> None:
    import asyncio
    from contextlib import nullcontext

    from kicad_mcp import cloud_windows_connector as connector

    device, _ = saved_device
    monkeypatch.setattr(connector, "selected_project", lambda: None)
    monkeypatch.setattr(boot, "selected_device", lambda: device)
    monkeypatch.setattr(boot, "verified_device_key", lambda _: Ed25519PrivateKey.generate())
    monkeypatch.setattr(boot, "owner_connector_instance", lambda **_: nullcontext())
    drain = asyncio.Event()
    calls = []
    activity = []

    async def session(**kwargs: object) -> None:
        assert kwargs["drain"] is drain
        calls.append("socket")
        drain.set()

    monkeypatch.setattr(boot, "execute_owner_folder_only_session", session)
    await asyncio.wait_for(
        boot.run_device_only(device, status_callback=activity.append, drain=drain), 2
    )
    assert calls == ["socket"]
    assert activity == ["Connecting"]
    assert boot.selected_device() == device


@pytest.mark.parametrize(
    "fault",
    [
        "none",
        "journal",
        "missing-binding",
        "foreign-origin",
        "foreign-owner",
        "fingerprint",
        "archives",
        "hash",
        "stop",
        "delete-refused",
        "pending-tamper",
        "pending-delete-refused",
        "journal-delete-refused",
    ],
)
def test_resume_switch_verifies_journal_and_archives_before_mutating(
    saved_device, monkeypatch, fault
) -> None:
    from dataclasses import replace

    from kicad_mcp import cloud_windows_connector as connector
    from kicad_mcp import cloud_windows_credentials as credentials

    previous, store = saved_device
    replacement = replace(
        previous, record_id="b" * 32, device_id=str(uuid4()), fingerprint="b" * 64
    )
    boot.remember_device(previous)
    selected = (boot._DEVICE_SELECTION_SLOT, "selected")
    journal_slot = (boot._DEVICE_SELECTION_SLOT, "recovery_switch")
    archives = {}
    for slot, part, archive in boot._switch_slots():
        old = store.get((slot, part))
        archives[archive] = hashlib.sha256(old).hexdigest() if old is not None else None
        if old is not None:
            store[replacement.record_id, archive] = old
    if fault == "foreign-origin":
        replacement = replace(replacement, origin="https://foreign.example")
    elif fault == "foreign-owner":
        replacement = replace(replacement, owner_sub="foreign")
    for identity in (previous, replacement):
        store[identity.record_id, "binding"] = boot._device_marker_payload(identity)
    if fault == "missing-binding":
        store.pop((replacement.record_id, "binding"))
    if fault == "archives":
        archives.pop("archived_active")
    if fault == "hash":
        store[replacement.record_id, "archived_device_selected"] = b"tampered"
    journal = {
        "previous": previous.record_id,
        "replacement": replacement.record_id,
        "archives": archives,
    }
    store[journal_slot] = b"[]" if fault == "journal" else json.dumps(journal).encode()
    pending = (previous.record_id, "recovery_pending")
    store[pending] = json.dumps(
        {"recordId": replacement.record_id if fault != "pending-tamper" else "foreign"}
    ).encode()

    def inspect(**kwargs: object):
        fingerprint = (
            previous.fingerprint
            if kwargs["record_id"] == previous.record_id
            else replacement.fingerprint
        )
        return SimpleNamespace(fingerprint="0" * 64 if fault == "fingerprint" else fingerprint)

    monkeypatch.setattr(boot, "inspect_local_binding", inspect)
    monkeypatch.setattr(connector, "selected_project", lambda: None)
    monkeypatch.setattr(
        credentials,
        "delete_credential",
        lambda slot, part: (
            False
            if (slot, part)
            == {
                "delete-refused": selected,
                "pending-delete-refused": pending,
                "journal-delete-refused": journal_slot,
            }.get(fault)
            else store.pop((slot, part), None) is not None
        ),
    )
    before = store.copy()
    assert boot.owner_recovery_pending()
    if fault == "none":
        assert boot.resume_owner_recovery(previous.origin, lambda: True)
        assert store[selected] == boot._device_marker_payload(replacement)
        assert journal_slot not in store
        assert pending not in store
    else:
        with pytest.raises(LocalApprovalDeniedError):
            boot.resume_device_switch(previous.origin, stop_previous=lambda: fault != "stop")
        if fault in {"pending-tamper", "pending-delete-refused", "journal-delete-refused"}:
            assert store[selected] == boot._device_marker_payload(replacement)
            assert store[journal_slot] == before[journal_slot]
            if fault != "journal-delete-refused":
                assert store[pending] == before[pending]
        else:
            assert store == before


@pytest.mark.parametrize("pending", [False, True])
def test_resume_owner_recovery_never_opens_new_approval(saved_device, monkeypatch, pending) -> None:
    from kicad_mcp import cloud_windows_connector as connector

    device, store = saved_device
    boot.remember_device(device)
    monkeypatch.setattr(connector, "selected_project", lambda: None)
    if pending:
        store[device.record_id, "recovery_pending"] = b"approved"
    events = []

    def repair(**kwargs: object) -> None:
        events.append(kwargs["alias"])
        with pytest.raises(LocalApprovalDeniedError):
            kwargs["approval"]("page", "challenge", "code")

    monkeypatch.setattr(boot, "repair_device_only", repair)
    assert boot.owner_recovery_pending() is pending
    assert boot.resume_owner_recovery(device.origin, lambda: True) is pending
    assert events == (["Recovery"] if pending else [])


@pytest.mark.asyncio
async def test_official_device_only_migrates_scoped_legacy_selection_before_socket(
    saved_device, monkeypatch, tmp_path
) -> None:
    import asyncio
    from contextlib import nullcontext
    from dataclasses import replace

    from kicad_mcp import cloud_windows_connector as connector
    from kicad_mcp import cloud_windows_scoped_projects as scoped
    from kicad_mcp.cloud_windows_write_issuer import _KICAD_CLOUD_ORIGIN

    device, _ = saved_device
    device = replace(device, origin=_KICAD_CLOUD_ORIGIN)
    monkeypatch.setattr(boot, "owner_connector_instance", lambda **_: nullcontext())
    monkeypatch.setattr(boot, "selected_device", lambda: device)
    monkeypatch.setattr(connector, "selected_project", lambda: None)
    key = Ed25519PrivateKey.generate()
    monkeypatch.setattr(boot, "verified_device_key", lambda _: key)
    pid = str(uuid4())
    monkeypatch.setattr(
        "kicad_mcp.cloud_legacy_project_migration.legacy_candidates",
        lambda: {pid: tmp_path / "board.kicad_pro"},
    )
    calls = []

    def migrate(identity, signing_key, authorized, primary):
        assert identity == device
        assert signing_key is key
        assert authorized()
        assert primary is None
        calls.append("migration")
        return 1

    monkeypatch.setattr(scoped, "migrate_legacy", migrate)
    monkeypatch.setattr(boot, "restore_existing_project", lambda _: calls.append("restore") or True)

    async def no_socket(**kwargs: object) -> None:
        pytest.fail("restored project must not start folder-only socket")

    monkeypatch.setattr(boot, "execute_owner_folder_only_session", no_socket)
    drain = asyncio.Event()
    activity = []
    await boot.run_device_only(device, status_callback=activity.append, drain=drain)
    assert calls == ["migration", "restore"]
    assert activity == ["Restored an existing Cloud project on this device."]
    drain.set()
    await boot.run_device_only(device, status_callback=activity.append, drain=drain)
    assert calls == ["migration", "restore"]
