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
from kicad_mcp.cloud_pair_keys import LocalApprovalDeniedError
from kicad_mcp.cloud_read_dispatch import LocalReadDispatch
from kicad_mcp.cloud_readonly_boundary import LocalReadDeniedError, inspect_readonly

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
        connector._unique([("state", "Off"), ("state", "On")])


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
    with pytest.raises(LocalApprovalDeniedError):
        factory(HandshakeReceipt(DEVICE, SESSION))


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
