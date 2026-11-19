"""Bounded managed reads over a separately authenticated outbound Cloud socket.

This is *post-handshake* transport only: no key access, enrollment, background
process, connection creation, or server-side OAuth authority is implemented here.
The caller must independently establish the signed device/session receipt and
owner-selected local project and its live authorization predicate.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Callable
from time import perf_counter
from typing import Any, Protocol
from uuid import UUID

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


class GenericMcpDispatch(Protocol):
    async def dispatch(self, frame: dict[str, Any]) -> dict[str, object]: ...


_DENIED = "handshake denied"
_MAX_MANAGED_READS = 16
_SESSION_TIMEOUT_SECONDS = 295
# Refresh well before the signed server-side five-minute session lease expires.
# Only the idle recv waits for this deadline; an in-flight tool is never cut short.
_SESSION_REFRESH_SECONDS = 240
_FOLDER_REQUEST_KIND = "connector.local_browser_request"
_WRITE_REQUEST_KIND = "connector.authorized_write"
_MCP_REQUEST_KIND = "connector.mcp_request"
# Only the bounded ASCII tool identifier may appear in human-readable activity.
_SAFE_ACTIVITY_TOOL = re.compile(r"[a-z][a-z0-9_]{0,63}", re.ASCII)


def _canonical_project_id(value: object) -> str:
    """An untrusted Cloud-supplied project id is a lookup only, never approval."""
    if not isinstance(value, str) or len(value) != 36:
        raise CloudHandshakeDeniedError(_DENIED)
    try:
        if str(UUID(value)) != value:
            raise CloudHandshakeDeniedError(_DENIED)
    except (TypeError, ValueError) as exc:
        raise CloudHandshakeDeniedError(_DENIED) from exc
    return value


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
    revisions_preparer: Callable[[str], dict[str, str]] | None,
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
    project_id = _canonical_project_id(req["projectId"])
    revisions = await asyncio.to_thread(revisions_preparer, project_id)
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
    write_executor: Callable[[str, bytes, bool], dict[str, object]] | None,
    fallback_seq: int,
    on_activity: Callable[[str], None] | None,
) -> dict[str, object]:
    if not allow_native_write or write_executor is None:
        raise CloudHandshakeDeniedError(_DENIED)
    envelope = _read_strict_json(raw, _WRITE_REQUEST_KIND)
    if envelope.get("version") != 1 or not isinstance(envelope.get("proof"), dict):
        raise CloudHandshakeDeniedError(_DENIED)
    project_id = _canonical_project_id(envelope.get("projectId"))
    proof_bytes = json.dumps(envelope["proof"], separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )
    persist = envelope.get("persistToDisk", True)
    if type(persist) is not bool:
        raise CloudHandshakeDeniedError(_DENIED)
    _report_activity(on_activity, "Cloud WRITE envelope validated")
    try:
        result = await asyncio.to_thread(write_executor, project_id, proof_bytes, persist)
    except Exception:
        _report_activity(on_activity, "Cloud WRITE local executor rejected")
        raise
    _report_activity(on_activity, "Cloud WRITE local executor returned")
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
    _report_activity(on_activity, "Cloud WRITE response acknowledged")
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
        _report_activity(on_activity, "Opening Windows project folder dialog")
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


async def _serve_one_mcp_request(
    socket: AuthenticatedReadSocket,
    service: GenericMcpDispatch,
    raw: str,
    *,
    expected_sequence: int,
) -> dict[str, object]:
    """Execute one bounded generic MCP operation on this signed device socket."""
    frame = _read_strict_json(raw, _MCP_REQUEST_KIND)
    if (
        set(frame) != {"kind", "version", "sequence", "request"}
        or type(frame.get("version")) is not int
        or frame["version"] != 1
        or type(frame.get("sequence")) is not int
        or frame["sequence"] != expected_sequence
        or not isinstance(frame.get("request"), dict)
        or not callable(getattr(service, "dispatch", None))
    ):
        raise CloudHandshakeDeniedError(_DENIED)
    request = frame["request"]
    if not isinstance(request, dict):
        raise CloudHandshakeDeniedError(_DENIED)
    response = await service.dispatch(request)
    if not isinstance(response, dict) or response.get("requestId") != request.get("requestId"):
        raise CloudHandshakeDeniedError(_DENIED)
    await socket.send(
        json.dumps(
            {
                "kind": "connector.mcp_result",
                "version": 1,
                "sequence": expected_sequence,
                "result": response,
            },
            separators=(",", ":"),
            ensure_ascii=False,
        )
    )
    raw_ack = await socket.recv()
    if not isinstance(raw_ack, str):
        raise CloudHandshakeDeniedError(_DENIED)
    ack = _read_strict_json(raw_ack, "connector.mcp_ack")
    if (
        set(ack) != {"kind", "version", "sequence", "requestId"}
        or type(ack.get("version")) is not int
        or ack["version"] != 1
        or type(ack.get("sequence")) is not int
        or ack["sequence"] != expected_sequence
        or ack.get("requestId") != response["requestId"]
    ):
        raise CloudHandshakeDeniedError(_DENIED)
    return response


def _verified_mcp_activity_request(raw: str, expected_sequence: int) -> dict[str, Any] | None:
    """Read the signed envelope's diagnostic metadata, without logging its arguments."""
    try:
        frame = _read_strict_json(raw, _MCP_REQUEST_KIND)
    except ValueError:
        return None
    if (
        set(frame) != {"kind", "version", "sequence", "request"}
        or type(frame.get("version")) is not int
        or frame["version"] != 1
        or type(frame.get("sequence")) is not int
        or frame["sequence"] != expected_sequence
    ):
        return None
    request = frame.get("request")
    return request if isinstance(request, dict) else None


