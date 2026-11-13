"""Bounded managed reads over a separately authenticated outbound Cloud socket.

This is *post-handshake* transport only: no key access, enrollment, background
process, connection creation, or server-side OAuth authority is implemented here.
The caller must independently establish the signed device/session receipt and
owner-selected local project and its live authorization predicate.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import Protocol

from kicad_mcp.cloud_folder_browse_receiver import (
    LocalFolderBrowseService,
    handle_folder_frame,
)
from kicad_mcp.cloud_outbound_handshake import (
    CloudHandshakeDeniedError,
    HandshakeReceipt,
    _read_strict_json,
)
from kicad_mcp.cloud_read_dispatch import LocalReadDispatch

_DENIED = "handshake denied"
_MAX_MANAGED_READS = 16
_SESSION_TIMEOUT_SECONDS = 295
_FOLDER_REQUEST_KIND = "connector.local_browser_request"


def _report_activity(callback: Callable[[str], None] | None, message: str) -> None:
    """Diagnostic callbacks are best-effort, never part of local authorization."""
    if callback is None:
        return
    try:
        callback(message)
    except Exception:
        return  # A broken console must never cancel a signed MCP response.


class AuthenticatedReadSocket(Protocol):
    """A socket *already* authenticated by the existing signed WSS handshake."""

    async def recv(self) -> str | bytes: ...

    async def send(self, message: str) -> None: ...


def _decode_sequenced_request(raw: str | bytes, expected_sequence: int) -> bytes:
    if not isinstance(raw, str):
        raise CloudHandshakeDeniedError(_DENIED)
    envelope = _read_strict_json(raw, "connector.authorized_read")
    if (
        set(envelope) != {"kind", "version", "sequence", "request"}
        or type(envelope["version"]) is not int
        or envelope["version"] != 1
        or type(envelope["sequence"]) is not int
        or envelope["sequence"] != expected_sequence
        or not isinstance(envelope["request"], dict)
    ):
        raise CloudHandshakeDeniedError(_DENIED)
    return json.dumps(envelope["request"], ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )


def _top_level_kind(raw: str) -> object:
    """Cheap kind probe for dispatch; full validation happens per protocol."""
    try:
        message = json.loads(raw)
    except (ValueError, TypeError):
        return None
    return message.get("kind") if isinstance(message, dict) else None


def _validate_read_ack(raw: str | bytes, expected_sequence: int, request_id: object) -> None:
    if not isinstance(raw, str):
        raise CloudHandshakeDeniedError(_DENIED)
    ack = _read_strict_json(raw, "connector.read_ack")
    if (
        set(ack) != {"kind", "version", "sequence", "requestId"}
        or type(ack["version"]) is not int
        or ack["version"] != 1
        or type(ack["sequence"]) is not int
        or ack["sequence"] != expected_sequence
        or ack["requestId"] != request_id
    ):
        raise CloudHandshakeDeniedError(_DENIED)


async def _serve_one_authenticated_read(
    socket: AuthenticatedReadSocket,
    dispatcher: LocalReadDispatch,
    receipt: HandshakeReceipt,
    expected_sequence: int,
) -> None:
    frame = _decode_sequenced_request(await socket.recv(), expected_sequence)
    response = await asyncio.to_thread(dispatcher.read, frame, sequence=expected_sequence)
    # The local grant can be revoked during inspection. Never interpret the
    # initial read as permission to send later.
    dispatcher.assert_delivery_authorized(
        frame, device_id=receipt.device_id, session_id=receipt.session_id
    )
    await socket.send(
        json.dumps(
            {
                "kind": "connector.read_result",
                "version": 1,
                "sequence": expected_sequence,
                "result": response,
            },
            separators=(",", ":"),
        )
    )
    _validate_read_ack(await socket.recv(), expected_sequence, response["requestId"])


async def _serve_folder_request(
    socket: AuthenticatedReadSocket, service: LocalFolderBrowseService, raw: str
) -> None:
    """Answer one owner-initiated opaque-token folder frame; sequences untouched."""
    response = await asyncio.to_thread(handle_folder_frame, service, raw)
    encoded = json.dumps(response, separators=(",", ":"), ensure_ascii=False)
    if len(encoded.encode("utf-8")) > 8192:
        raise CloudHandshakeDeniedError(_DENIED)
    await socket.send(encoded)


async def serve_authenticated_reads(
    socket: AuthenticatedReadSocket,
    receipt: HandshakeReceipt,
    dispatcher_factory: Callable[[HandshakeReceipt], LocalReadDispatch],
    *,
    max_reads: int = _MAX_MANAGED_READS,
    folder_service: LocalFolderBrowseService | None = None,
    allow_native_drc: bool = False,
    on_activity: Callable[[str], None] | None = None,
) -> HandshakeReceipt:
    """Serve bounded serial, independently authorized READs on a signed socket.

    Does not grant any read by itself. Dispatcher's independently sourced
    authorization is checked around every file read and before each send;
    Cloud must also recheck OAuth/client/project and owner On/Off after receipt.
    The caller owns the signed socket lifecycle and handles disconnect/retry.

    When an owner-operated folder browse service is attached, interleaved
    ``connector.local_browser_request`` frames are answered between reads
    without consuming or altering any read sequence. Frame handling remains
    fail-closed: any invalid frame ends the signed session.
    """
    if (
        not isinstance(receipt, HandshakeReceipt)
        or not callable(dispatcher_factory)
        or type(max_reads) is not int
        or not 1 <= max_reads <= _MAX_MANAGED_READS
        or (folder_service is not None and not callable(getattr(folder_service, "list", None)))
        or type(allow_native_drc) is not bool
        or (on_activity is not None and not callable(on_activity))
    ):
        raise CloudHandshakeDeniedError(_DENIED)

    dispatcher = dispatcher_factory(receipt)
    if not isinstance(dispatcher, LocalReadDispatch) or dispatcher.native_drc != allow_native_drc:
        raise CloudHandshakeDeniedError(_DENIED)
    try:
        dispatcher.assert_transport_session(
            device_id=receipt.device_id, session_id=receipt.session_id
        )
        try:
            async with asyncio.timeout(_SESSION_TIMEOUT_SECONDS):
                reads_served = 0
                while reads_served < max_reads:
                    # A folder frame may arrive between reads. Dispatch on the
                    # top-level kind without consuming the read sequence budget.
                    raw = await socket.recv()
                    if not isinstance(raw, str):
                        raise CloudHandshakeDeniedError(_DENIED)
                    kind = _top_level_kind(raw)
                    if kind == _FOLDER_REQUEST_KIND:
                        if folder_service is None:
                            raise CloudHandshakeDeniedError(_DENIED)
                        await _serve_folder_request(socket, folder_service, raw)
                        _report_activity(on_activity, "Folder browsing request completed")
                        continue
                    if kind != "connector.authorized_read":
                        raise CloudHandshakeDeniedError(_DENIED)
                    frame = _decode_sequenced_request(raw, reads_served + 1)
                    response = await asyncio.to_thread(
                        dispatcher.read, frame, sequence=reads_served + 1
                    )
                    # The local grant can be revoked during inspection. Never
                    # interpret the initial read as permission to send later.
                    dispatcher.assert_delivery_authorized(
                        frame, device_id=receipt.device_id, session_id=receipt.session_id
                    )
                    await socket.send(
                        json.dumps(
                            {
                                "kind": "connector.read_result",
                                "version": 1,
                                "sequence": reads_served + 1,
                                "result": response,
                            },
                            separators=(",", ":"),
                        )
                    )
                    _validate_read_ack(await socket.recv(), reads_served + 1, response["requestId"])
                    reads_served += 1
                    operation = response.get("operation")
                    safe = operation if operation in {"project_summary", "run_drc"} else "read"
                    _report_activity(on_activity, f"Tool call {reads_served}: {safe} completed")
        except TimeoutError as exc:
            raise CloudHandshakeDeniedError(_DENIED) from exc
        return receipt
    finally:
        dispatcher.close()
