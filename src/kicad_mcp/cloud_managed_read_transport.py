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

from kicad_mcp.cloud_outbound_handshake import (
    CloudHandshakeDeniedError,
    HandshakeReceipt,
    _read_strict_json,
)
from kicad_mcp.cloud_read_dispatch import LocalReadDispatch

_DENIED = "handshake denied"
_MAX_MANAGED_READS = 16
_SESSION_TIMEOUT_SECONDS = 295


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


async def serve_authenticated_reads(
    socket: AuthenticatedReadSocket,
    receipt: HandshakeReceipt,
    dispatcher_factory: Callable[[HandshakeReceipt], LocalReadDispatch],
    *,
    max_reads: int = _MAX_MANAGED_READS,
) -> HandshakeReceipt:
    """Serve bounded serial project-summary reads on an already signed socket.

    Does not grant any read by itself. Dispatcher's independently sourced
    authorization is checked around every file read and before each send;
    Cloud must also recheck OAuth/client/project and owner On/Off after receipt.
    The caller owns the signed socket lifecycle and handles disconnect/retry.
    """
    if (
        not isinstance(receipt, HandshakeReceipt)
        or not callable(dispatcher_factory)
        or type(max_reads) is not int
        or not 1 <= max_reads <= _MAX_MANAGED_READS
    ):
        raise CloudHandshakeDeniedError(_DENIED)

    dispatcher = dispatcher_factory(receipt)
    if not isinstance(dispatcher, LocalReadDispatch) or dispatcher.native_drc:
        raise CloudHandshakeDeniedError(_DENIED)
    try:
        dispatcher.assert_transport_session(
            device_id=receipt.device_id, session_id=receipt.session_id
        )
        try:
            async with asyncio.timeout(_SESSION_TIMEOUT_SECONDS):
                for expected_sequence in range(1, max_reads + 1):
                    await _serve_one_authenticated_read(
                        socket, dispatcher, receipt, expected_sequence
                    )
        except TimeoutError as exc:
            raise CloudHandshakeDeniedError(_DENIED) from exc
        return receipt
    finally:
        dispatcher.close()
