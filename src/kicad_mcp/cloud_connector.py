"""Opt-in, outbound-only Cloud proof-of-possession connector bootstrap.

No KiCad engine or project access. No background startup, stateful reconnect,
or remote command execution. Production support requires independent security
and device/host acceptance.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import binascii
import json
import os
import ssl
import stat
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast
from urllib.parse import urlsplit
from uuid import UUID

if TYPE_CHECKING:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

_MAX_FRAME_BYTES = 1024
_WS_ENDPOINT = "/api/v1/connector/ws"


class CloudConnectorError(Exception):
    """Sanitized, user-visible rejection without secrets or signed frames."""


class CloudSocket(Protocol):
    async def recv(self) -> str | bytes: ...

    async def send(self, message: str) -> None: ...


@dataclass(frozen=True, slots=True)
class CloudIdentity:
    owner_sub: str
    device_id: str

    def __post_init__(self) -> None:
        if not self.owner_sub or len(self.owner_sub) > 256:
            raise CloudConnectorError("Invalid owner identity")
        try:
            if str(UUID(self.device_id)) != self.device_id:
                raise ValueError("invalid device")
        except ValueError as exc:
            raise CloudConnectorError("Noncanonical device ID") from exc


def validate_wss_endpoint(uri: str) -> str:
    """Accept only the Cloud connector WSS path with no secrets or URL overrides."""
    try:
        parsed = urlsplit(uri)
        if (
            parsed.scheme != "wss"
            or not parsed.hostname
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path != _WS_ENDPOINT
            or parsed.query
            or parsed.fragment
            or any(char.isspace() for char in uri)
        ):
            raise CloudConnectorError("Cloud connector requires a strict WSS endpoint")
        _ = parsed.port  # reject invalid ports
    except ValueError as exc:
        raise CloudConnectorError("Invalid WSS endpoint") from exc
    return uri


def _uuid(value: object) -> str:
    if not isinstance(value, str):
        raise CloudConnectorError("Invalid challenge identity")
    try:
        if str(UUID(value)) != value:
            raise ValueError("UUID must be canonical")
    except ValueError as exc:
        raise CloudConnectorError("Invalid challenge identity") from exc
    return value


def _b64(value: object, *, size: int) -> str:
    if not isinstance(value, str):
        raise CloudConnectorError("Invalid challenge nonce")
    try:
        raw = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
    except (ValueError, binascii.Error) as exc:
        raise CloudConnectorError("Invalid challenge nonce") from exc
    if len(raw) != size or base64.urlsafe_b64encode(raw).rstrip(b"=").decode() != value:
        raise CloudConnectorError("Invalid challenge nonce")
    return value


def _unique_json_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _json_frame(frame: str | bytes, keys: set[str], kind: str) -> dict[str, object]:
    if not isinstance(frame, str) or len(frame.encode("utf-8")) > _MAX_FRAME_BYTES:
        raise CloudConnectorError("Unexpected Cloud frame format")
    try:
        obj: object = json.loads(frame, object_pairs_hook=_unique_json_pairs)
    except (ValueError, TypeError) as exc:
        raise CloudConnectorError("Malformed Cloud response") from exc
    if not isinstance(obj, dict):
        raise CloudConnectorError("Unexpected Cloud response")
    data = cast(dict[str, object], obj)
    if (
        set(data) != keys
        or data.get("kind") != kind
        or type(data.get("version")) is not int
        or data["version"] != 1
    ):
        raise CloudConnectorError("Unexpected Cloud response")
    return data


def _expiry(value: object, *, max_lifetime: int) -> int:
    if type(value) is not int or value <= 0:
        raise CloudConnectorError("Invalid challenge expiry")
    # Caller checks lifetime using the local clock and also enforces a
    # strict 60-second network timeout. Server state remains authoritative.
    import time

    now = int(time.time() * 1000)
    if value <= now or value > now + max_lifetime * 1000 + 5000:
        raise CloudConnectorError("Cloud challenge is expired or out of range")
    return value


def _signature(signer: Ed25519PrivateKey, payload: bytes) -> str:
    return base64.urlsafe_b64encode(signer.sign(payload)).rstrip(b"=").decode("ascii")


def _first_proof(challenge_id: str, device_id: str, nonce: str) -> bytes:
    return (
        b"kicad-cloud-device-handshake-v1\x00"
        + challenge_id.encode("ascii")
        + b"\x00"
        + device_id.encode("ascii")
        + b"\x00"
        + nonce.encode("ascii")
    )


def _second_proof(
    session_id: str, challenge_id: str, device_id: str, nonce: str, binding: str
) -> bytes:
    return (
        b"kicad-cloud-bound-session-v1\x00"
        + session_id.encode("ascii")
        + b"\x00"
        + challenge_id.encode("ascii")
        + b"\x00"
        + device_id.encode("ascii")
        + b"\x00"
        + nonce.encode("ascii")
        + b"\x00"
        + binding.encode("ascii")
    )


async def perform_handshake(
    socket: CloudSocket, identity: CloudIdentity, signer: Ed25519PrivateKey
) -> None:
    """Perform the two Cloud challenges, then stop sending all application frames."""
    await socket.send(
        json.dumps(
            {
                "kind": "device.hello",
                "version": 1,
                "ownerSub": identity.owner_sub,
                "deviceId": identity.device_id,
            },
            separators=(",", ":"),
        )
    )
    first = _json_frame(
        await asyncio.wait_for(socket.recv(), timeout=15),
        {"kind", "version", "challengeId", "deviceId", "nonce", "expiresAtMs"},
        "device.challenge",
    )
    device_id = _uuid(first["deviceId"])
    if device_id != identity.device_id:
        raise CloudConnectorError("Cloud device identity mismatch")
    challenge_id = _uuid(first["challengeId"])
    nonce = _b64(first["nonce"], size=32)
    _expiry(first["expiresAtMs"], max_lifetime=60)
    await socket.send(
        json.dumps(
            {
                "kind": "device.proof",
                "version": 1,
                "signature": _signature(signer, _first_proof(challenge_id, device_id, nonce)),
            },
            separators=(",", ":"),
        )
    )
    second = _json_frame(
        await asyncio.wait_for(socket.recv(), timeout=15),
        {
            "kind",
            "version",
            "sessionId",
            "challengeId",
            "deviceId",
            "nonce",
            "binding",
            "expiresAtMs",
        },
        "connector.session_challenge",
    )
    if _uuid(second["deviceId"]) != device_id:
        raise CloudConnectorError("Cloud session identity mismatch")
    session_id = _uuid(second["sessionId"])
    next_challenge = _uuid(second["challengeId"])
    next_nonce = _b64(second["nonce"], size=32)
    binding = _b64(second["binding"], size=32)
    _expiry(second["expiresAtMs"], max_lifetime=60)
    await socket.send(
        json.dumps(
            {
                "kind": "connector.session_proof",
                "version": 1,
                "signature": _signature(
                    signer,
                    _second_proof(session_id, next_challenge, device_id, next_nonce, binding),
                ),
            },
            separators=(",", ":"),
        )
    )
    _json_frame(
        await asyncio.wait_for(socket.recv(), timeout=15), {"kind", "version"}, "connector.ready"
    )


def load_private_key(path: Path) -> Ed25519PrivateKey:
    """Load a user-owned POSIX 0600 PEM key; do not create or persist a key."""
    if os.name != "posix":
        raise CloudConnectorError("Secure local key storage is not implemented on this OS")
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import load_pem_private_key

    fd: int | None = None
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            raise CloudConnectorError("Private key must be a user-owned regular file")
        if stat.S_IMODE(info.st_mode) & 0o077:
            raise CloudConnectorError("Private key permissions must be 0600 or tighter")
        with os.fdopen(fd, "rb") as file:
            fd = None
            content = file.read(8193)
        if len(content) > 8192:
            raise CloudConnectorError("Private key file is too large")
        private_key = load_pem_private_key(content, password=None)
        if not isinstance(private_key, Ed25519PrivateKey):
            raise CloudConnectorError("Private key must be Ed25519")
        return private_key
    except (OSError, ValueError, TypeError) as exc:
        raise CloudConnectorError("Unable to load secure Ed25519 key") from exc
    finally:
        if fd is not None:
            os.close(fd)


async def run_once(endpoint: str, identity: CloudIdentity, key: Ed25519PrivateKey) -> None:
    """Explicit one-shot connection; no reconnect and no KiCad tool dispatch."""
    from websockets.asyncio.client import connect

    uri = validate_wss_endpoint(endpoint)
    async with connect(
        uri,
        ssl=ssl.create_default_context(),
        proxy=None,
        compression=None,
        origin=None,
        subprotocols=None,
        additional_headers=None,
        open_timeout=10,
        close_timeout=5,
        ping_interval=20,
        ping_timeout=20,
        max_size=_MAX_FRAME_BYTES,
        max_queue=4,
    ) as socket:
        await perform_handshake(socket, identity, key)
        # The server currently sends no application messages after READY.
        # A five-minute cap is a safety bound, not an automatic renewal.
        try:
            await asyncio.wait_for(socket.wait_closed(), timeout=300)
        except TimeoutError:
            await socket.close(code=1000, reason="session expired")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Explicit opt-in KiCad Cloud outbound authentication (no tools)"
    )
    parser.add_argument("--wss-url", required=True)
    parser.add_argument("--owner-sub", required=True)
    parser.add_argument("--device-id", required=True)
    parser.add_argument("--private-key", required=True, type=Path)
    args = parser.parse_args()
    try:
        identity = CloudIdentity(owner_sub=args.owner_sub, device_id=args.device_id)
        key = load_private_key(args.private_key)
        asyncio.run(run_once(args.wss_url, identity, key))
    except (CloudConnectorError, TimeoutError):
        print("Cloud connector authentication failed or timed out", file=sys.stderr)
        return 2
    except Exception:
        # Never print raw endpoints, private keys or signed frame contents.
        print("Cloud connector connection closed or unavailable", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
