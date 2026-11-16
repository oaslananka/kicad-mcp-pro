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
from time import perf_counter
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
# Refresh well before the signed server-side five-minute session lease expires.
# Only the idle recv waits for this deadline; an in-flight tool is never cut short.
_SESSION_REFRESH_SECONDS = 240
_FOLDER_REQUEST_KIND = "connector.local_browser_request"
_WRITE_REQUEST_KIND = "connector.authorized_write"
_READ_REQUEST_KIND = "connector.authorized_read"


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
    envelope = _read_strict_json(raw, _READ_REQUEST_KIND)
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
    raw: str | None = None,
) -> dict[str, object]:
    frame = _decode_sequenced_request(
        raw if raw is not None else await socket.recv(), expected_sequence
    )
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
    return response


async def _serve_folder_request(
    socket: AuthenticatedReadSocket, service: LocalFolderBrowseService, raw: str
) -> dict[str, object]:
    """Answer one owner-initiated opaque-token folder frame; sequences untouched."""
    response = await asyncio.to_thread(handle_folder_frame, service, raw)
    encoded = json.dumps(response, separators=(",", ":"), ensure_ascii=False)
    if len(encoded.encode("utf-8")) > 8192:
        raise CloudHandshakeDeniedError(_DENIED)
    await socket.send(encoded)
    return response


async def _serve_write_revisions_request(
    socket: AuthenticatedReadSocket,
    raw: str,
    allow_native_write: bool,
    revisions_preparer: Callable[[], dict[str, str]] | None,
) -> None:
    if not allow_native_write or revisions_preparer is None:
        raise CloudHandshakeDeniedError(_DENIED)
    req = _read_strict_json(raw, "connector.prepare_write_revisions")
    if (
        req.get("version") != 1
        or not isinstance(req.get("requestId"), str)
        or not isinstance(req.get("deviceId"), str)
        or not isinstance(req.get("projectId"), str)
    ):
        raise CloudHandshakeDeniedError(_DENIED)
    revisions = await asyncio.to_thread(revisions_preparer)
    await socket.send(
        json.dumps(
            {
                "kind": "connector.write_revisions_result",
                "version": 1,
                "requestId": req["requestId"],
                **revisions,
            },
            separators=(",", ":"),
        )
    )


async def _serve_authorized_write_request(
    socket: AuthenticatedReadSocket,
    raw: str,
    allow_native_write: bool,
    write_executor: Callable[[bytes, bool], dict[str, object]] | None,
    fallback_seq: int,
) -> dict[str, object]:
    if not allow_native_write or write_executor is None:
        raise CloudHandshakeDeniedError(_DENIED)
    envelope = _read_strict_json(raw, _WRITE_REQUEST_KIND)
    if envelope.get("version") != 1 or not isinstance(envelope.get("proof"), dict):
        raise CloudHandshakeDeniedError(_DENIED)
    proof_bytes = json.dumps(envelope["proof"], separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )
    persist = bool(envelope.get("persistToDisk", True))
    result = await asyncio.to_thread(write_executor, proof_bytes, persist)
    seq_val = envelope.get("sequence")
    seq = int(seq_val) if isinstance(seq_val, (int, str)) else fallback_seq
    await socket.send(
        json.dumps(
            {
                "kind": "connector.write_result",
                "version": 1,
                "sequence": seq,
                "result": result,
            },
            separators=(",", ":"),
        )
    )
    raw_ack = await socket.recv()
    if not isinstance(raw_ack, str):
        raise CloudHandshakeDeniedError(_DENIED)
    ack = _read_strict_json(raw_ack, "connector.write_ack")
    if (
        ack.get("version") != 1
        or ack.get("sequence") != seq
        or ack.get("requestId") != result.get("requestId")
    ):
        raise CloudHandshakeDeniedError(_DENIED)
    return result


async def _serve_folder_frame(
    socket: AuthenticatedReadSocket,
    raw: str,
    folder_service: LocalFolderBrowseService | None,
    on_activity: Callable[[str], None] | None,
) -> int:
    """Handle the owner-initiated native folder dialog without consuming a tool slot."""
    if folder_service is None:
        raise CloudHandshakeDeniedError(_DENIED)
    # The operation is still strictly validated by handle_folder_frame.
    # This hint contains no user path, device key or private project data.
    try:
        operation = json.loads(raw).get("operation")
    except (ValueError, TypeError, AttributeError):
        operation = None
    if operation == "choose":
        _report_activity(on_activity, "Opening local project folder dialog")
    result = await _serve_folder_request(socket, folder_service, raw)
    if operation == "choose":
        status = result.get("status")
        _report_activity(
            on_activity,
            "Folder selection "
            + (status if status in {"selected", "cancelled", "invalid"} else "finished"),
        )
    else:
        _report_activity(on_activity, "Folder request completed")
    return 0


def _requested_display_operation(raw: str, kind: object) -> str:
    """Return an allowlisted tool label, never caller-supplied paths or arguments."""
    fallback = "write" if kind == _WRITE_REQUEST_KIND else "read"
    if kind != _READ_REQUEST_KIND:
        # Native write proof contains an opaque signed payload; the verified
        # operation is reported only after local execution acknowledges it.
        return fallback
    try:
        envelope = json.loads(raw)
    except (ValueError, TypeError):
        return fallback
    if not isinstance(envelope, dict):
        return fallback
    request = envelope.get("request")
    if not isinstance(request, dict):
        return fallback
    operation = request.get("operation")
    return (
        operation
        if isinstance(operation, str) and operation in {"project_summary", "run_drc"}
        else fallback
    )


