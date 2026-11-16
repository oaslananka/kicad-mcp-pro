"""Cross-platform signed foreground Connector contract; no network or user data."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import cast
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from kicad_mcp.cloud_local_registry import LocalRegisteredRead
from kicad_mcp.cloud_outbound_handshake import CloudHandshakeDeniedError, HandshakeReceipt
from kicad_mcp.cloud_pair_keys import LocalApprovalDeniedError
from kicad_mcp.cloud_posix_foreground import run_foreground
from kicad_mcp.cloud_read_dispatch import LocalReadDispatch

DEVICE = str(uuid4())
PROJECT = str(uuid4())
SESSION = str(uuid4())
RECORD = {
    "ownerSub": "test-owner",
    "cloudOrigin": "https://cloud.example",
    "deviceId": DEVICE,
    "projectId": PROJECT,
}


def inputs(tmp_path: Path) -> tuple[LocalRegisteredRead, Ed25519PrivateKey, list[dict[str, str]]]:
    project_dir = tmp_path / "test-board"
    project_dir.mkdir()
    (project_dir / "test-board.kicad_pro").write_text("{}", encoding="utf-8")
    project = LocalRegisteredRead(tmp_path / "key.pem", project_dir, "test-board")
    key = Ed25519PrivateKey.generate()
    record = [RECORD.copy()]
    return project, key, record


@pytest.mark.anyio
async def test_signed_foreground_reuses_local_identity_and_has_no_persistent_marker(
    tmp_path: Path,
) -> None:
    project, key, record = inputs(tmp_path)
    stop = asyncio.Event()
    statuses = []
    dispatchers = []

    async def runner(**kwargs: object) -> HandshakeReceipt:
        assert kwargs["device_id"] == DEVICE
        assert kwargs["signing_key"] is key
        receipt = HandshakeReceipt(DEVICE, SESSION)
        dispatcher = cast(
            Callable[[HandshakeReceipt], LocalReadDispatch], kwargs["dispatcher_factory"]
        )(receipt)
        dispatchers.append(dispatcher)
        assert dispatcher._current_authorization()
        kwargs["on_ready"](receipt)
        stop.set()
        return receipt

    finished = await run_foreground(
        registry=tmp_path,
        stop_event=stop,
        status_callback=statuses.append,
        identity_loader=lambda _root: record[0],
        project_resolver=lambda **_kw: project,
        key_loader=lambda *_args: key,
        session_runner=runner,
    )
    assert finished is None, "foreground terminal has no RPC result"
    assert statuses[:2] == ["Connecting", "Connected"]
    assert dispatchers
    assert not (tmp_path / "connector-enabled.json").exists()
    assert not dispatchers[0]._current_authorization()


@pytest.mark.anyio
async def test_foreground_revokes_inflight_read_when_local_identity_changes(tmp_path: Path) -> None:
    project, key, record = inputs(tmp_path)
    stop = asyncio.Event()
    observed = []

    async def runner(**kwargs: object) -> HandshakeReceipt:
        dispatcher = cast(
            Callable[[HandshakeReceipt], LocalReadDispatch], kwargs["dispatcher_factory"]
        )(HandshakeReceipt(DEVICE, SESSION))
        assert dispatcher._current_authorization()
        record[0] = {**RECORD, "projectId": str(uuid4())}
        observed.append(dispatcher._current_authorization())
        stop.set()
        return HandshakeReceipt(DEVICE, SESSION)

    await run_foreground(
        registry=tmp_path,
        stop_event=stop,
        identity_loader=lambda _root: record[0],
        project_resolver=lambda **_kw: project,
        key_loader=lambda *_args: key,
        session_runner=runner,
    )
    assert observed == [False]


@pytest.mark.anyio
async def test_foreground_network_failure_retries_with_same_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kicad_mcp import cloud_posix_foreground as foreground

    project, key, record = inputs(tmp_path)
    monkeypatch.setattr(foreground, "reconnect_delay_seconds", lambda _failures, _jitter: 0.001)
    stop = asyncio.Event()
    calls = []
    statuses = []

    async def runner(**kwargs: object) -> HandshakeReceipt:
        calls.append(kwargs["device_id"])
        if len(calls) == 1:
            raise OSError("simulated outage")
        stop.set()
        return HandshakeReceipt(DEVICE, SESSION)

    await run_foreground(
        registry=tmp_path,
        stop_event=stop,
        status_callback=statuses.append,
        identity_loader=lambda _root: record[0],
        project_resolver=lambda **_kw: project,
        key_loader=lambda *_args: key,
        session_runner=runner,
    )
    assert calls == [DEVICE, DEVICE]
    assert "Reconnecting" in statuses


@pytest.mark.anyio
async def test_foreground_policy_denial_does_not_retry(tmp_path: Path) -> None:
    project, key, record = inputs(tmp_path)
    calls = 0

    async def denied(**_kw: object) -> HandshakeReceipt:
        nonlocal calls
        calls += 1
        raise CloudHandshakeDeniedError("not approved")

    with pytest.raises(CloudHandshakeDeniedError):
        await run_foreground(
            registry=tmp_path,
            identity_loader=lambda _root: record[0],
            project_resolver=lambda **_kw: project,
            key_loader=lambda *_args: key,
            session_runner=denied,
        )
    assert calls == 1


@pytest.mark.anyio
async def test_foreground_missing_owner_registration_never_opens_socket(tmp_path: Path) -> None:
    def denied(_root: Path) -> dict[str, str]:
        raise LocalApprovalDeniedError("invalid")

    async def runner(**_kw: object) -> HandshakeReceipt:
        pytest.fail("An invalid local owner identity must not open a WebSocket")

    with pytest.raises(LocalApprovalDeniedError):
        await run_foreground(registry=tmp_path, identity_loader=denied, session_runner=runner)


@pytest.mark.anyio
async def test_foreground_does_not_dispatch_after_local_signing_key_becomes_unreadable(
    tmp_path: Path,
) -> None:
    project, key, record = inputs(tmp_path)
    stop = asyncio.Event()
    reads = 0

    def recheck_key(*_args: object) -> Ed25519PrivateKey:
        nonlocal reads
        reads += 1
        if reads > 1:
            raise OSError("synthetic key vault failure")
        return key

    async def runner(**kwargs: object) -> HandshakeReceipt:
        factory = cast(
            Callable[[HandshakeReceipt], LocalReadDispatch], kwargs["dispatcher_factory"]
        )
        with pytest.raises(LocalApprovalDeniedError):
            factory(HandshakeReceipt(DEVICE, SESSION))
        stop.set()
        return HandshakeReceipt(DEVICE, SESSION)

    await run_foreground(
        registry=tmp_path,
        stop_event=stop,
        identity_loader=lambda _root: record[0],
        project_resolver=lambda **_kw: project,
        key_loader=recheck_key,
        session_runner=runner,
    )
    assert reads == 2


@pytest.mark.anyio
async def test_foreground_rejects_invalid_owner_signing_key_without_network(
    tmp_path: Path,
) -> None:
    project, _key, record = inputs(tmp_path)

    def broken_key(*_args: object) -> Ed25519PrivateKey:
        raise ValueError("synthetic missing key")

    async def no_network(**_kwargs: object) -> HandshakeReceipt:
        pytest.fail("Invalid local key must be rejected before connecting")

    with pytest.raises(LocalApprovalDeniedError):
        await run_foreground(
            registry=tmp_path,
            identity_loader=lambda _root: record[0],
            project_resolver=lambda **_kw: project,
            key_loader=broken_key,
            session_runner=no_network,
        )


@pytest.mark.anyio
async def test_foreground_exposes_owner_selected_native_folder_and_revokes_it(
    tmp_path: Path,
) -> None:
    from kicad_mcp.cloud_folder_browse_receiver import (
        LocalFolderBrowseService,
    )
    from kicad_mcp.cloud_outbound_handshake import CloudHandshakeDeniedError

    project, key, record = inputs(tmp_path)
    second = tmp_path / "Second Board"
    second.mkdir()
    (second / "Second Board.kicad_pro").write_text("{}", encoding="utf-8")
    stop = asyncio.Event()
    binding_path = tmp_path / "local-bindings.json"
    observed = []

    async def runner(**kwargs: object) -> HandshakeReceipt:
        factory = cast(
            Callable[[HandshakeReceipt], LocalFolderBrowseService],
            kwargs["folder_service_factory"],
        )
        receipt = HandshakeReceipt(DEVICE, SESSION)
        service = factory(receipt)
        chosen = service.choose()
        assert chosen["status"] == "selected"
        token = str(chosen["folderId"])
        assert chosen["projects"] == [{"id": token, "name": "Second Board"}]
        new_project_id = str(uuid4())
        assert service.bind(token, new_project_id)
        assert service.project_path(new_project_id) == str(second / "Second Board.kicad_pro")
        assert not (tmp_path / "connector-enabled.json").exists()
        observed.append(chosen["name"])
        record[0] = {**record[0], "projectId": str(uuid4())}
        with pytest.raises(CloudHandshakeDeniedError):
            service.choose()
        stop.set()
        return receipt

    await run_foreground(
        registry=tmp_path,
        stop_event=stop,
        native_picker=lambda: second,
        bindings_file=binding_path,
        identity_loader=lambda _root: record[0],
        project_resolver=lambda **_kw: project,
        key_loader=lambda *_args: key,
        session_runner=runner,
    )
    assert observed == ["Second Board"]
    assert "Second Board.kicad_pro" in binding_path.read_text(encoding="utf-8")


@pytest.mark.anyio
async def test_headless_posix_foreground_never_claims_cloud_browse(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kicad_mcp import cloud_posix_foreground as foreground

    project, key, record = inputs(tmp_path)
    stop = asyncio.Event()
    monkeypatch.setattr(foreground, "native_picker_available", lambda: False)

    async def runner(**kwargs: object) -> HandshakeReceipt:
        assert "folder_service_factory" not in kwargs
        stop.set()
        return HandshakeReceipt(DEVICE, SESSION)

    await run_foreground(
        registry=tmp_path,
        stop_event=stop,
        identity_loader=lambda _root: record[0],
        project_resolver=lambda **_kw: project,
        key_loader=lambda *_args: key,
        session_runner=runner,
    )
