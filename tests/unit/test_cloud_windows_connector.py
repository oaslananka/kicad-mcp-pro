"""Windows current-user local Connector core tests; no live tasks or HTTP."""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

from kicad_mcp import cloud_windows_connector as connector
from kicad_mcp.cloud_outbound_handshake import HandshakeReceipt
from kicad_mcp.cloud_pair_keys import LocalApprovalDeniedError
from kicad_mcp.cloud_windows_enrollment import WindowsRegisteredProject
from kicad_mcp.cloud_windows_local_selection import WindowsLocalProjectSelection


@pytest.fixture
def local_user_connector(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> tuple[WindowsRegisteredProject, dict[tuple[str, str], bytes], Path]:
    directory = tmp_path / "board"
    directory.mkdir()
    (directory / "demo.kicad_pro").touch()

    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
    fingerprint = hashlib.sha256(public).hexdigest()
    project = WindowsRegisteredProject(
        registration_id="a" * 32,
        record_id="b" * 32,
        origin="https://cloud.example",
        owner_sub="provider|owner-42",
        device_id="19ee4be9-0aec-448e-9873-721ae113ec02",
        fingerprint=fingerprint,
        project_id="29ee4be9-0aec-448e-9873-721ae113ec02",
        filename_stem="demo",
    )
    selected = WindowsLocalProjectSelection(
        registration_id=project.registration_id,
        record_id=project.record_id,
        device_id=project.device_id,
        project_id=project.project_id,
        filename_stem=project.filename_stem,
        directory=directory,
    )
    record = {
        "registrationId": project.registration_id,
        "recordId": project.record_id,
        "origin": project.origin,
        "ownerSub": project.owner_sub,
        "deviceId": project.device_id,
        "fingerprint": project.fingerprint,
        "projectId": project.project_id,
        "filenameStem": project.filename_stem,
    }
    store: dict[tuple[str, str], bytes] = {
        (project.registration_id, "registration"): json.dumps(record).encode(),
        (project.record_id, "key"): key.private_bytes(
            Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()
        ),
    }
    monkeypatch.setattr(connector, "os", SimpleNamespace(name="nt"))

    def read(record_id: str, part: str) -> bytes | None:
        return store.get((record_id, part))

    def create(record_id: str, part: str, value: bytes) -> None:
        if (record_id, part) in store:
            raise LocalApprovalDeniedError("duplicate")
        store[(record_id, part)] = value

    def delete(record_id: str, part: str) -> bool:
        return store.pop((record_id, part), None) is not None

    monkeypatch.setattr(connector, "read_credential", read)
    monkeypatch.setattr(connector, "create_credential", create)
    monkeypatch.setattr(connector, "delete_credential", delete)
    monkeypatch.setattr(
        connector,
        "inspect_project_reference",
        lambda **_kwargs: SimpleNamespace(fingerprint=project.fingerprint),
    )
    monkeypatch.setattr(connector, "inspect_owner_selected_project", lambda _: selected)
    return project, store, directory


def test_local_default_off_and_owner_cancel_never_enables(
    local_user_connector,
) -> None:
    project, store, _path = local_user_connector
    assert connector.local_state() == "Off"
    assert connector._active() is None
    with pytest.raises(LocalApprovalDeniedError, match="owner declined"):
        connector.activate(project, owner_confirm=lambda _: False)
    assert connector.local_state() == "Off"
    assert (connector._ACTIVE_RECORD_ID, "active") not in store


def test_activation_is_only_local_configuration_not_remote_connection(
    local_user_connector,
) -> None:
    project, store, _ = local_user_connector
    connector.activate(project, owner_confirm=lambda _: True)
    assert connector.local_state() == "Configured (not connected)"
    active = connector._active()
    assert active is not None
    assert active.project == project
    assert active.selected.project_id == project.project_id
    assert connector._current_authorization(project) is True
    with pytest.raises(LocalApprovalDeniedError):
        connector.activate(project, owner_confirm=lambda _: True)
    assert connector.deactivate() is True
    assert connector.local_state() == "Off"
    assert connector._current_authorization(project) is False
    assert connector.deactivate() is False


def test_corrupt_or_unrelated_active_marker_denies(
    local_user_connector,
) -> None:
    project, store, _ = local_user_connector
    key = (connector._ACTIVE_RECORD_ID, "active")
    store[key] = b'{"deviceId":"a","deviceId":"b"}'
    with pytest.raises(LocalApprovalDeniedError):
        connector._active()
    assert connector.local_state() == "Unavailable"
    store[key] = json.dumps(
        {
            "registrationId": project.registration_id,
            "recordId": project.record_id,
            "deviceId": project.device_id,
            "projectId": "39ee4be9-0aec-448e-9873-721ae113ec02",
        }
    ).encode()
    with pytest.raises(LocalApprovalDeniedError):
        connector._active()
    assert connector.local_state() == "Unavailable"


@pytest.mark.asyncio
async def test_managed_windows_session_uses_signed_outbound_readonly_dispatch(
    local_user_connector,
) -> None:
    project, _store, folder = local_user_connector
    connector.activate(project, owner_confirm=lambda _: True)
    stop = asyncio.Event()
    session_id = "39ee4be9-0aec-448e-9873-721ae113ec02"
    captured: list[dict[str, object]] = []

    async def fake_session(**kwargs: object) -> HandshakeReceipt:
        assert kwargs["origin"] == "https://cloud.example"
        assert kwargs["trusted_origin"] == "https://cloud.example"
        assert kwargs["device_id"] == project.device_id
        assert kwargs["owner_sub"] == project.owner_sub
        assert isinstance(kwargs["signing_key"], Ed25519PrivateKey)
        assert kwargs["max_reads"] == 16
        dispatch = kwargs["dispatcher_factory"](
            HandshakeReceipt(device_id=project.device_id, session_id=session_id)
        )
        assert dispatch.native_drc is False
        assert dispatch._project.directory == folder
        assert dispatch._verified.operations == frozenset({"project_summary"})
        captured.append({"session": session_id})
        stop.set()
        return HandshakeReceipt(device_id=project.device_id, session_id=session_id)

    await asyncio.wait_for(connector.run_connector(stop=stop, session_runner=fake_session), 5)
    assert captured == [{"session": session_id}]


@pytest.mark.asyncio
async def test_deactivation_cancels_running_session_without_cloud_access(
    local_user_connector,
) -> None:
    project, _store, _ = local_user_connector
    connector.activate(project, owner_confirm=lambda _: True)
    stop = asyncio.Event()
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def fake_session(**kwargs: object) -> HandshakeReceipt:
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise
        raise AssertionError("must never complete")

    async def revoke() -> None:
        await started.wait()
        assert connector.deactivate() is True

    await asyncio.wait_for(
        asyncio.gather(connector.run_connector(stop=stop, session_runner=fake_session), revoke()),
        5,
    )
    assert cancelled.is_set()
    assert connector.local_state() == "Off"


@pytest.mark.asyncio
async def test_stop_cancels_running_session_without_changing_vault(
    local_user_connector,
) -> None:
    project, store, _ = local_user_connector
    connector.activate(project, owner_confirm=lambda _: True)
    stop = asyncio.Event()
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def fake_session(**kwargs: object) -> HandshakeReceipt:
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise
        raise AssertionError("must never complete")

    async def signal_stop() -> None:
        await started.wait()
        stop.set()

    await asyncio.wait_for(
        asyncio.gather(
            connector.run_connector(stop=stop, session_runner=fake_session),
            signal_stop(),
        ),
        5,
    )
    assert cancelled.is_set()
    assert (connector._ACTIVE_RECORD_ID, "active") in store


@pytest.mark.asyncio
async def test_inactive_windows_connector_never_opens_socket(
    local_user_connector,
) -> None:
    _project, _store, _ = local_user_connector
    stop = asyncio.Event()

    async def no_call(**_kwargs: object) -> HandshakeReceipt:
        raise AssertionError("No socket while Off")

    await asyncio.wait_for(connector.run_connector(stop=stop, session_runner=no_call), 3)


def test_remembered_project_survives_local_off_without_remote_access(
    local_user_connector,
) -> None:
    project, store, _folder = local_user_connector
    assert connector.selected_project() is None
    connector.remember_selected_project(project)
    assert connector.selected_project() == project
    assert connector.local_state() == "Off"
    assert connector._active() is None
    assert connector.deactivate() is False
    assert connector.selected_project() == project
    assert (connector._SELECTED_RECORD_ID, "selected") in store


def test_selected_project_cannot_be_replaced_silently(
    local_user_connector,
) -> None:
    project, store, _folder = local_user_connector
    connector.remember_selected_project(project)
    before = store[(connector._SELECTED_RECORD_ID, "selected")]
    with pytest.raises(LocalApprovalDeniedError):
        connector.remember_selected_project(project)
    assert store[(connector._SELECTED_RECORD_ID, "selected")] == before


def test_tampered_selected_project_fails_without_auto_pairing(
    local_user_connector,
) -> None:
    project, store, _folder = local_user_connector
    connector.remember_selected_project(project)
    key = (connector._SELECTED_RECORD_ID, "selected")
    store[key] = b'{"deviceId":"x","deviceId":"y"}'
    with pytest.raises(LocalApprovalDeniedError):
        connector.selected_project()
    assert connector.local_state() == "Off"


def test_connector_rejects_corrupt_vault_records_and_missing_identity(
    local_user_connector, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, vault, _directory = local_user_connector
    active_key = (connector._ACTIVE_RECORD_ID, "active")
    selected_key = (connector._SELECTED_RECORD_ID, "selected")
    valid_marker = {
        "registrationId": project.registration_id,
        "recordId": project.record_id,
        "deviceId": project.device_id,
        "projectId": project.project_id,
    }
    for malformed in [b"x" * 1025, b'{"deviceId":"bad"}', b"[]"]:
        vault[active_key] = malformed
        with pytest.raises(LocalApprovalDeniedError):
            connector._active_marker()
    vault[active_key] = json.dumps(valid_marker).encode()
    registration = vault.pop((project.registration_id, "registration"))
    with pytest.raises(LocalApprovalDeniedError):
        connector._active()
    vault[(project.registration_id, "registration")] = registration
    vault[(project.registration_id, "registration")] = b"x" * 2049
    with pytest.raises(LocalApprovalDeniedError):
        connector._active()
    vault[(project.registration_id, "registration")] = registration
    monkeypatch.setattr(
        connector, "inspect_project_reference", lambda **_kw: SimpleNamespace(fingerprint="bad")
    )
    with pytest.raises(LocalApprovalDeniedError):
        connector._active()
    monkeypatch.setattr(
        connector,
        "inspect_project_reference",
        lambda **_kw: SimpleNamespace(fingerprint=project.fingerprint),
    )

    for malformed in [b"x" * 1025, b'{"deviceId":"bad"}', b"[]"]:
        vault[selected_key] = malformed
        with pytest.raises(LocalApprovalDeniedError):
            connector.selected_project()
    vault.pop(selected_key)
    assert connector.selected_project() is None


def test_connector_rejects_missing_or_mismatched_private_keys(
    local_user_connector,
) -> None:
    project, vault, _directory = local_user_connector
    connector.activate(project, owner_confirm=lambda _: True)
    key_id = (project.record_id, "key")
    valid = vault.pop(key_id)
    with pytest.raises(LocalApprovalDeniedError):
        connector._active()
    vault[key_id] = valid
    replacement = Ed25519PrivateKey.generate()
    vault[key_id] = replacement.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
    with pytest.raises(LocalApprovalDeniedError):
        connector._active()


def test_connector_denies_invalid_owner_selection_or_dispatch(
    local_user_connector, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, _vault, directory = local_user_connector
    with pytest.raises(LocalApprovalDeniedError):
        connector.remember_selected_project(object())  # type: ignore[arg-type]
    with pytest.raises(LocalApprovalDeniedError):
        connector.activate(object(), owner_confirm=lambda _: True)  # type: ignore[arg-type]
    selected = WindowsLocalProjectSelection(
        registration_id=project.registration_id,
        record_id=project.record_id,
        device_id=project.device_id,
        project_id="different-project",
        filename_stem=project.filename_stem,
        directory=directory,
    )
    monkeypatch.setattr(connector, "inspect_owner_selected_project", lambda _: selected)
    with pytest.raises(LocalApprovalDeniedError):
        connector.activate(project, owner_confirm=lambda _: True)

    receipt = HandshakeReceipt(device_id="wrong-device", session_id="session")
    with pytest.raises(LocalApprovalDeniedError):
        connector._dispatcher(project, selected, receipt)
    monkeypatch.setattr(connector, "_active", lambda: (_ for _ in ()).throw(OSError("vault")))
    assert connector._current_authorization(project) is False


def test_connector_posix_guards_remain_fail_closed(
    local_user_connector, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, _vault, _directory = local_user_connector
    monkeypatch.setattr(connector, "os", SimpleNamespace(name="posix"))
    with pytest.raises(LocalApprovalDeniedError):
        connector._active_marker()
    with pytest.raises(LocalApprovalDeniedError):
        connector.selected_project()
    with pytest.raises(LocalApprovalDeniedError):
        connector.remember_selected_project(project)
    with pytest.raises(LocalApprovalDeniedError):
        connector.activate(project, owner_confirm=lambda _: True)
    with pytest.raises(LocalApprovalDeniedError):
        connector.deactivate()
    assert connector.local_state() == "Unavailable"


@pytest.mark.asyncio
async def test_connector_refuses_non_windows_session_before_socket(
    local_user_connector, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(connector, "os", SimpleNamespace(name="posix"))

    async def unreachable(**_kwargs: object) -> HandshakeReceipt:
        raise AssertionError("must not open a Cloud session")

    with pytest.raises(LocalApprovalDeniedError):
        await connector.run_connector(stop=asyncio.Event(), session_runner=unreachable)


def test_connector_scheduled_entrypoint_requires_local_marker(
    local_user_connector, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    project, _vault, _directory = local_user_connector
    assert connector.main(["run"]) == 2
    assert "Off" in capsys.readouterr().err
    connector.activate(project, owner_confirm=lambda _: True)

    def fake_run(task: object) -> None:
        task.close()

    monkeypatch.setattr(connector.asyncio, "run", fake_run)
    assert connector.main(["run"]) == 0

    def stopped(task: object) -> None:
        task.close()
        raise KeyboardInterrupt

    monkeypatch.setattr(connector.asyncio, "run", stopped)
    assert connector.main(["run"]) == 0


@pytest.mark.asyncio
async def test_connector_retries_transient_session_failures_and_cancels(
    local_user_connector, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, _vault, _directory = local_user_connector
    connector.activate(project, owner_confirm=lambda _: True)
    stop = asyncio.Event()
    calls: list[str] = []
    monkeypatch.setattr(connector, "reconnect_delay_seconds", lambda *_args: 0)

    async def unstable(**_kwargs: object) -> HandshakeReceipt:
        calls.append("attempt")
        if len(calls) == 1:
            raise OSError("transient socket failure")
        stop.set()
        return HandshakeReceipt(device_id=project.device_id, session_id="session")

    await asyncio.wait_for(connector.run_connector(stop=stop, session_runner=unstable), 3)
    assert len(calls) == 2
