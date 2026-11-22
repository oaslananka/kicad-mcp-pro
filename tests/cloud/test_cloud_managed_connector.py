"""Local owner-managed Connector lifecycle stays default-off and project-scoped."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import stat
import subprocess
import threading
import time
from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from kicad_mcp import cloud_managed_connector as connector
from kicad_mcp.cloud_local_registry import LocalRegisteredRead
from kicad_mcp.cloud_outbound_handshake import HandshakeReceipt
from kicad_mcp.cloud_pair_keys import LocalApprovalDeniedError, _unique
from kicad_mcp.cloud_read_dispatch import LocalReadDispatch
from kicad_mcp.cloud_readonly_boundary import LocalReadDeniedError, inspect_readonly

pytestmark = pytest.mark.skipif(os.name != "posix", reason="Systemd user connector is POSIX-only")

DEVICE = "11111111-1111-4111-8111-111111111111"
PROJECT = "22222222-2222-4222-8222-222222222222"
SESSION = "33333333-3333-4333-8333-333333333333"
RECORD = {
    "ownerSub": "fixture-owner",
    "cloudOrigin": "https://cloud.example",
    "deviceId": DEVICE,
    "projectId": PROJECT,
}


def _root(tmp_path: Path) -> tuple[Path, LocalRegisteredRead]:
    root = tmp_path / "registry"
    root.mkdir(mode=0o700)
    (root / "projects").mkdir(mode=0o700)
    (root / "keys").mkdir(mode=0o700)
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    key = root / "keys" / f"{DEVICE}.pem"
    key.write_text("synthetic-key")
    key.chmod(0o600)
    record = {
        **RECORD,
        "keySlot": DEVICE,
        "directory": str(project_dir),
        "filenameStem": "board",
    }
    project_record = root / "projects" / f"{PROJECT}.json"
    project_record.write_text(json.dumps(record))
    project_record.chmod(0o600)
    return root, LocalRegisteredRead(key, project_dir, "board")


def test_status_is_off_by_default_without_touching_registration(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "registry"
    root.mkdir(mode=0o700)
    monkeypatch.setattr(connector, "default_registry_root", lambda: root)
    monkeypatch.setattr(
        connector,
        "_single_registered_identity",
        lambda _root: pytest.fail("Off status must not inspect the owner registration"),
    )
    assert connector.main(["status"]) == 0
    assert capsys.readouterr().out.strip() == "Off"


@pytest.mark.anyio
async def test_run_is_default_off_before_key_load_or_identity_lookup(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = tmp_path / "registry"
    root.mkdir(mode=0o700)
    monkeypatch.setattr(
        connector,
        "_single_registered_identity",
        lambda _root: pytest.fail("disabled service must not inspect identity"),
    )
    monkeypatch.setattr(
        connector,
        "_load_bound_owner_key",
        lambda *_args: pytest.fail("disabled service must not load a signing key"),
    )
    assert await connector._run_connector(root=root) == 0


def test_enable_record_is_private_and_bound_to_one_existing_identity(tmp_path: Path) -> None:
    root, _project = _root(tmp_path)
    connector._write_private_json(root, connector._ENABLED_FILE, connector._identity_state(RECORD))
    marker = root / connector._ENABLED_FILE
    assert stat.S_IMODE(marker.stat().st_mode) == 0o600
    assert connector._enabled_record(root) == connector._identity_state(RECORD)


def test_corrupt_or_symlinked_enable_record_fails_closed(tmp_path: Path) -> None:
    root, _project = _root(tmp_path)
    marker = root / connector._ENABLED_FILE
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps(connector._identity_state(RECORD)))
    marker.symlink_to(outside)
    assert connector._enabled_record(root) is None
    marker.unlink()
    marker.write_text(json.dumps({**connector._identity_state(RECORD), "extra": True}))
    marker.chmod(0o600)
    assert connector._enabled_record(root) is None


def test_disable_removes_local_authority_before_stopping_service(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root, _project = _root(tmp_path)
    connector._write_private_json(root, connector._ENABLED_FILE, connector._identity_state(RECORD))
    monkeypatch.setattr(connector, "default_registry_root", lambda: root)
    calls: list[tuple[str, ...]] = []

    def systemctl(*args: str) -> subprocess.CompletedProcess[str]:
        assert not (root / connector._ENABLED_FILE).exists()
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(connector, "_systemctl", systemctl)
    assert connector.main(["disable"]) == 0
    assert calls == [("disable", "--now", connector._SERVICE_NAME)]
    assert "Off" in capsys.readouterr().out


def test_enable_rolls_back_local_marker_when_service_start_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root, _project = _root(tmp_path)
    monkeypatch.setattr(connector, "default_registry_root", lambda: root)
    monkeypatch.setattr(connector, "_single_registered_identity", lambda _root: RECORD.copy())
    monkeypatch.setattr(connector, "_install_user_service", lambda: None)
    monkeypatch.setattr(
        connector,
        "_systemctl",
        lambda *args: subprocess.CompletedProcess(args, 1, "", "user manager unavailable"),
    )
    assert connector.main(["enable"]) == 1
    assert not (root / connector._ENABLED_FILE).exists()


def test_disable_stops_service_even_when_registry_permissions_are_broken(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root, _project = _root(tmp_path)
    connector._write_private_json(root, connector._ENABLED_FILE, connector._identity_state(RECORD))
    root.chmod(0o755)
    monkeypatch.setattr(connector, "default_registry_root", lambda: root)
    calls: list[tuple[str, ...]] = []

    def systemctl(*args: str) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(connector, "_systemctl", systemctl)
    assert connector.main(["disable"]) == 1
    assert calls == [("disable", "--now", connector._SERVICE_NAME)]
    assert (root / connector._ENABLED_FILE).exists()


def test_disable_is_idempotent_when_service_was_never_installed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root, _project = _root(tmp_path)
    monkeypatch.setattr(connector, "default_registry_root", lambda: root)
    calls: list[tuple[str, ...]] = []

    def systemctl(*args: str) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        if args[0] == "disable":
            return subprocess.CompletedProcess(args, 4, "", "Unit not found")
        return subprocess.CompletedProcess(args, 4, "unknown", "")

    monkeypatch.setattr(connector, "_systemctl", systemctl)
    assert connector.main(["disable"]) == 0
    assert calls == [
        ("disable", "--now", connector._SERVICE_NAME),
        ("is-active", connector._SERVICE_NAME),
    ]


def test_enable_installs_only_the_expected_user_scoped_unit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root, _project = _root(tmp_path)
    service = tmp_path / "config" / "systemd" / "user" / connector._SERVICE_NAME
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(connector, "default_registry_root", lambda: root)
    monkeypatch.setattr(connector, "_single_registered_identity", lambda _root: RECORD.copy())
    monkeypatch.setattr(connector, "_service_path", lambda: service)

    def systemctl(*args: str) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(connector, "_systemctl", systemctl)
    connector._install_user_service()
    unit = service.read_text()
    assert "Restart=on-failure" in unit
    assert "RestartSec=30s" in unit
    assert "UMask=0077" in unit
    assert "NoNewPrivileges=true" in unit
    assert "cloud_managed_connector run" in unit
    assert calls == [("daemon-reload",)]


def test_existing_unrelated_user_unit_is_never_overwritten(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root, _project = _root(tmp_path)
    service = tmp_path / "config" / "systemd" / "user" / connector._SERVICE_NAME
    service.parent.mkdir(parents=True, mode=0o700)
    service.write_text("[Service]\nExecStart=/bin/false\n")
    monkeypatch.setattr(connector, "default_registry_root", lambda: root)
    monkeypatch.setattr(connector, "_service_path", lambda: service)
    monkeypatch.setattr(
        connector,
        "_systemctl",
        lambda *_args: pytest.fail("do not reload a conflicting unit"),
    )
    with pytest.raises(LocalApprovalDeniedError):
        connector._install_user_service()
    assert service.read_text() == "[Service]\nExecStart=/bin/false\n"


def test_dispatcher_is_project_summary_only_and_tracks_local_off(
    tmp_path: Path,
) -> None:
    root, project = _root(tmp_path)
    connector._write_private_json(root, connector._ENABLED_FILE, connector._identity_state(RECORD))
    factory = connector._dispatcher_factory(root, RECORD, project)
    dispatcher = factory(HandshakeReceipt(DEVICE, SESSION))
    assert dispatcher.native_drc is False
    assert dispatcher._max_reads == connector._MAX_READS
    dispatcher._authorize_now()
    connector._remove_private_file(root, connector._ENABLED_FILE)
    with pytest.raises(LocalReadDeniedError):
        dispatcher._authorize_now()


def test_posix_cloud_device_bound_second_project_is_readable_then_revocable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The project the owner added on Devices must actually work, and revoke."""
    from kicad_mcp.cloud_folder_browse_receiver import device_folder_service, handle_folder_frame

    root, project = _root(tmp_path)
    (project.project_directory / "board.kicad_pro").write_text("{}", encoding="utf-8")
    record = json.loads((root / "projects" / f"{PROJECT}.json").read_text())
    chosen = tmp_path / "owner-selected"
    chosen.mkdir()
    (chosen / "new.kicad_pro").write_text("{}", encoding="utf-8")
    new_project = "44444444-4444-4444-8444-444444444444"
    bindings_file = tmp_path / "folder-bindings.json"
    monkeypatch.setattr(
        "kicad_mcp.cloud_folder_browse_receiver.default_bindings_file",
        lambda: bindings_file,
    )
    connector._write_private_json(
        root,
        connector._FOREGROUND_FILE,
        connector._identity_state(record, connector._FOREGROUND_FILE),
    )
    service = device_folder_service(
        project.project_directory,
        bindings_file=bindings_file,
        native_picker=lambda: chosen,
        authorization=lambda: connector._is_enabled(root, record, connector._FOREGROUND_FILE),
    )

    def browser_frame(operation: str, **fields: object) -> str:
        return json.dumps(
            {
                "kind": "connector.local_browser_request",
                "version": 1,
                "requestId": str(uuid4()),
                "operation": operation,
                **fields,
            }
        )

    selected = handle_folder_frame(service, browser_frame("choose"))
    assert selected["status"] == "selected"
    assert not bindings_file.exists()

    def frame(pid: str) -> bytes:
        return json.dumps(
            {
                "kind": "connector.read_request",
                "version": 1,
                "requestId": str(uuid4()),
                "deviceId": DEVICE,
                "projectId": pid,
                "operation": "project_summary",
                "deadlineUnixMs": time.time_ns() // 1_000_000 + 20_000,
            }
        ).encode()

    # Remote 'choose' is NOT permission to read. A successful separate owner
    # binding must be necessary for the second project to be readable.
    dispatcher = connector._dispatcher_factory(root, record, project, connector._FOREGROUND_FILE)(
        HandshakeReceipt(DEVICE, SESSION)
    )
    unbound_read = frame(new_project)
    with pytest.raises(LocalReadDeniedError):
        dispatcher.read(unbound_read, sequence=1)
    assert (
        handle_folder_frame(
            service,
            browser_frame("bind", folderId=selected["projects"][0]["id"], projectId=new_project),
        )["ok"]
        is True
    )
    raw = frame(new_project)
    response = dispatcher.read(raw, sequence=2)
    assert response["projectId"] == new_project
    assert response["files"]["projectPresent"] is True
    assert str(chosen) not in json.dumps(response)
    dispatcher.assert_delivery_authorized(raw, device_id=DEVICE, session_id=SESSION)

    # Removing the local mapping must deny delivery even after read completed.
    bindings_file.unlink()
    with pytest.raises(LocalReadDeniedError):
        dispatcher.assert_delivery_authorized(raw, device_id=DEVICE, session_id=SESSION)
    revoked_read = frame(new_project)
    with pytest.raises(LocalReadDeniedError):
        dispatcher.read(revoked_read, sequence=3)

    # Removing owner permission is an independent fail-closed gate.
    connector._remove_private_file(root, connector._FOREGROUND_FILE)
    disabled_owner_read = frame(PROJECT)
    with pytest.raises(LocalReadDeniedError):
        dispatcher.read(disabled_owner_read, sequence=4)


