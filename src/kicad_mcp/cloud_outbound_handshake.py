"""Explicit opt-in outbound TLS/WebSocket proof handshake for future KiCad Cloud.

This module does not enroll devices, establish OAuth authorization, read files,
dispatch commands or keep a session alive. A completed handshake is NOT a
project-grant or execution capability. It is never started automatically.
"""

from __future__ import annotations

import asyncio
import json
import re
import ssl
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlsplit

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import WebSocketException

from kicad_mcp.cloud_device_proofs import (
    _unique_keys,
    sign_device_challenge,
    sign_session_challenge,
)
from kicad_mcp.cloud_read_dispatch import LocalReadDispatch

CONNECTOR_WS_PATH = "/api/v1/connector/ws"
_HANDSHAKE_DENIED = "handshake denied"

_DEVICE_UUID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
)
HANDSHAKE_TIMEOUT_SECONDS = 9


class CloudHandshakeDeniedError(ValueError):
    """Generic failure without leaking server frames or credentials."""


@dataclass(frozen=True)
class HandshakeReceipt:
    """Proof exchange completed; expressly NOT an execution authorization."""

    device_id: str
    session_id: str


def _endpoint(*, origin: str, trusted_origin: str) -> str:
    """Require exact independently configured HTTPS Cloud origin."""
    if (
        not isinstance(origin, str)
        or not isinstance(trusted_origin, str)
        or not origin.isascii()
        or not trusted_origin.isascii()
        # urllib.parse silently strips CR, LF, tab and leading C0 controls,
        # while the WSS endpoint below uses the original untrusted bytes.
        or any(ord(char) <= 0x20 or ord(char) == 0x7F for char in origin)
        or any(delimiter in value for value in (origin, trusted_origin) for delimiter in "?#")
    ):
        raise CloudHandshakeDeniedError(_HANDSHAKE_DENIED)
    parsed = urlsplit(origin)
    expected = urlsplit(trusted_origin)
    for item in (parsed, expected):
        if (
            item.scheme != "https"
            or not item.hostname
            or item.username is not None
            or item.password is not None
            or item.path not in ("", "/")
            or item.query
            or item.fragment
            or item.hostname.endswith(".")
        ):
            raise CloudHandshakeDeniedError(_HANDSHAKE_DENIED)
        try:
            if item.port is not None and not (1 <= item.port <= 65535):
                raise CloudHandshakeDeniedError(_HANDSHAKE_DENIED)
        except ValueError as exc:
            raise CloudHandshakeDeniedError(_HANDSHAKE_DENIED) from exc
    if origin != trusted_origin or not origin.startswith("https://"):
        raise CloudHandshakeDeniedError(_HANDSHAKE_DENIED)
    # Use the checked original URL with a scheme swap; it cannot contain
    # embedded credentials, redirects, query parameters or another path.
    return "wss://" + origin[len("https://") :].rstrip("/") + CONNECTOR_WS_PATH


def _read_strict_json(raw: str, expected_kind: str) -> dict[str, object]:
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > 1024:
        raise CloudHandshakeDeniedError(_HANDSHAKE_DENIED)
    try:
        message = json.loads(raw, object_pairs_hook=_unique_keys)
    except (ValueError, TypeError) as exc:
        raise CloudHandshakeDeniedError(_HANDSHAKE_DENIED) from exc
    if not isinstance(message, dict) or message.get("kind") != expected_kind:
        raise CloudHandshakeDeniedError(_HANDSHAKE_DENIED)
    return message


