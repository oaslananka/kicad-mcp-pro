"""Offline verification of a signed, one-use proposed KiCad write command.

No Cloud transport, issuer key management, grant issuance, replay storage,
filesystem or KiCad execution is wired to this helper. Even a valid signature
is NOT authorization to mutate: a future caller must independently establish
the trusted server signer, live owner/client/project consent, authenticated
connection, atomic durable one-use reservation and current board revision.
"""

from __future__ import annotations

import base64
import json
import re
from collections.abc import Callable
from typing import cast

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from kicad_mcp.cloud_readonly_boundary import OperatorProject, VerifiedLocalBinding
from kicad_mcp.cloud_write_contract import (
    MAX_WRITE_FRAME_BYTES,
    LocalWriteDeniedError,
    parse_local_write_contract,
)

MAX_SIGNED_WRITE_PROOF_BYTES = 2048
_SIGNED_PREFIX = b"kicad-cloud-signed-write-proposal-v1\x00"
_PROOF_FIELDS = frozenset({"kind", "version", "payload", "signature"})
_URLSAFE = re.compile(r"[\w-]+", re.ASCII)
_DENIED = "request denied"


def _unique_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    if len(pairs) != len({key for key, _ in pairs}):
        raise LocalWriteDeniedError(_DENIED)
    return dict(pairs)


def _reject_nonstandard(_: str) -> None:
    raise LocalWriteDeniedError(_DENIED)


def _decode_bounded(value: object, *, max_bytes: int) -> bytes:
    if not isinstance(value, str) or len(value) > (max_bytes * 4 + 2) // 3:
        raise LocalWriteDeniedError(_DENIED)
    if _URLSAFE.fullmatch(value) is None:
        raise LocalWriteDeniedError(_DENIED)
    try:
        decoded = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except ValueError as exc:
        raise LocalWriteDeniedError(_DENIED) from exc
    if (
        not 1 <= len(decoded) <= max_bytes
        or base64.urlsafe_b64encode(decoded).decode("ascii").rstrip("=") != value
    ):
        raise LocalWriteDeniedError(_DENIED)
    return decoded


def verify_offline_signed_write_proof(
    frame: object,
    *,
    trusted_issuer_key: object,
    verified: VerifiedLocalBinding,
    operator_project: OperatorProject,
    now_unix_ms: int,
    consume_once: Callable[[str, str], bool],
) -> dict[str, object]:
    """Verify a detached proof and atomically reserve its (session, request) ID.

    The trusted_issuer_key MUST be pinned independently of the untrusted frame.
    The consume_once callback MUST be durable and atomic across processes/hosts:
    returning True exactly once per session/request even after a crash. Do not
    pass an in-memory set for production. This only validates a proposed command
    and MUST NOT be connected to a native KiCad mutation without live authorization,
    revision verification, cancellation/disconnect and rollback controls.
    """
    if (
        not isinstance(frame, bytes)
        or not 1 <= len(frame) <= MAX_SIGNED_WRITE_PROOF_BYTES
        or not isinstance(trusted_issuer_key, Ed25519PublicKey)
        or not callable(consume_once)
    ):
        raise LocalWriteDeniedError(_DENIED)
    try:
        parsed: object = json.loads(
            frame.decode("utf-8"),
            object_pairs_hook=_unique_pairs,
            parse_constant=_reject_nonstandard,
        )
    except (ValueError, TypeError) as exc:
        raise LocalWriteDeniedError(_DENIED) from exc
    if not isinstance(parsed, dict) or parsed.keys() != _PROOF_FIELDS:
        raise LocalWriteDeniedError(_DENIED)
    proof = cast(dict[str, object], parsed)
    if (
        proof["kind"] != "connector.signed_write_proposal"
        or type(proof["version"]) is not int
        or proof["version"] != 1
    ):
        raise LocalWriteDeniedError(_DENIED)
    payload = _decode_bounded(proof["payload"], max_bytes=MAX_WRITE_FRAME_BYTES)
    signature = _decode_bounded(proof["signature"], max_bytes=64)
    if len(signature) != 64:
        raise LocalWriteDeniedError(_DENIED)
    try:
        trusted_issuer_key.verify(signature, _SIGNED_PREFIX + payload)
    except (InvalidSignature, ValueError, TypeError) as exc:
        raise LocalWriteDeniedError(_DENIED) from exc
    command = parse_local_write_contract(
        payload,
        verified=verified,
        operator_project=operator_project,
        now_unix_ms=now_unix_ms,
    )
    try:
        reserved = consume_once(str(command["sessionId"]), str(command["requestId"]))
    except Exception as exc:
        raise LocalWriteDeniedError(_DENIED) from exc
    if reserved is not True:
        raise LocalWriteDeniedError(_DENIED)
    return command