def test_explicit_enable_writes_marker_then_starts_existing_user_unit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root, _project = _root(tmp_path)
    monkeypatch.setattr(connector, "default_registry_root", lambda: root)
    monkeypatch.setattr(connector, "_single_registered_identity", lambda _root: RECORD.copy())
    installed: list[bool] = []
    monkeypatch.setattr(connector, "_install_user_service", lambda: installed.append(True))
    calls: list[tuple[str, ...]] = []

    def systemctl(*args: str) -> subprocess.CompletedProcess[str]:
        assert connector._enabled_record(root) == connector._identity_state(RECORD)
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(connector, "_systemctl", systemctl)
    assert connector.main(["enable"]) == 0
    assert installed == [True]
    assert calls == [("enable", "--now", connector._SERVICE_NAME)]


@pytest.mark.anyio
async def test_local_off_during_inspection_fences_result_and_delivery(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root, project = _root(tmp_path)
    (project.project_directory / "board.kicad_pro").write_text("{}")
    connector._write_private_json(root, connector._ENABLED_FILE, connector._identity_state(RECORD))
    dispatcher = connector._dispatcher_factory(root, RECORD, project)(
        HandshakeReceipt(DEVICE, SESSION)
    )
    frame = json.dumps(
        {
            "kind": "connector.read_request",
            "version": 1,
            "requestId": str(uuid4()),
            "deviceId": DEVICE,
            "projectId": PROJECT,
            "operation": "project_summary",
            "deadlineUnixMs": time.time_ns() // 1_000_000 + 30_000,
        }
    ).encode()
    entered = threading.Event()
    release = threading.Event()
    original = inspect_readonly

    def delayed_inspection(*args: object, **kwargs: object) -> dict[str, object]:
        entered.set()
        assert release.wait(timeout=5)
        return original(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr("kicad_mcp.cloud_read_dispatch.inspect_readonly", delayed_inspection)
    pending = asyncio.create_task(asyncio.to_thread(dispatcher.read, frame, sequence=1))
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        connector._remove_private_file(root, connector._ENABLED_FILE)
    finally:
        release.set()
    with pytest.raises(LocalReadDeniedError):
        await pending
    assert not dispatcher._current_authorization()


@pytest.mark.anyio
async def test_local_off_after_read_but_before_delivery_is_denied(tmp_path: Path) -> None:
    root, project = _root(tmp_path)
    (project.project_directory / "board.kicad_pro").write_text("{}")
    connector._write_private_json(root, connector._ENABLED_FILE, connector._identity_state(RECORD))
    dispatcher = connector._dispatcher_factory(root, RECORD, project)(
        HandshakeReceipt(DEVICE, SESSION)
    )
    frame = json.dumps(
        {
            "kind": "connector.read_request",
            "version": 1,
            "requestId": str(uuid4()),
            "deviceId": DEVICE,
            "projectId": PROJECT,
            "operation": "project_summary",
            "deadlineUnixMs": time.time_ns() // 1_000_000 + 30_000,
        }
    ).encode()
    dispatcher.read(frame, sequence=1)
    connector._remove_private_file(root, connector._ENABLED_FILE)
    with pytest.raises(LocalReadDeniedError):
        dispatcher.assert_delivery_authorized(frame, device_id=DEVICE, session_id=SESSION)


@pytest.mark.anyio
async def test_connector_retries_after_disconnect_with_bounded_backoff(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root, project = _root(tmp_path)
    connector._write_private_json(root, connector._ENABLED_FILE, connector._identity_state(RECORD))
    stop = asyncio.Event()
    calls = 0
    key = Ed25519PrivateKey.generate()
    monkeypatch.setattr(connector, "_is_enabled", lambda *_args: True)
    monkeypatch.setattr(connector, "reconnect_delay_seconds", lambda failures, jitter: 0.0)

    async def session_runner(
        *,
        origin: str,
        trusted_origin: str,
        owner_sub: str,
        device_id: str,
        signing_key: Ed25519PrivateKey,
        dispatcher_factory: Callable[[HandshakeReceipt], LocalReadDispatch],
        max_reads: int,
    ) -> HandshakeReceipt:
        nonlocal calls
        calls += 1
        assert max_reads == connector._MAX_READS
        assert device_id == DEVICE
        assert origin == trusted_origin == RECORD["cloudOrigin"]
        assert owner_sub == RECORD["ownerSub"]
        assert isinstance(signing_key, Ed25519PrivateKey)
        assert callable(dispatcher_factory)
        if calls == 1:
            raise OSError("simulated network interruption")
        stop.set()
        return HandshakeReceipt(DEVICE, SESSION)

    result = await connector._run_connector(
        root=root,
        stop_event=stop,
        identity_loader=lambda _root: RECORD.copy(),
        project_resolver=lambda **_kwargs: project,
        key_loader=lambda *_args: key,
        session_runner=session_runner,
    )
    assert result == 0
    assert calls == 2
    status = connector._read_private_json(root, connector._STATUS_FILE)
    assert status["state"] == "connecting"


def test_private_json_rejects_duplicate_keys_invalid_shape_and_permissions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, _project = _root(tmp_path)
    path = root / connector._STATUS_FILE
    path.write_text('{"state":"connected"}')
    path.chmod(0o644)
    with pytest.raises(LocalApprovalDeniedError):
        connector._read_private_json(root, connector._STATUS_FILE)
    path.chmod(0o600)
    path.write_text("[]")
    with pytest.raises(LocalApprovalDeniedError):
        connector._read_private_json(root, connector._STATUS_FILE)
    path.write_text('{"state":"one","state":"two"}')
    with pytest.raises(LocalApprovalDeniedError):
        connector._read_private_json(root, connector._STATUS_FILE)
    path.write_text('{"state":"small"}')
    monkeypatch.setattr(os, "read", lambda *_args: b"x" * 2049)
    with pytest.raises(LocalApprovalDeniedError):
        connector._read_private_json(root, connector._STATUS_FILE)


def test_private_json_writer_rejects_oversized_state_and_remove_is_idempotent(
    tmp_path: Path,
) -> None:
    root, _project = _root(tmp_path)
    with pytest.raises(LocalApprovalDeniedError):
        connector._write_private_json(root, connector._STATUS_FILE, {"data": "x" * 2050})
    connector._remove_private_file(root, connector._STATUS_FILE)


def test_unique_rejects_duplicate_json_keys() -> None:
    with pytest.raises(LocalApprovalDeniedError):
        _unique([("state", "Off"), ("state", "On")])


def test_enabled_predicate_fails_closed_on_identity_change_or_registry_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root, _project = _root(tmp_path)
    connector._write_private_json(root, connector._ENABLED_FILE, connector._identity_state(RECORD))
    monkeypatch.setattr(
        connector,
        "_single_registered_identity",
        lambda _root: {**RECORD, "deviceId": "99999999-9999-4999-8999-999999999999"},
    )
    assert connector._is_enabled(root, RECORD) is False
    monkeypatch.setattr(
        connector,
        "_single_registered_identity",
        lambda _root: (_ for _ in ()).throw(LocalApprovalDeniedError("denied")),
    )
    assert connector._is_enabled(root, RECORD) is False


def test_status_reports_connection_state_and_stale_status_as_unavailable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root, _project = _root(tmp_path)
    monkeypatch.setattr(connector, "default_registry_root", lambda: root)
    connector._write_private_json(root, connector._ENABLED_FILE, connector._identity_state(RECORD))
    monkeypatch.setattr(
        connector,
        "_systemctl",
        lambda *args: subprocess.CompletedProcess(args, 0, "active", ""),
    )
    with connector._connector_session_lock(root):
        connector._write_status(root, "connected")
        assert connector.main(["status"]) == 0
        assert capsys.readouterr().out.strip() == "Connected"
        connector._write_status(root, "connecting")
        assert connector.main(["status"]) == 0
        assert capsys.readouterr().out.strip() == "Connecting"
        connector._write_private_json(
            root,
            connector._STATUS_FILE,
            {"state": "connected", "updatedAtUnixMs": 0, "pid": os.getpid()},
        )
        assert connector.main(["status"]) == 0
        assert capsys.readouterr().out.strip() == "Unavailable"


def test_status_reports_unavailable_when_enabled_marker_is_invalid(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root, _project = _root(tmp_path)
    monkeypatch.setattr(connector, "default_registry_root", lambda: root)
    marker = root / connector._ENABLED_FILE
    marker.write_text("{}")
    marker.chmod(0o600)
    assert connector.main(["status"]) == 0
    assert capsys.readouterr().out.strip() == "Unavailable"


def test_systemctl_requires_a_resolved_executable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    with pytest.raises(FileNotFoundError):
        connector._systemctl("is-active", connector._SERVICE_NAME)


def test_systemctl_uses_resolved_executable_and_user_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        assert kwargs["timeout"] == 8
        return subprocess.CompletedProcess(argv, 0, "active", "")

    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/bin/systemctl")
    monkeypatch.setattr(subprocess, "run", run)
    result = connector._systemctl("is-active", connector._SERVICE_NAME)
    assert result.returncode == 0
    assert calls == [["/usr/bin/systemctl", "--user", "is-active", connector._SERVICE_NAME]]


def test_service_path_and_systemd_quote_validation() -> None:
    assert connector._service_path().name == connector._SERVICE_NAME
    assert connector._systemd_quote('/home/test/a%folder/python"') == (
        '"/home/test/a%%folder/python\\""'
    )
    with pytest.raises(ValueError):
        connector._systemd_quote("/home/test/python\nunsafe")


def test_install_rejects_group_or_world_writable_unit_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root, _project = _root(tmp_path)
    service_dir = tmp_path / "config" / "systemd" / "user"
    service_dir.mkdir(parents=True, mode=0o700)
    service_dir.chmod(0o777)
    monkeypatch.setattr(connector, "default_registry_root", lambda: root)
    monkeypatch.setattr(
        connector,
        "_service_path",
        lambda: service_dir / connector._SERVICE_NAME,
    )
    with pytest.raises(LocalApprovalDeniedError):
        connector._install_user_service()


def test_install_reports_user_manager_reload_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root, _project = _root(tmp_path)
    service = tmp_path / "config" / "systemd" / "user" / connector._SERVICE_NAME
    monkeypatch.setattr(connector, "default_registry_root", lambda: root)
    monkeypatch.setattr(connector, "_service_path", lambda: service)
    monkeypatch.setattr(
        connector,
        "_systemctl",
        lambda *args: subprocess.CompletedProcess(args, 1, "", "reload failed"),
    )
    with pytest.raises(RuntimeError):
        connector._install_user_service()
    assert service.is_file()


def test_disable_reports_manager_failure_after_attempting_to_stop(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root, _project = _root(tmp_path)
    connector._write_private_json(root, connector._ENABLED_FILE, connector._identity_state(RECORD))
    monkeypatch.setattr(connector, "default_registry_root", lambda: root)
    calls = 0

    def systemctl(*args: str) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        raise OSError("user manager unavailable")

    monkeypatch.setattr(connector, "_systemctl", systemctl)
    assert connector.main(["disable"]) == 1
    assert calls == 2
    assert not (root / connector._ENABLED_FILE).exists()


def test_dispatcher_factory_refuses_a_locally_disabled_project(
    tmp_path: Path,
) -> None:
    root, project = _root(tmp_path)
    factory = connector._dispatcher_factory(root, RECORD, project)
    receipt = HandshakeReceipt(DEVICE, SESSION)
    with pytest.raises(LocalApprovalDeniedError):
        factory(receipt)


@pytest.mark.anyio
async def test_disable_racing_key_loading_prevents_new_handshake(
    tmp_path: Path,
) -> None:
    root, project = _root(tmp_path)
    connector._write_private_json(root, connector._ENABLED_FILE, connector._identity_state(RECORD))
    session_calls: list[bool] = []
    key = Ed25519PrivateKey.generate()

    def remove_before_return(*_args: object) -> Ed25519PrivateKey:
        connector._remove_private_file(root, connector._ENABLED_FILE)
        return key

    async def session_runner(
        *,
        origin: str,
        trusted_origin: str,
        owner_sub: str,
        device_id: str,
        signing_key: Ed25519PrivateKey,
        dispatcher_factory: Callable[[HandshakeReceipt], LocalReadDispatch],
        max_reads: int,
    ) -> HandshakeReceipt:
        session_calls.append(True)
        return HandshakeReceipt(DEVICE, SESSION)

    result = await connector._run_connector(
        root=root,
        stop_event=asyncio.Event(),
        identity_loader=lambda _root: RECORD.copy(),
        project_resolver=lambda **_kwargs: project,
        key_loader=remove_before_return,
        session_runner=session_runner,
    )
    assert result == 0
    assert session_calls == []


def test_connector_uid_lookup_fails_closed_without_posix_getuid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delattr(os, "getuid")
    with pytest.raises(LocalApprovalDeniedError):
        connector._current_uid()


@pytest.mark.anyio
async def test_second_local_connector_cannot_load_key_or_start_session(tmp_path: Path) -> None:
    root, project = _root(tmp_path)
    connector._write_private_json(root, connector._ENABLED_FILE, connector._identity_state(RECORD))
    entered = asyncio.Event()
    stop = asyncio.Event()
    loads = 0
    starts = 0

    def load_key(*_args: object) -> Ed25519PrivateKey:
        nonlocal loads
        loads += 1
        return Ed25519PrivateKey.generate()

    async def run_session(**_kwargs: object) -> HandshakeReceipt:
        nonlocal starts
        starts += 1
        entered.set()
        await asyncio.Event().wait()
        return HandshakeReceipt(DEVICE, SESSION)

    async def launch() -> int:
        return await connector._run_connector(
            root=root,
            stop_event=stop,
            identity_loader=lambda _: RECORD.copy(),
            project_resolver=lambda **_: project,
            key_loader=load_key,
            session_runner=run_session,
        )

    first = asyncio.create_task(launch())
    try:
        await asyncio.wait_for(entered.wait(), timeout=3)
        competing_attempt = asyncio.wait_for(launch(), timeout=0.5)
        with pytest.raises(RuntimeError, match="already running"):
            await competing_attempt
        assert loads == starts == 1
        assert not first.done()
        assert connector._enabled_record(root) == connector._identity_state(RECORD)
    finally:
        stop.set()
        await asyncio.wait_for(first, timeout=3)
    stop.clear()
    entered.clear()
    restarted = asyncio.create_task(launch())
    try:
        await asyncio.wait_for(entered.wait(), timeout=3)
        assert loads == starts == 2
    finally:
        stop.set()
        await asyncio.wait_for(restarted, timeout=3)


@pytest.mark.anyio
async def test_cancel_connector_closes_session_before_returning(tmp_path: Path) -> None:
    root, project = _root(tmp_path)
    connector._write_private_json(root, connector._ENABLED_FILE, connector._identity_state(RECORD))
    entered = asyncio.Event()
    closed = asyncio.Event()

    async def run_session(**_kwargs: object) -> HandshakeReceipt:
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            closed.set()
        return HandshakeReceipt(DEVICE, SESSION)

    task = asyncio.create_task(
        connector._run_connector(
            root=root,
            identity_loader=lambda _: RECORD.copy(),
            project_resolver=lambda **_: project,
            key_loader=lambda *_: Ed25519PrivateKey.generate(),
            session_runner=run_session,
        )
    )
    await asyncio.wait_for(entered.wait(), timeout=3)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert closed.is_set()


@pytest.mark.parametrize("invalid_lock", ["symlink", "hardlink", "public", "nonempty", "fifo"])
def test_session_lock_rejects_unsafe_files(tmp_path: Path, invalid_lock: str) -> None:
    root, _project = _root(tmp_path)
    path = root / connector._SESSION_LOCK_FILE
    outside = tmp_path / "outside"
    outside.write_bytes(b"")
    outside.chmod(0o600)
    if invalid_lock == "symlink":
        path.symlink_to(outside)
    elif invalid_lock == "hardlink":
        os.link(outside, path)
    elif invalid_lock == "fifo":
        os.mkfifo(path, 0o600)
    else:
        path.write_bytes(b"unexpected" if invalid_lock == "nonempty" else b"")
        path.chmod(0o644 if invalid_lock == "public" else 0o600)
    with (
        pytest.raises((OSError, LocalApprovalDeniedError)),
        connector._connector_session_lock(root),
    ):
        pytest.fail("unsafe lock was acquired")
    assert outside.read_bytes() == b""


def test_main_reports_existing_session_without_a_traceback(monkeypatch, capsys) -> None:
    async def already_running() -> int:
        raise connector.ConnectorAlreadyRunningError("A local Cloud Connector is already running.")

    monkeypatch.setattr(connector, "_run_service", already_running)
    assert connector.main(["run"]) == 1
    assert "already running" in capsys.readouterr().err


def test_stale_connected_status_without_session_owner_is_unavailable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root, _project = _root(tmp_path)
    monkeypatch.setattr(connector, "default_registry_root", lambda: root)
    monkeypatch.setattr(
        connector,
        "_systemctl",
        lambda *args: subprocess.CompletedProcess("systemctl fixture", 0, "active", ""),
    )
    connector._write_private_json(root, connector._ENABLED_FILE, connector._identity_state(RECORD))
    connector._write_status(root, "connected")
    with connector._connector_session_lock(root):
        pass
    assert connector._status() == "Unavailable"


def test_status_without_lock_does_not_create_lock_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root, _project = _root(tmp_path)
    monkeypatch.setattr(connector, "default_registry_root", lambda: root)
    monkeypatch.setattr(
        connector,
        "_systemctl",
        lambda *args: subprocess.CompletedProcess("systemctl fixture", 0, "active", ""),
    )
    connector._write_private_json(root, connector._ENABLED_FILE, connector._identity_state(RECORD))
    connector._write_status(root, "connected")
    assert connector._status() == "Unavailable"
    assert not (root / connector._SESSION_LOCK_FILE).exists()


@pytest.mark.anyio
@pytest.mark.parametrize("revoke", ["marker", "registration"])
async def test_local_authority_revocation_closes_idle_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, revoke: str
) -> None:
    root, project = _root(tmp_path)
    connector._write_private_json(root, connector._ENABLED_FILE, connector._identity_state(RECORD))
    monkeypatch.setattr(connector, "_LOCAL_AUTHORITY_POLL_SECONDS", 0.01)
    entered = asyncio.Event()
    closed = asyncio.Event()
    starts = 0

    async def run_session(**_kwargs: object) -> HandshakeReceipt:
        nonlocal starts
        starts += 1
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            closed.set()
        return HandshakeReceipt(DEVICE, SESSION)

    task = asyncio.create_task(
        connector._run_connector(
            root=root,
            identity_loader=lambda _: RECORD.copy(),
            project_resolver=lambda **_: project,
            key_loader=lambda *_: Ed25519PrivateKey.generate(),
            session_runner=run_session,
        )
    )
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        if revoke == "marker":
            connector._remove_private_file(root, connector._ENABLED_FILE)
        else:
            (root / "projects" / f"{PROJECT}.json").unlink()
        assert await asyncio.wait_for(task, timeout=0.5) == 0
        assert closed.is_set()
        assert starts == 1
        assert not connector._session_lock_held(root)
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.anyio
async def test_foreground_authority_is_temporary_and_reconnects_same_device(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, project = _root(tmp_path)
    stop = asyncio.Event()
    calls = []
    monkeypatch.setattr(connector, "reconnect_delay_seconds", lambda *_: 0.0)

    async def session(**kwargs: object) -> HandshakeReceipt:
        calls.append(kwargs["device_id"])
        assert not (root / connector._ENABLED_FILE).exists()
        assert (root / "connector-foreground.json").is_file()
        if len(calls) == 1:
            raise OSError("fixture network interruption")
        stop.set()
        return HandshakeReceipt(DEVICE, SESSION)

    result = await connector._run_connector(
        root=root,
        stop_event=stop,
        foreground=True,
        project_resolver=lambda **_: project,
        key_loader=lambda *_: Ed25519PrivateKey.generate(),
        session_runner=session,
    )
    assert result == 0
    assert calls == [DEVICE, DEVICE]
    assert not (root / "connector-foreground.json").exists()
    assert not (root / connector._ENABLED_FILE).exists()
    assert not connector._session_lock_held(root)


@pytest.mark.anyio
async def test_foreground_refuses_persistent_authority_without_mutation(tmp_path: Path) -> None:
    root, _project = _root(tmp_path)
    connector._write_private_json(root, connector._ENABLED_FILE, connector._identity_state(RECORD))
    previous = (root / connector._ENABLED_FILE).read_bytes()
    with pytest.raises(RuntimeError, match="background"):
        await connector._run_connector(root=root, foreground=True)
    assert (root / connector._ENABLED_FILE).read_bytes() == previous
    assert not (root / "connector-foreground.json").exists()


@pytest.mark.anyio
async def test_service_does_not_inherit_crashed_foreground_authority(tmp_path: Path) -> None:
    root, _project = _root(tmp_path)
    connector._write_private_json(
        root, "connector-foreground.json", connector._identity_state(RECORD)
    )
    assert (
        await connector._run_connector(
            root=root, identity_loader=lambda _: pytest.fail("background must stay disabled")
        )
        == 0
    )
    assert not (root / connector._ENABLED_FILE).exists()


@pytest.mark.anyio
async def test_foreground_status_and_revocation_without_systemd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, project = _root(tmp_path)
    monkeypatch.setattr(connector, "default_registry_root", lambda: root)
    monkeypatch.setattr(connector, "_LOCAL_AUTHORITY_POLL_SECONDS", 0.01)
    monkeypatch.setattr(
        connector, "_systemctl", lambda *_: pytest.fail("foreground needs no systemd")
    )
    ready = asyncio.Event()
    closed = asyncio.Event()

    async def session(**kwargs: object) -> HandshakeReceipt:
        dispatcher = kwargs["dispatcher_factory"](HandshakeReceipt(DEVICE, SESSION))
        dispatcher._authorize_now()
        ready.set()
        try:
            await asyncio.Event().wait()
        finally:
            assert not dispatcher._current_authorization()
            closed.set()
        return HandshakeReceipt(DEVICE, SESSION)

    task = asyncio.create_task(
        connector._run_connector(
            root=root,
            foreground=True,
            project_resolver=lambda **_: project,
            key_loader=lambda *_: Ed25519PrivateKey.generate(),
            session_runner=session,
        )
    )
    try:
        await asyncio.wait_for(ready.wait(), timeout=2)
        assert connector._status() == "Connected"
        connector._remove_private_file(root, connector._FOREGROUND_FILE)
        assert connector._status() == "Off"
        assert await asyncio.wait_for(task, timeout=2) == 0
        assert closed.is_set()
        assert not connector._session_lock_held(root)
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


def test_crashed_foreground_status_is_off(monkeypatch, tmp_path: Path) -> None:
    root, _ = _root(tmp_path)
    monkeypatch.setattr(connector, "default_registry_root", lambda: root)
    record = connector._single_registered_identity(root)
    connector._write_private_json(
        root,
        connector._FOREGROUND_FILE,
        connector._identity_state(record, connector._FOREGROUND_FILE),
    )
    connector._write_status(root, "connected")
    with connector._connector_session_lock(root):
        pass
    assert connector._status() == "Off"


@pytest.mark.anyio
async def test_foreground_cannot_reconnect_after_project_directory_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, project = _root(tmp_path)
    monkeypatch.setattr(connector, "reconnect_delay_seconds", lambda *_: 0.0)
    stop = asyncio.Event()
    calls = 0
    changed_dir = tmp_path / "other-project"
    changed_dir.mkdir()

    async def session(**_kwargs: object) -> HandshakeReceipt:
        nonlocal calls
        calls += 1
        if calls == 1:
            record_path = root / "projects" / f"{PROJECT}.json"
            record = json.loads(record_path.read_text())
            record["directory"] = str(changed_dir)
            record_path.write_text(json.dumps(record))
        else:
            stop.set()
        return HandshakeReceipt(DEVICE, SESSION)

    assert (
        await connector._run_connector(
            root=root,
            foreground=True,
            stop_event=stop,
            project_resolver=lambda **_: project,
            key_loader=lambda *_: Ed25519PrivateKey.generate(),
            session_runner=session,
        )
        == 0
    )
    assert calls == 1
    assert not (root / connector._FOREGROUND_FILE).exists()


@pytest.mark.anyio
async def test_foreground_revocation_interrupts_reconnect_delay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, project = _root(tmp_path)
    monkeypatch.setattr(connector, "_LOCAL_AUTHORITY_POLL_SECONDS", 0.01)
    monkeypatch.setattr(connector, "reconnect_delay_seconds", lambda *_: 120.0)
    entered = asyncio.Event()
    calls = 0

    async def session(**_kwargs: object) -> HandshakeReceipt:
        nonlocal calls
        calls += 1
        entered.set()
        raise OSError("fixture network interruption")

    task = asyncio.create_task(
        connector._run_connector(
            root=root,
            foreground=True,
            project_resolver=lambda **_: project,
            key_loader=lambda *_: Ed25519PrivateKey.generate(),
            session_runner=session,
        )
    )
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        await asyncio.sleep(0.03)
        connector._remove_private_file(root, connector._FOREGROUND_FILE)
        assert await asyncio.wait_for(task, timeout=0.5) == 0
        assert calls == 1
        assert not connector._session_lock_held(root)
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


def test_disable_foreground_on_darwin_does_not_use_systemd(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from types import SimpleNamespace

    root, _ = _root(tmp_path)
    record = connector._single_registered_identity(root)
    connector._write_private_json(
        root,
        connector._FOREGROUND_FILE,
        connector._identity_state(record, connector._FOREGROUND_FILE),
    )
    monkeypatch.setattr(connector, "default_registry_root", lambda: root)
    monkeypatch.setattr(connector, "sys", SimpleNamespace(platform="darwin"))
    monkeypatch.setattr(connector, "_systemctl", lambda *_: pytest.fail("no systemd on Darwin"))
    assert connector._disable() == 0
    assert not (root / connector._FOREGROUND_FILE).exists()


@pytest.mark.anyio
async def test_foreground_rejects_changed_binding_before_key_loading(tmp_path: Path) -> None:
    root, _project = _root(tmp_path)
    expected = connector._single_registered_identity(root)
    expected["cloudOrigin"] = "https://other.example"
    with pytest.raises(ValueError):
        await connector._run_connector(
            root=root,
            foreground=True,
            expected_identity=expected,
            key_loader=lambda *_: pytest.fail("changed binding must not load key"),
        )
    assert not (root / connector._FOREGROUND_FILE).exists()


@pytest.mark.parametrize("outcome", ["success", "occupied", "invalid"])
def test_run_foreground_routes_expected_binding_and_errors(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], outcome: str
) -> None:
    async def run(*, foreground: bool, expected_identity: dict[str, str]) -> int:
        assert foreground is True
        assert expected_identity == RECORD
        if outcome == "occupied":
            raise connector.ConnectorAlreadyRunningError("already running")
        if outcome == "invalid":
            raise LocalApprovalDeniedError("fixture private details")
        return 0

    monkeypatch.setattr(connector, "_run_service", run)
    assert connector.run_foreground(RECORD) == (0 if outcome == "success" else 1)
    captured = capsys.readouterr()
    assert "fixture private details" not in captured.err
    if outcome == "occupied":
        assert "already running" in captured.err


def test_foreground_disable_does_not_claim_stop_if_lock_is_still_held(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root, _ = _root(tmp_path)
    record = connector._single_registered_identity(root)
    connector._write_private_json(
        root,
        connector._FOREGROUND_FILE,
        connector._identity_state(record, connector._FOREGROUND_FILE),
    )
    monkeypatch.setattr(connector, "default_registry_root", lambda: root)
    monkeypatch.setattr(connector, "_FOREGROUND_SHUTDOWN_TIMEOUT", 0.0)
    monkeypatch.setattr(
        connector, "_systemctl", lambda *_: pytest.fail("foreground needs no systemd")
    )
    with connector._connector_session_lock(root):
        assert connector._disable() == 1
        assert not (root / connector._FOREGROUND_FILE).exists()
        captured = capsys.readouterr()
        assert "unverified" in captured.err
        assert "is Off" not in captured.out


@pytest.mark.anyio
async def test_foreground_terminal_reports_signed_ready_and_disconnect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root, project = _root(tmp_path)
    stop = asyncio.Event()
    monkeypatch.setattr(connector, "reconnect_delay_seconds", lambda *_: 0.0)
    attempts = 0

    async def session(**kwargs: object) -> HandshakeReceipt:
        nonlocal attempts
        attempts += 1
        before = capsys.readouterr().out
        assert "Connected" not in before
        assert "Connecting" in before
        if attempts == 1:
            raise OSError("secret fixture path")
        assert "Disconnected" in before
        kwargs["dispatcher_factory"](HandshakeReceipt(DEVICE, SESSION))
        assert "Connected" in capsys.readouterr().out
        stop.set()
        return HandshakeReceipt(DEVICE, SESSION)

    assert (
        await connector._run_connector(
            root=root,
            foreground=True,
            stop_event=stop,
            project_resolver=lambda **_: project,
            key_loader=lambda *_: Ed25519PrivateKey.generate(),
            session_runner=session,
        )
        == 0
    )
    assert attempts == 2
    output = capsys.readouterr().out
    assert "Disconnected" in output
    assert "secret fixture path" not in output


def test_foreground_status_rejects_changed_binding_immediately(monkeypatch, tmp_path: Path) -> None:
    root, _ = _root(tmp_path)
    record = connector._single_registered_identity(root)
    connector._write_private_json(
        root,
        connector._FOREGROUND_FILE,
        connector._identity_state(record, connector._FOREGROUND_FILE),
    )
    monkeypatch.setattr(connector, "default_registry_root", lambda: root)
    with connector._connector_session_lock(root):
        connector._write_status(root, "connected")
        assert connector._status() == "Connected"
        (root / "projects" / f"{PROJECT}.json").unlink()
        assert connector._status() == "Unavailable"


def test_foreground_disable_rejects_unverifiable_lock(monkeypatch, tmp_path: Path, capsys) -> None:
    root, _ = _root(tmp_path)
    record = connector._single_registered_identity(root)
    connector._write_private_json(
        root,
        connector._FOREGROUND_FILE,
        connector._identity_state(record, connector._FOREGROUND_FILE),
    )
    lock = root / connector._SESSION_LOCK_FILE
    lock.write_text("invalid lock")
    lock.chmod(0o600)
    monkeypatch.setattr(connector, "default_registry_root", lambda: root)
    monkeypatch.setattr(connector, "_systemctl", lambda *_: pytest.fail("no systemd"))
    assert connector._disable() == 1
    assert "unverified" in capsys.readouterr().err


@pytest.mark.anyio
async def test_foreground_signed_transport_receives_activity_callback(
    monkeypatch, tmp_path, capsys
) -> None:
    root, project = _root(tmp_path)
    stop = asyncio.Event()

    async def signed_transport(**kwargs: object) -> HandshakeReceipt:
        kwargs["dispatcher_factory"](HandshakeReceipt(DEVICE, SESSION))
        kwargs["on_activity"]("Tool call 1: project_summary completed (5 ms)")
        stop.set()
        return HandshakeReceipt(DEVICE, SESSION)

    monkeypatch.setattr(connector, "execute_owner_managed_read_session", signed_transport)
    assert (
        await connector._run_connector(
            root=root,
            foreground=True,
            stop_event=stop,
            project_resolver=lambda **_: project,
            key_loader=lambda *_: Ed25519PrivateKey.generate(),
            session_runner=signed_transport,
        )
        == 0
    )
    assert "Tool call 1: project_summary completed (5 ms)" in capsys.readouterr().out


def test_background_enable_refuses_active_foreground_without_mutation(
    monkeypatch, tmp_path: Path
) -> None:
    root, _ = _root(tmp_path)
    record = connector._single_registered_identity(root)
    connector._write_private_json(
        root,
        connector._FOREGROUND_FILE,
        connector._identity_state(record, connector._FOREGROUND_FILE),
    )
    before = (root / connector._FOREGROUND_FILE).read_bytes()
    monkeypatch.setattr(connector, "default_registry_root", lambda: root)
    monkeypatch.setattr(
        connector, "_install_user_service", lambda: pytest.fail("must not install service")
    )
    monkeypatch.setattr(connector, "_systemctl", lambda *_: pytest.fail("must not start service"))
    with connector._connector_session_lock(root):
        assert connector.main(["enable"]) == 1
    assert not (root / connector._ENABLED_FILE).exists()
    assert (root / connector._FOREGROUND_FILE).read_bytes() == before


def test_enable_does_not_report_success_after_concurrent_revocation(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    root, _ = _root(tmp_path)
    monkeypatch.setattr(connector, "default_registry_root", lambda: root)
    monkeypatch.setattr(connector, "_install_user_service", lambda: None)
    calls = []

    def systemctl(*args: str) -> subprocess.CompletedProcess[str]:
        calls.append(args[0])
        if args[0] == "enable":
            connector._remove_private_file(root, connector._ENABLED_FILE)
        return subprocess.CompletedProcess("systemctl fixture", 0, "", "")

    monkeypatch.setattr(connector, "_systemctl", systemctl)
    assert connector.main(["enable"]) == 1
    assert calls == ["enable", "disable"]
    assert not (root / connector._ENABLED_FILE).exists()
    assert "enabled for" not in capsys.readouterr().out


def test_disable_without_marker_does_not_claim_stop_while_runner_holds_lock(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    root, _ = _root(tmp_path)
    monkeypatch.setattr(connector, "default_registry_root", lambda: root)
    monkeypatch.setattr(connector, "_FOREGROUND_SHUTDOWN_TIMEOUT", 0.0)
    monkeypatch.setattr(
        connector,
        "_systemctl",
        lambda *args: subprocess.CompletedProcess("systemctl fixture", 0, "", ""),
    )
    with connector._connector_session_lock(root):
        assert connector._disable() == 1
        captured = capsys.readouterr()
        assert "unverified" in captured.err
        assert "is Off" not in captured.out