async def _complete_authorized_read(
    socket: ClientConnection,
    receipt: HandshakeReceipt,
    dispatcher_factory: Callable[[HandshakeReceipt], LocalReadDispatch] | None,
    *,
    operator_presence_pilot: bool = False,
    operator_native_drc_pilot: bool = False,
) -> HandshakeReceipt:
    """Complete one bounded presence read, or exit after proof-only mode."""
    device_id = receipt.device_id
    session_id = receipt.session_id
    if dispatcher_factory is None:
        # Proof-only mode retains its original no-command behavior.
        return receipt
    # The independent-authority reader remains strict. Separately named,
    # manually operated pilots may use presence flags or native DRC counts,
    # never arbitrary commands or an unattended general connector.
    if not operator_presence_pilot:
        _require_independent_read_authority()
    # A presence-only entrypoint can never become a native command relay
    # through a caller-supplied dispatcher.
    if dispatcher_factory is None:
        raise CloudHandshakeDeniedError(_HANDSHAKE_DENIED)
    # The caller, not Cloud wire claims, supplies this independent
    # local authorization and owner-approved project selection.
    dispatcher = dispatcher_factory(receipt)
    if (
        not isinstance(dispatcher, LocalReadDispatch)
        or dispatcher.native_drc != operator_native_drc_pilot
    ):
        raise CloudHandshakeDeniedError(_HANDSHAKE_DENIED)
    try:
        dispatcher.assert_transport_session(device_id=device_id, session_id=session_id)
        raw_request = await socket.recv()
        if not isinstance(raw_request, str):
            raise CloudHandshakeDeniedError(_HANDSHAKE_DENIED)
        envelope = _read_strict_json(raw_request, "connector.authorized_read")
        if (
            set(envelope) != {"kind", "version", "sequence", "request"}
            or type(envelope["version"]) is not int
            or envelope["version"] != 1
            or type(envelope["sequence"]) is not int
            or not isinstance(envelope["request"], dict)
        ):
            raise CloudHandshakeDeniedError(_HANDSHAKE_DENIED)
        request_bytes = json.dumps(
            envelope["request"], separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        # read() fences replay, local path, expiry, and real-time
        # authorization; no native KiCad operation is exposed.
        response = await asyncio.to_thread(
            dispatcher.read, request_bytes, sequence=envelope["sequence"]
        )
        # Worker completion is not a delivery capability. The foreground
        # consent/grant and exact signed frame deadline may have expired
        # between read() returning and this WebSocket send.
        dispatcher.assert_delivery_authorized(
            request_bytes, device_id=device_id, session_id=session_id
        )
        await socket.send(
            json.dumps(
                {
                    "kind": "connector.read_result",
                    "version": 1,
                    "sequence": envelope["sequence"],
                    "result": response,
                },
                separators=(",", ":"),
            )
        )
        raw_ack = await socket.recv()
        if not isinstance(raw_ack, str):
            raise CloudHandshakeDeniedError(_HANDSHAKE_DENIED)
        ack = _read_strict_json(raw_ack, "connector.read_ack")
        if (
            set(ack) != {"kind", "version", "sequence", "requestId"}
            or type(ack["version"]) is not int
            or ack["version"] != 1
            or type(ack["sequence"]) is not int
            or ack["sequence"] != envelope["sequence"]
            or ack["requestId"] != response["requestId"]
        ):
            raise CloudHandshakeDeniedError(_HANDSHAKE_DENIED)
        return receipt
    finally:
        dispatcher.close()


def _require_independent_read_authority() -> None:
    """Deny read-capable transport until a separate owner verifier is accepted.

    This transport is also callable without the guarded cloud_once CLI. An
    owner key and caller-supplied dispatcher never prove a human approved a
    read. Only isolated protocol fixtures may replace this fail-closed gate.
    """
    raise CloudHandshakeDeniedError(_HANDSHAKE_DENIED)


def _check_read_transport_gate(
    dispatcher_factory: Callable[[HandshakeReceipt], LocalReadDispatch] | None,
    operator_presence_pilot: bool,
) -> None:
    """Keep the independent-owner gate on all non-pilot read entrypoints."""
    if dispatcher_factory is not None and not operator_presence_pilot:
        _require_independent_read_authority()


async def _perform_outbound_session(
    *,
    origin: str,
    trusted_origin: str,
    owner_sub: str,
    device_id: str,
    signing_key: Ed25519PrivateKey,
    tls_context: ssl.SSLContext | None = None,
    dispatcher_factory: Callable[[HandshakeReceipt], LocalReadDispatch] | None = None,
    operator_presence_pilot: bool = False,
    operator_native_drc_pilot: bool = False,
) -> HandshakeReceipt:
    """Perform the Cloud v1 proof order; optionally handle one approved read.

    Origin and credentials MUST come from independently trusted operator setup
    (not Cloud messages). A custom TLS context is for controlled enterprise
    trust roots or isolated tests; disabling certificate/hostname verification
    is forbidden. No on-disk key management or actual KiCad project reads.
    """
    # Reject both direct public read calls and private session-helper calls
    # before TLS setup or a WebSocket. Proof-only sessions stay available.
    _check_read_transport_gate(dispatcher_factory, operator_presence_pilot)
    endpoint = _endpoint(origin=origin, trusted_origin=trusted_origin)
    if (
        not isinstance(owner_sub, str)
        or not (1 <= len(owner_sub) <= 256)
        or owner_sub != owner_sub.strip()
        or not isinstance(device_id, str)
        or _DEVICE_UUID.fullmatch(device_id) is None
        or not isinstance(signing_key, Ed25519PrivateKey)
    ):
        raise CloudHandshakeDeniedError(_HANDSHAKE_DENIED)
    context = tls_context if tls_context is not None else ssl.create_default_context()
    if (
        not isinstance(context, ssl.SSLContext)
        or context.verify_mode != ssl.CERT_REQUIRED
        or not context.check_hostname
    ):
        raise CloudHandshakeDeniedError(_HANDSHAKE_DENIED)

    def now_ms() -> int:
        return int(datetime.now(UTC).timestamp() * 1000)

    try:
        async with (
            asyncio.timeout(HANDSHAKE_TIMEOUT_SECONDS if dispatcher_factory is None else 40),
            connect(
                endpoint,
                ssl=context,
                origin=None,
                compression=None,
                max_size=1024,
                max_queue=2,
                open_timeout=3,
                close_timeout=2,
            ) as socket,
        ):
            if socket.transport.get_extra_info("ssl_object") is None:
                raise CloudHandshakeDeniedError(_HANDSHAKE_DENIED)
            await socket.send(
                json.dumps(
                    {
                        "kind": "device.hello",
                        "version": 1,
                        "ownerSub": owner_sub,
                        "deviceId": device_id,
                    },
                    separators=(",", ":"),
                )
            )
            challenge = await socket.recv()
            if not isinstance(challenge, str):
                raise CloudHandshakeDeniedError(_HANDSHAKE_DENIED)
            proof = sign_device_challenge(
                challenge.encode(),
                expected_device_id=device_id,
                now_unix_ms=now_ms(),
                signing_key=signing_key,
            )
            await socket.send(json.dumps(proof, separators=(",", ":")))
            session = await socket.recv()
            if not isinstance(session, str):
                raise CloudHandshakeDeniedError(_HANDSHAKE_DENIED)
            signed = sign_session_challenge(
                session.encode(),
                expected_device_id=device_id,
                now_unix_ms=now_ms(),
                signing_key=signing_key,
            )
            accepted_session = _read_strict_json(session, "connector.session_challenge")
            session_id = accepted_session["sessionId"]
            if not isinstance(session_id, str):
                raise CloudHandshakeDeniedError(_HANDSHAKE_DENIED)
            await socket.send(json.dumps(signed, separators=(",", ":")))
            raw_ready = await socket.recv()
            if not isinstance(raw_ready, str):
                raise CloudHandshakeDeniedError(_HANDSHAKE_DENIED)
            ready = _read_strict_json(raw_ready, "connector.ready")
            if (
                set(ready) != {"kind", "version"}
                or type(ready["version"]) is not int
                or ready["version"] != 1
            ):
                raise CloudHandshakeDeniedError(_HANDSHAKE_DENIED)
            receipt = HandshakeReceipt(device_id=device_id, session_id=session_id)
            return await _complete_authorized_read(
                socket,
                receipt,
                dispatcher_factory,
                operator_presence_pilot=operator_presence_pilot,
                operator_native_drc_pilot=operator_native_drc_pilot,
            )
    except (OSError, ValueError, WebSocketException) as exc:
        raise CloudHandshakeDeniedError(_HANDSHAKE_DENIED) from exc


async def establish_proof_only_handshake(
    *,
    origin: str,
    trusted_origin: str,
    owner_sub: str,
    device_id: str,
    signing_key: Ed25519PrivateKey,
    tls_context: ssl.SSLContext | None = None,
) -> HandshakeReceipt:
    """Perform the device proof and close without accepting any commands."""
    return await _perform_outbound_session(
        origin=origin,
        trusted_origin=trusted_origin,
        owner_sub=owner_sub,
        device_id=device_id,
        signing_key=signing_key,
        tls_context=tls_context,
    )


async def execute_operator_presence_once(
    *,
    origin: str,
    trusted_origin: str,
    owner_sub: str,
    device_id: str,
    signing_key: Ed25519PrivateKey,
    dispatcher_factory: Callable[[HandshakeReceipt], LocalReadDispatch],
    tls_context: ssl.SSLContext | None = None,
) -> HandshakeReceipt:
    """Manual lower-assurance presence pilot; no independent owner UV claim.

    The caller must obtain a fresh foreground operator decision. The
    LocalReadDispatch only admits project_summary presence booleans and
    cannot route native KiCad operations or return project contents.
    """
    if not callable(dispatcher_factory):
        raise CloudHandshakeDeniedError(_HANDSHAKE_DENIED)
    return await _perform_outbound_session(
        origin=origin,
        trusted_origin=trusted_origin,
        owner_sub=owner_sub,
        device_id=device_id,
        signing_key=signing_key,
        tls_context=tls_context,
        dispatcher_factory=dispatcher_factory,
        operator_presence_pilot=True,
    )


async def execute_operator_native_drc_once(
    *,
    origin: str,
    trusted_origin: str,
    owner_sub: str,
    device_id: str,
    signing_key: Ed25519PrivateKey,
    dispatcher_factory: Callable[[HandshakeReceipt], LocalReadDispatch],
    tls_context: ssl.SSLContext | None = None,
) -> HandshakeReceipt:
    """Explicit lower-assurance foreground DRC-count pilot only.

    Not a native public/unattended command authority. It requires the
    separate remote Cloud native DRC opt-in flag and an approved dispatcher.
    """
    if not callable(dispatcher_factory):
        raise CloudHandshakeDeniedError(_HANDSHAKE_DENIED)
    return await _perform_outbound_session(
        origin=origin,
        trusted_origin=trusted_origin,
        owner_sub=owner_sub,
        device_id=device_id,
        signing_key=signing_key,
        tls_context=tls_context,
        dispatcher_factory=dispatcher_factory,
        operator_presence_pilot=True,
        operator_native_drc_pilot=True,
    )


async def execute_single_approved_read(
    *,
    origin: str,
    trusted_origin: str,
    owner_sub: str,
    device_id: str,
    signing_key: Ed25519PrivateKey,
    dispatcher_factory: Callable[[HandshakeReceipt], LocalReadDispatch],
    tls_context: ssl.SSLContext | None = None,
) -> HandshakeReceipt:
    """Opt-in one-shot metadata relay; requires independent local grant authority.

    This API cannot establish OAuth, enroll a device, or grant access by itself.
    No production caller is registered; the Cloud server must independently
    authorize and deliver one read over this wire protocol before activation.
    """
    if not callable(dispatcher_factory):
        raise CloudHandshakeDeniedError(_HANDSHAKE_DENIED)
    return await _perform_outbound_session(
        origin=origin,
        trusted_origin=trusted_origin,
        owner_sub=owner_sub,
        device_id=device_id,
        signing_key=signing_key,
        tls_context=tls_context,
        dispatcher_factory=dispatcher_factory,
    )
