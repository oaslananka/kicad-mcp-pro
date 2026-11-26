"""Current-user Windows-vault public issuer pin for future native writes.

No command, network route or remote-supplied key can provision this trust
anchor. A separately approved local owner action must first persist the
public key in the existing per-user Windows Credential Manager namespace and
independently pin the expected Ed25519 SPKI SHA-256.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
from contextlib import suppress
from importlib.resources import files

from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat, load_pem_public_key

from kicad_mcp.cloud_windows_credentials import (
    create_credential,
    delete_credential,
    read_credential,
)
from kicad_mcp.cloud_write_contract import LocalWriteDeniedError

_RECORD = re.compile(r"[0-9a-f]{32}", re.ASCII)
_HASH = re.compile(r"[0-9a-f]{64}", re.ASCII)
_DENIED = "request denied"


def _issuer_key(pem: bytes) -> Ed25519PublicKey:
    if (
        not isinstance(pem, bytes)
        or not 80 <= len(pem) <= 512
        or not pem.startswith(b"-----BEGIN PUBLIC KEY-----\n")
    ):
        raise LocalWriteDeniedError(_DENIED)
    try:
        key = load_pem_public_key(pem)
    except (OSError, ValueError, TypeError, UnsupportedAlgorithm) as exc:
        raise LocalWriteDeniedError(_DENIED) from exc
    if not isinstance(key, Ed25519PublicKey):
        raise LocalWriteDeniedError(_DENIED)
    if key.public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo) != pem:
        raise LocalWriteDeniedError(_DENIED)
    return key


def _fingerprint(key: Ed25519PublicKey) -> str:
    der = key.public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
    return hashlib.sha256(der).hexdigest()


def trust_owner_windows_write_issuer(
    record_id: str, public_key_pem: bytes, *, expected_spki_sha256: str
) -> None:
    """Persist the owner's independently verified issuer key+pin, create-only.

    An OAuth client, a received WebSocket frame, or a remote API must NEVER
    invoke this function: the interactive local owner command supplies both
    the public PEM and the independently checked fingerprint.
    """
    if (
        os.name != "nt"
        or not isinstance(record_id, str)
        or _RECORD.fullmatch(record_id) is None
        or not isinstance(expected_spki_sha256, str)
        or _HASH.fullmatch(expected_spki_sha256) is None
    ):
        raise LocalWriteDeniedError(_DENIED)
    key = _issuer_key(public_key_pem)
    if not hmac.compare_digest(_fingerprint(key), expected_spki_sha256):
        raise LocalWriteDeniedError(_DENIED)
    try:
        previous_key = read_credential(record_id, "write_issuer")
        previous_pin = read_credential(record_id, "write_issuer_pin")
        pin_bytes = expected_spki_sha256.encode("ascii")
        if previous_key is not None or previous_pin is not None:
            if previous_key == public_key_pem and previous_pin == pin_bytes:
                return  # Idempotent for an already approved identity.
            raise LocalWriteDeniedError(_DENIED)  # No silent issuer replacement.
        create_credential(record_id, "write_issuer", public_key_pem)
        try:
            create_credential(record_id, "write_issuer_pin", pin_bytes)
        except Exception:
            # If pin creation fails the partially provisioned key cannot be
            # used for native writes. Remove only this newly created key.
            with suppress(Exception):
                delete_credential(record_id, "write_issuer")
            raise
    except Exception as exc:
        raise LocalWriteDeniedError(_DENIED) from exc


def load_pinned_windows_write_issuer_key(
    record_id: str, *, expected_spki_sha256: str | None = None
) -> Ed25519PublicKey:
    """Trust only an owner-stored public key matching its verified SPKI pin."""
    if os.name != "nt" or not isinstance(record_id, str) or _RECORD.fullmatch(record_id) is None:
        raise LocalWriteDeniedError(_DENIED)
    try:
        if expected_spki_sha256 is None:
            raw = read_credential(record_id, "write_issuer_pin")
            if not isinstance(raw, bytes) or len(raw) != 64:
                raise LocalWriteDeniedError(_DENIED)
            expected_spki_sha256 = raw.decode("ascii")
        if (
            not isinstance(expected_spki_sha256, str)
            or _HASH.fullmatch(expected_spki_sha256) is None
        ):
            raise LocalWriteDeniedError(_DENIED)
        pem = read_credential(record_id, "write_issuer")
        key = _issuer_key(pem)  # type: ignore[arg-type]
        if not hmac.compare_digest(_fingerprint(key), expected_spki_sha256):
            raise LocalWriteDeniedError(_DENIED)
        return key
    except (OSError, ValueError, TypeError, UnsupportedAlgorithm) as exc:
        raise LocalWriteDeniedError(_DENIED) from exc


# Pin of the verified production Cloud issuer PUBLIC key. Rotating this key
# requires an updated client release, never an untrusted network substitution.
_KICAD_CLOUD_ORIGIN = "https://kicad-mcp-pro.oaslananka.dev"
_KICAD_CLOUD_ISSUER_SHA256 = "f49abb8687a184f842e259744eedcc3ceb80254c91942b7dd485df92ee688b01"


def load_bundled_cloud_issuer(origin: str) -> Ed25519PublicKey:
    """Load the release-pinned official issuer, not a network-supplied key."""
    if origin != _KICAD_CLOUD_ORIGIN:
        raise LocalWriteDeniedError(_DENIED)
    try:
        pem = (files("kicad_mcp") / "data" / "cloud_write_issuer_public.txt").read_bytes()
        key = _issuer_key(pem)
        if not hmac.compare_digest(_fingerprint(key), _KICAD_CLOUD_ISSUER_SHA256):
            raise LocalWriteDeniedError(_DENIED)
        return key
    except (OSError, ValueError, TypeError) as exc:
        raise LocalWriteDeniedError(_DENIED) from exc


def trust_bundled_owner_cloud_issuer(record_id: str, *, origin: str) -> None:
    """One foreground owner action trusts the package-pinned Cloud issuer.

    Pairing itself does not grant an AI client any project access. A later
    explicit owner-granted Edit permission and OAuth WRITE scope are required
    on the Cloud side for every signed write request.
    """
    if origin != _KICAD_CLOUD_ORIGIN:
        raise LocalWriteDeniedError(_DENIED)
    try:
        public_pem = (files("kicad_mcp") / "data" / "cloud_write_issuer_public.txt").read_bytes()
        trust_owner_windows_write_issuer(
            record_id, public_pem, expected_spki_sha256=_KICAD_CLOUD_ISSUER_SHA256
        )
    except (OSError, ValueError, TypeError) as exc:
        raise LocalWriteDeniedError(_DENIED) from exc