def _mcp_activity_tool(raw: str, expected_sequence: int) -> str | None:
    """Return only a bounded, validated MCP tool name; never expose parameters."""
    operation = _verified_mcp_activity_request(raw, expected_sequence)
    if operation is None:
        return None
    if operation.get("method") == "catalog":
        return "catalog"
    if operation.get("method") != "call":
        return None
    tool = operation.get("toolName")
    if isinstance(tool, str) and _SAFE_ACTIVITY_TOOL.fullmatch(tool) is not None:
        return tool
    return None


async def _serve_one_signed_frame(
    socket: AuthenticatedReadSocket,
    raw: str,
    reads_served: int,
    dispatcher: LocalReadDispatch,
    receipt: HandshakeReceipt,
    folder_service: LocalFolderBrowseService | None,
    on_activity: Callable[[str], None] | None,
    allow_native_write: bool = False,
    revisions_preparer: Callable[[str], dict[str, str]] | None = None,
    write_executor: Callable[[str, bytes, bool], dict[str, object]] | None = None,
    mcp_service: GenericMcpDispatch | None = None,
) -> int:
    """Serve a single authenticated frame; return 1 if frame counts as a read/write, else 0."""
    kind = _top_level_kind(raw)
    if kind == _FOLDER_REQUEST_KIND:
        return await _serve_folder_frame(socket, raw, folder_service, on_activity)
    if kind == "connector.prepare_write_revisions":
        await _serve_write_revisions_request(socket, raw, allow_native_write, revisions_preparer)
        _report_activity(on_activity, "Write revision preparation completed")
        return 0
    if kind not in {_WRITE_REQUEST_KIND, "connector.authorized_read", _MCP_REQUEST_KIND}:
        raise CloudHandshakeDeniedError(_DENIED)
    sequence = reads_served + 1
    is_write = kind == _WRITE_REQUEST_KIND
    is_mcp = kind == _MCP_REQUEST_KIND
    if is_mcp:
        name = _mcp_activity_tool(raw, sequence)
        label = "mcp " + name if name is not None else "mcp"
    elif is_write:
        label = "write"
    else:
        label = "read"
    start = perf_counter()
    _report_activity(on_activity, f"Tool call {sequence}: {label} started")
    try:
        if is_mcp:
            if mcp_service is None:
                raise CloudHandshakeDeniedError(_DENIED)
            result = await _serve_one_mcp_request(
                socket, mcp_service, raw, expected_sequence=sequence
            )
        elif is_write:
            result = await _serve_authorized_write_request(
                socket, raw, allow_native_write, write_executor, sequence, on_activity
            )
        else:
            result = await _serve_one_authenticated_read(socket, dispatcher, receipt, sequence, raw)
    except Exception:
        _report_activity(on_activity, f"Tool call {sequence}: {label} failed")
        raise
    operation = result.get("operation")
    safe = operation if operation in {"project_summary", "run_drc", "pcb_move_footprint"} else label
    elapsed = round((perf_counter() - start) * 1000)
    # Transport delivery may succeed while the acknowledged MCP tool reports
    # isError=true (for example, a bounded local DRC/ERC timeout).
    outcome = "completed"
    if is_mcp:
        if result.get("ok") is False:
            outcome = "failed"
        elif result.get("method") == "call":
            tool_result = result.get("result")
            if isinstance(tool_result, dict) and tool_result.get("isError") is True:
                outcome = "failed"
    _report_activity(on_activity, f"Tool call {sequence}: {safe} {outcome} ({elapsed} ms)")
    return 1


async def _serve_signed_read_frames(
    socket: AuthenticatedReadSocket,
    dispatcher: LocalReadDispatch,
    receipt: HandshakeReceipt,
    max_reads: int,
    folder_service: LocalFolderBrowseService | None,
    on_activity: Callable[[str], None] | None,
    allow_native_write: bool = False,
    revisions_preparer: Callable[[str], dict[str, str]] | None = None,
    write_executor: Callable[[str, bytes, bool], dict[str, object]] | None = None,
    mcp_service: GenericMcpDispatch | None = None,
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
            mcp_service,
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
    revisions_preparer: Callable[[str], dict[str, str]] | None = None,
    write_executor: Callable[[str, bytes, bool], dict[str, object]] | None = None,
    mcp_service_factory: Callable[[HandshakeReceipt], GenericMcpDispatch] | None = None,
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
        or (mcp_service_factory is not None and not callable(mcp_service_factory))
        or (on_activity is not None and not callable(on_activity))
    ):
        raise CloudHandshakeDeniedError(_DENIED)

    dispatcher = dispatcher_factory(receipt)
    mcp_service = mcp_service_factory(receipt) if mcp_service_factory is not None else None
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
                    mcp_service=mcp_service,
                )
        except TimeoutError as exc:
            raise CloudHandshakeDeniedError(_DENIED) from exc
        return receipt
    finally:
        dispatcher.close()
