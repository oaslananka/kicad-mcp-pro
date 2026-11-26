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
async def test_posix_signed_schematic_request_uses_real_verifier(tmp_path, monkeypatch) -> None:
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
    record = {"cloudOrigin": ORIGIN, "deviceId": DEVICE, "projectId": PROJECT}
    settings = connector._posix_mcp_settings(
        root, record, LocalRegisteredRead(root / "key", board, "board"), connector._FOREGROUND_FILE
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
