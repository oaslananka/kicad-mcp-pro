"""Device-only Cloud bootstrap must never execute KiCad or project MCP tools."""

import asyncio
import json
from typing import Any

import pytest

from kicad_mcp.cloud_outbound_handshake import CloudHandshakeDeniedError, HandshakeReceipt

DEVICE = "11111111-1111-4111-8111-111111111111"
SESSION = "33333333-3333-4333-8333-333333333333"
PROJECT = "22222222-2222-4222-8222-222222222222"
REQUEST = "44444444-4444-4444-8444-444444444444"


def folder_request(operation: str, **args: str) -> str:
    return json.dumps(
        {
            "kind": "connector.local_browser_request",
            "version": 1,
            "requestId": REQUEST,
            "operation": operation,
            **args,
        }
    )


class Socket:
    def __init__(self, incoming: list[str]) -> None:
        self.incoming = asyncio.Queue()
        for request in incoming:
            self.incoming.put_nowait(request)
        self.sent: list[dict[str, Any]] = []

    async def recv(self) -> str:
        return await self.incoming.get()

    async def send(self, raw: str) -> None:
        self.sent.append(json.loads(raw))


class OwnerFolder:
    def __init__(self) -> None:
        self.bound = []

    def choose(self) -> dict[str, object]:
        return {
            "status": "selected",
            "folderId": "token",
            "name": "Board",
            "projects": [{"id": "token", "name": "Board"}],
        }

    def list(self, folder_id: str) -> dict[str, object]:
        return {
            "folderId": folder_id,
            "name": "Board",
            "parentId": None,
            "project": True,
            "more": False,
            "folders": [],
        }

    def bind(self, folder_id: str, project_id: str) -> bool:
        self.bound.append((folder_id, project_id))
        return True

    def project_path(self, project_id: str) -> str | None:
        return None


@pytest.mark.asyncio
async def test_unbound_device_serves_owner_browser_then_restarts_after_bound_project() -> None:
    from kicad_mcp.cloud_managed_read_transport import serve_owner_folder_only

    service = OwnerFolder()
    socket = Socket(
        [folder_request("choose"), folder_request("bind", folderId="token", projectId=PROJECT)]
    )
    events = []
    assert await asyncio.wait_for(
        serve_owner_folder_only(
            socket, HandshakeReceipt(DEVICE, SESSION), service, on_activity=events.append
        ),
        timeout=2,
    ) == HandshakeReceipt(DEVICE, SESSION)
    assert [x["operation"] for x in socket.sent] == ["choose", "bind"]
    assert socket.sent[0]["status"] == "selected"
    assert socket.sent[1]["ok"] is True
    assert service.bound == [("token", PROJECT)]
    assert "Opening Windows project folder dialog" in events


@pytest.mark.asyncio
async def test_unbound_device_rejects_mcp_and_native_write_frames() -> None:
    from kicad_mcp.cloud_managed_read_transport import serve_owner_folder_only

    for kind in ("connector.mcp_request", "connector.authorized_read", "connector.write_request"):
        socket = Socket([json.dumps({"kind": kind, "version": 1})])
        with pytest.raises(CloudHandshakeDeniedError):
            await asyncio.wait_for(
                serve_owner_folder_only(socket, HandshakeReceipt(DEVICE, SESSION), OwnerFolder()),
                timeout=2,
            )
        assert socket.sent == []


def test_folder_only_handshake_cannot_claim_generic_or_native_write() -> None:
    from kicad_mcp.cloud_outbound_handshake import (
        OutboundSessionOptions,
        _catalog_hello_metadata,
        _validate_outbound_options,
    )

    def factory(_receipt: HandshakeReceipt) -> OwnerFolder:
        return OwnerFolder()

    options = OutboundSessionOptions(owner_folder_only=True, folder_service_factory=factory)
    _validate_outbound_options(options)
    assert _catalog_hello_metadata(options) == {"folderBrowse": 1}
    for invalid in (
        OutboundSessionOptions(owner_folder_only=True),
        OutboundSessionOptions(
            owner_folder_only=True, folder_service_factory=factory, managed_native_drc=True
        ),
        OutboundSessionOptions(
            owner_folder_only=True, folder_service_factory=factory, owner_managed_read=True
        ),
        OutboundSessionOptions(
            owner_folder_only=True,
            folder_service_factory=factory,
            mcp_service_factory=lambda _: None,
        ),
        OutboundSessionOptions(
            owner_folder_only=True,
            folder_service_factory=factory,
            dispatcher_factory=lambda _: None,
        ),
    ):
        with pytest.raises(CloudHandshakeDeniedError):
            _validate_outbound_options(invalid)


@pytest.mark.asyncio
async def test_owner_folder_only_handshake_has_no_project_dispatcher(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from kicad_mcp import cloud_outbound_handshake as transport

    async def simulate(**kwargs: object) -> HandshakeReceipt:
        options = kwargs["options"]
        assert isinstance(options, transport.OutboundSessionOptions)
        assert options.owner_folder_only is True
        assert options.owner_managed_read is False
        assert options.dispatcher_factory is None
        assert options.mcp_service_factory is None
        assert options.managed_native_write is False
        assert options.folder_service_factory is not None
        return HandshakeReceipt(DEVICE, SESSION)

    monkeypatch.setattr(transport, "_perform_outbound_session", simulate)
    result = await transport.execute_owner_folder_only_session(
        origin="https://cloud.example",
        trusted_origin="https://cloud.example",
        owner_sub="owner",
        device_id=DEVICE,
        signing_key=Ed25519PrivateKey.generate(),
        folder_service_factory=lambda _receipt: OwnerFolder(),
    )
    assert result == HandshakeReceipt(DEVICE, SESSION)