async def _serve_one_signed_frame(
    socket: AuthenticatedReadSocket,
    raw: str,
    reads_served: int,
    dispatcher: LocalReadDispatch,
    receipt: HandshakeReceipt,
    folder_service: LocalFolderBrowseService | None,
    on_activity: Callable[[str], None] | None,
    allow_native_write: bool = False,
    revisions_preparer: Callable[[], dict[str, str]] | None = None,
    write_executor: Callable[[bytes, bool], dict[str, object]] | None = None,
) -> int:
    """Serve a single authenticated frame; return 1 if frame counts as a read/write, else 0."""
    kind = _top_level_kind(raw)
    if kind == _FOLDER_REQUEST_KIND:
        return await _serve_folder_frame(socket, raw, folder_service, on_activity)
    if kind == "connector.prepare_write_revisions":
        await _serve_write_revisions_request(socket, raw, allow_native_write, revisions_preparer)
        _report_activity(on_activity, "Write revision preparation completed")
        return 0
    if kind not in {_WRITE_REQUEST_KIND, _READ_REQUEST_KIND}:
        raise CloudHandshakeDeniedError(_DENIED)
    sequence = reads_served + 1
    is_write = kind == _WRITE_REQUEST_KIND
    label = "write" if is_write else "read"
    safe_requested = _requested_display_operation(raw, kind)
    start = perf_counter()
    _report_activity(on_activity, f"Tool call {sequence}: {safe_requested} started")
    try:
        if is_write:
            result = await _serve_authorized_write_request(
                socket, raw, allow_native_write, write_executor, sequence
            )
        else:
            result = await _serve_one_authenticated_read(socket, dispatcher, receipt, sequence, raw)
    except Exception:
        elapsed = round((perf_counter() - start) * 1000)
        _report_activity(
            on_activity, f"Tool call {sequence}: {safe_requested} failed ({elapsed} ms)"
        )
        raise
    operation = result.get("operation")
    safe = operation if operation in {"project_summary", "run_drc", "pcb_move_footprint"} else label
    elapsed = round((perf_counter() - start) * 1000)
    # "completed" means the device sent its acknowledged response. It does
    # not assert a successful PCB operation or an external Cloud MCP outcome.
    _report_activity(on_activity, f"Tool call {sequence}: {safe} completed ({elapsed} ms)")
    return 1


async def _serve_signed_read_frames(
    socket: AuthenticatedReadSocket,
    dispatcher: LocalReadDispatch,
    receipt: HandshakeReceipt,
    max_reads: int,
    folder_service: LocalFolderBrowseService | None,
    on_activity: Callable[[str], None] | None,
    allow_native_write: bool = False,
    revisions_preparer: Callable[[], dict[str, str]] | None = None,
    write_executor: Callable[[bytes, bool], dict[str, object]] | None = None,
) -> None:
    """Process authenticated frames without charging folder or write prep requests as reads."""
    reads_served = 0
    loop = asyncio.get_running_loop()
    refresh_deadline = loop.time() + _SESSION_REFRESH_SECONDS
    while reads_served < max_reads:
        remaining = refresh_deadline - loop.time()
        if remaining <= 0:
            _report_activity(on_activity, "Refreshing signed Cloud session")
            return
        try:
            raw = await asyncio.wait_for(socket.recv(), timeout=remaining)
        except TimeoutError:
            # This is an expected idle lease refresh, not a failed handshake.
            # Work already dispatched runs to its normal per-command deadline.
            _report_activity(on_activity, "Refreshing signed Cloud session")
            return
        if not isinstance(raw, str):
            raise CloudHandshakeDeniedError(_DENIED)
        reads_served += await _serve_one_signed_frame(
            socket,
            raw,
            reads_served,
            dispatcher,
            receipt,
            folder_service,
            on_activity,
            allow_native_write,
            revisions_preparer,
            write_executor,
        )


async def serve_authenticated_reads(
    socket: AuthenticatedReadSocket,
    receipt: HandshakeReceipt,
    dispatcher_factory: Callable[[HandshakeReceipt], LocalReadDispatch],
    *,
    max_reads: int = _MAX_MANAGED_READS,
    folder_service: LocalFolderBrowseService | None = None,
    allow_native_drc: bool = False,
    allow_native_write: bool = False,
    revisions_preparer: Callable[[], dict[str, str]] | None = None,
    write_executor: Callable[[bytes, bool], dict[str, object]] | None = None,
    on_activity: Callable[[str], None] | None = None,
) -> HandshakeReceipt:
    """Serve bounded serial, independently authorized READs/WRITEs on a signed socket.

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
        or type(allow_native_write) is not bool
        or (allow_native_write and (revisions_preparer is None or write_executor is None))
        or (revisions_preparer is not None and not callable(revisions_preparer))
        or (write_executor is not None and not callable(write_executor))
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
                await _serve_signed_read_frames(
                    socket,
                    dispatcher,
                    receipt,
                    max_reads,
                    folder_service,
                    on_activity,
                    allow_native_write=allow_native_write,
                    revisions_preparer=revisions_preparer,
                    write_executor=write_executor,
                )
        except TimeoutError as exc:
            raise CloudHandshakeDeniedError(_DENIED) from exc
        return receipt
    finally:
        dispatcher.close()
