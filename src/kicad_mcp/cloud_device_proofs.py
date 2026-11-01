"""Offline Ed25519 proof construction for the Cloud v1 device handshake.

This module does not authenticate the Cloud endpoint, enroll a device, save
keys, open a connection, authorize a project or execute a local KiCad action.
Only an independently authenticated future transport may call these helpers.
"""

from __future__ import annotations

import base64
import json
import re
from typing import Literal

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

MAX_CHALLENGE_BYTES = 1024
MAX_CHALLENGE_LIFETIME_MS = 60_000
_CHALLENGE_DENIED = "challenge denied"

_UUID = re.compile(r"[a-f0-9]{8}-[a-f0-9]{4}-[1-8][a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}")
_BASE64URL_32 = re.compile(r"[A-Za-z0-9_-]{43}")
_DEVICE_FIELDS = frozenset({"kind", "version", "challengeId", "deviceId", "nonce", "expiresAtMs"})
_SESSION_FIELDS = _DEVICE_FIELDS | frozenset({"sessionId", "binding"})
_PREFIX_DEVICE = b"kicad-cloud-device-handshake-v1\0"
_PREFIX_SESSION = b"kicad-cloud-bound-session-v1\0"


class OfflineProofDeniedError(ValueError):
    """Generic rejection for a malformed or stale, unauthenticated frame."""


def _unique_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    if len({name for name, _ in pairs}) != len(pairs):
        raise OfflineProofDeniedError(_CHALLENGE_DENIED)
    return dict(pairs)


def _reject_constant(_: str) -> None:
    raise OfflineProofDeniedError(_CHALLENGE_DENIED)


def _uuid(value: object) -> bool:
    return isinstance(value, str) and _UUID.fullmatch(value) is not None


def _canonical_32(value: object) -> bool:
    if not isinstance(value, str) or _BASE64URL_32.fullmatch(value) is None:
        return False
    try:
        decoded = base64.urlsafe_b64decode(value + "=")
    except ValueError:
        return False
    return len(decoded) == 32 and base64.urlsafe_b64encode(decoded).decode().rstrip("=") == value


def _decode_challenge(
    raw: bytes,
    *,
    expected_device_id: str,
    now_unix_ms: int,
    kind: Literal["device.challenge", "connector.session_challenge"],
) -> dict[str, object]:
    if (
        not isinstance(raw, bytes)
        or not (1 <= len(raw) <= MAX_CHALLENGE_BYTES)
        or not _uuid(expected_device_id)
        or type(now_unix_ms) is not int
        or now_unix_ms <= 0
    ):
        raise OfflineProofDeniedError(_CHALLENGE_DENIED)
    try:
        parsed = json.loads(
            raw.decode("utf-8"), object_pairs_hook=_unique_keys, parse_constant=_reject_constant
        )
    except (ValueError, TypeError) as exc:
        raise OfflineProofDeniedError(_CHALLENGE_DENIED) from exc
    expected = _DEVICE_FIELDS if kind == "device.challenge" else _SESSION_FIELDS
    if not isinstance(parsed, dict) or set(parsed) != expected:
        raise OfflineProofDeniedError(_CHALLENGE_DENIED)
    expiry = parsed["expiresAtMs"]
    if (
        parsed["kind"] != kind
        or type(parsed["version"]) is not int
        or parsed["version"] != 1
        or parsed["deviceId"] != expected_device_id
        or not _uuid(parsed["challengeId"])
        or not _canonical_32(parsed["nonce"])
        or type(expiry) is not int
        or not (now_unix_ms < expiry <= now_unix_ms + MAX_CHALLENGE_LIFETIME_MS)
    ):
        raise OfflineProofDeniedError(_CHALLENGE_DENIED)
    if kind == "connector.session_challenge" and (
        not _uuid(parsed["sessionId"]) or not _canonical_32(parsed["binding"])
    ):
        raise OfflineProofDeniedError(_CHALLENGE_DENIED)
    return parsed


def _sign(signing_key: Ed25519PrivateKey, payload: bytes) -> str:
    if not isinstance(signing_key, Ed25519PrivateKey):
        raise OfflineProofDeniedError(_CHALLENGE_DENIED)
    signature = signing_key.sign(payload)
    return base64.urlsafe_b64encode(signature).decode("ascii").rstrip("=")


def sign_device_challenge(
    raw: bytes,
    *,
    expected_device_id: str,
    now_unix_ms: int,
    signing_key: Ed25519PrivateKey,
) -> dict[str, object]:
    """Return Cloud v1 device.proof only for a valid, still-current challenge.

    A future caller must independently authenticate the server's TLS identity
    before signing and must enforce challenge-use/reconnect lifecycle.
    """
    challenge = _decode_challenge(
        raw,
        expected_device_id=expected_device_id,
        now_unix_ms=now_unix_ms,
        kind="device.challenge",
    )
    message = (
        _PREFIX_DEVICE
        + str(challenge["challengeId"]).encode()
        + b"\0"
        + expected_device_id.encode()
        + b"\0"
        + str(challenge["nonce"]).encode()
    )
    return {"kind": "device.proof", "version": 1, "signature": _sign(signing_key, message)}


def sign_session_challenge(
    raw: bytes,
    *,
    expected_device_id: str,
    now_unix_ms: int,
    signing_key: Ed25519PrivateKey,
) -> dict[str, object]:
    """Return Cloud v1 connector.session_proof, bound to the socket's challenge.

    This signature is NOT a local authorization to execute a Cloud read.
    """
    challenge = _decode_challenge(
        raw,
        expected_device_id=expected_device_id,
        now_unix_ms=now_unix_ms,
        kind="connector.session_challenge",
    )
    message = (
        _PREFIX_SESSION
        + str(challenge["sessionId"]).encode()
        + b"\0"
        + str(challenge["challengeId"]).encode()
        + b"\0"
        + expected_device_id.encode()
        + b"\0"
        + str(challenge["nonce"]).encode()
        + b"\0"
        + str(challenge["binding"]).encode()
    )
    return {
        "kind": "connector.session_proof",
        "version": 1,
        "signature": _sign(signing_key, message),
    }
