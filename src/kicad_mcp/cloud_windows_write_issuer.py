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

from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat, load_pem_public_key

from kicad_mcp.cloud_windows_credentials import read_credential
from kicad_mcp.cloud_write_contract import LocalWriteDeniedError

_RECORD = re.compile(r"[0-9a-f]{32}", re.ASCII)
_HASH = re.compile(r"[0-9a-f]{64}", re.ASCII)
_DENIED = "request denied"


def load_pinned_windows_write_issuer_key(
    record_id: str, *, expected_spki_sha256: str
) -> Ed25519PublicKey:
    """Return only an owner-vault public key matching a separately pinned hash."""
    if (
        os.name != "nt"
        or not isinstance(record_id, str)
        or _RECORD.fullmatch(record_id) is None
        or not isinstance(expected_spki_sha256, str)
        or _HASH.fullmatch(expected_spki_sha256) is None
    ):
        raise LocalWriteDeniedError(_DENIED)
    try:
        pem = read_credential(record_id, "write_issuer")
        if (
            not isinstance(pem, bytes)
            or not 80 <= len(pem) <= 512
            or not pem.startswith(b"-----BEGIN PUBLIC KEY-----\n")
        ):
            raise LocalWriteDeniedError(_DENIED)
        key = load_pem_public_key(pem)
        if not isinstance(key, Ed25519PublicKey):
            raise LocalWriteDeniedError(_DENIED)
        der = key.public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
        if not hmac.compare_digest(hashlib.sha256(der).hexdigest(), expected_spki_sha256):
            raise LocalWriteDeniedError(_DENIED)
        return key
    except (OSError, ValueError, TypeError, UnsupportedAlgorithm) as exc:
        raise LocalWriteDeniedError(_DENIED) from exc
