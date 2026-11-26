"""Owner-started POSIX sessions expose real MCP without separate edit switches."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from kicad_mcp import cloud_managed_connector as connector
from kicad_mcp.cloud_local_registry import LocalRegisteredRead
from kicad_mcp.cloud_outbound_handshake import HandshakeReceipt

ORIGIN = "https://kicad-mcp-pro.oaslananka.dev"


@pytest.mark.parametrize("mode", ["official", "other", "background", "revoked"])
def test_posix_session_factory(tmp_path: Path, monkeypatch, mode: str) -> None:
    root = tmp_path / "registry"
    root.mkdir(mode=0o700)
    board = tmp_path / "board"
    board.mkdir()
    record = {
        "ownerSub": "owner",
        "cloudOrigin": ORIGIN if mode != "other" else "https://other.example",
        "deviceId": str(uuid4()),
        "projectId": str(uuid4()),
    }
    project = LocalRegisteredRead(root / "key.pem", board, "board")
    marker = connector._ENABLED_FILE if mode == "background" else connector._FOREGROUND_FILE
    state = {"authorized": mode != "revoked"}
    monkeypatch.setattr(connector, "_is_enabled", lambda *_: state["authorized"])
    receipt = HandshakeReceipt(record["deviceId"], str(uuid4()))
    if mode == "revoked":
        with pytest.raises(ValueError):
            connector._posix_mcp_settings(root, record, project, marker)
        return
    options = connector._posix_mcp_settings(root, record, project, marker)
    if mode == "background":
        assert options == {}
        return
    service = options["mcp_bridge_factory"](receipt)
    assert service.allow_write is (mode == "official")
    assert service._current_project(record["projectId"]).directory == board
    with pytest.raises(ValueError):
        service._current_project(str(uuid4()))
    if mode == "official":
        assert "native_write" in options
        req = str(uuid4())
        assert service.consume_once(receipt.session_id, req)
        assert not service.consume_once(receipt.session_id, req)
    else:
        assert "native_write" not in options
        assert service.consume_once is None
    state["authorized"] = False
    with pytest.raises(ValueError):
        service._current_project(record["projectId"])


def test_posix_replay_directory_cannot_be_symlink(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "registry"
    root.mkdir(mode=0o700)
    outside = tmp_path / "outside"
    outside.mkdir(mode=0o700)
    (root / "write-markers").symlink_to(outside, target_is_directory=True)
    monkeypatch.setattr(connector, "_is_enabled", lambda *_: True)
    with pytest.raises(ValueError):
        connector._posix_mcp_settings(
            root,
            {"cloudOrigin": ORIGIN},
            LocalRegisteredRead(root / "key", tmp_path, "board"),
            connector._FOREGROUND_FILE,
        )
    assert not list(outside.iterdir())


@pytest.mark.asyncio
@pytest.mark.parametrize("secondary", [False, True])
async def test_posix_signed_schematic_request_uses_real_verifier(
    tmp_path, monkeypatch, secondary
) -> None:
    from contextlib import asynccontextmanager

    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from kicad_mcp.cloud_generic_mcp_transport import GenericMcpTransportError
    from tests.cloud.test_generic_mcp_adversarial import (
        DEVICE,
        PROJECT,
        SESSION,
        frame,
        signed_proof,
    )
    from tests.cloud.test_generic_mcp_transport import FakeWorker

    root = tmp_path / "registry"
    root.mkdir(mode=0o700)
    board = tmp_path / "board"
    board.mkdir()
    (board / "board.kicad_pro").write_text("{}")
    (board / "board.kicad_sch").write_text("(kicad_sch)")
    key = Ed25519PrivateKey.generate()
    monkeypatch.setattr(
        "kicad_mcp.cloud_windows_write_issuer.load_bundled_cloud_issuer", lambda _: key.public_key()
    )
    monkeypatch.setattr(connector, "_is_enabled", lambda *_: True)
    events = []

    @asynccontextmanager
    async def worker(directory, *, profile, operating_mode):
        assert directory == board and profile == "expert" and operating_mode == "write"
        events.append("worker")
        yield FakeWorker()

    monkeypatch.setattr("kicad_mcp.cloud_generic_mcp_transport.project_stdio_worker", worker)
    record = {
        "cloudOrigin": ORIGIN,
        "deviceId": DEVICE,
        "projectId": PROJECT,
        "ownerSub": "owner",
        "keySlot": str(uuid4()),
    }
    primary = board
    if secondary:
        from kicad_mcp.cloud_posix_project_bindings import folder_service

        primary = tmp_path / "primary"
        primary.mkdir()
        record["projectId"] = str(uuid4())
        (primary / "board.kicad_pro").write_text("{}")
        folder = folder_service(
            root,
            record,
            LocalRegisteredRead(root / "key", primary, "board"),
            lambda: True,
            native_picker=lambda: board,
        )
        token = folder.choose()["projects"][0]["id"]
        assert folder.bind(token, PROJECT)
    settings = connector._posix_mcp_settings(
        root,
        record,
        LocalRegisteredRead(root / "key", primary, "board"),
        connector._FOREGROUND_FILE,
    )
    service = settings["mcp_bridge_factory"](HandshakeReceipt(DEVICE, SESSION))
    args = '{"reference":"R9"}'
    request = frame("call", args=args, proof=signed_proof(key, args))
    FakeWorker.calls.clear()
    with pytest.raises(GenericMcpTransportError):
        await service.dispatch(frame("call", args=args))
    assert events == []
    result = await service.dispatch(request)
    assert result["ok"] is True
    assert ("sch_add_symbol", {"reference": "R9"}) in FakeWorker.calls
    with pytest.raises(GenericMcpTransportError):
        await service.dispatch(request)
    assert events == ["worker"]


def test_posix_explicit_secondary_project_binding(tmp_path, monkeypatch) -> None:
    from kicad_mcp import cloud_posix_project_bindings as bindings
    from kicad_mcp.cloud_local_folder_browser import LocalFolderBrowser

    root = tmp_path / "registry"
    root.mkdir(mode=0o700)
    primary = tmp_path / "first"
    primary.mkdir()
    secondary = tmp_path / "second"
    secondary.mkdir()
    selected = secondary / "second.kicad_pro"
    selected.write_text("{}")
    record = {
        "ownerSub": "owner",
        "cloudOrigin": ORIGIN,
        "deviceId": str(uuid4()),
        "projectId": str(uuid4()),
        "keySlot": str(uuid4()),
    }
    project = LocalRegisteredRead(root / "key.pem", primary, "first")
    state = {"authorized": True}
    monkeypatch.setattr(connector, "_is_enabled", lambda *_: state["authorized"])
    pid = str(uuid4())
    legacy = tmp_path / "legacy.json"
    browser = LocalFolderBrowser([], legacy)
    monkeypatch.setattr(
        "kicad_mcp.cloud_folder_browse_receiver.default_bindings_file", lambda: legacy
    )
    options = connector._posix_mcp_settings(root, record, project, connector._FOREGROUND_FILE)
    service = options["mcp_bridge_factory"](HandshakeReceipt(record["deviceId"], str(uuid4())))
    token = browser.choose_native(lambda: secondary)["projects"][0]["id"]
    assert browser.bind(token, pid)
    # A legacy unscoped mapping alone cannot authorize an edit.
    with pytest.raises(ValueError):
        service._current_project(pid)
    folder = bindings.folder_service(
        root, record, project, lambda: state["authorized"], native_picker=lambda: secondary
    )
    token = folder.choose()["projects"][0]["id"]
    assert folder.bind(token, pid)
    assert service._current_project(pid).directory == secondary
    assert service._current_project(pid).filename_stem == "second"
    assert folder.project_path(pid) == str(selected)
    assert not (root / "unused-browser-cache.json").exists()
    (primary / "first.kicad_pro").write_text("{}")
    conflicting = bindings.folder_service(
        root, record, project, lambda: True, native_picker=lambda: primary
    )
    conflicting_token = conflicting.choose()["projects"][0]["id"]
    assert not conflicting.bind(conflicting_token, pid)
    assert folder.project_path(pid) == str(selected)
    other = {**record, "deviceId": str(uuid4())}
    assert bindings.resolve_secondary(root, other, pid) is None
    # A replaced project path may not silently change the bound file.
    selected.unlink()
    with pytest.raises(ValueError):
        service._current_project(pid)
    state["authorized"] = False
    with pytest.raises(ValueError):
        service._current_project(record["projectId"])
