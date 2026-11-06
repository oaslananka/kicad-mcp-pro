"""Inspect a Windows owner's local Cloud key binding without granting access.

This is deliberately NOT an enrollment, authorization, project registration,
revocation, or Connector service. It reads only Windows user-scoped credentials
from the independent vault primitive and does not use filesystem paths.
The caller must already possess the trusted Cloud origin, owner and device
identifiers from an independent human-approved flow. Comparing local values
is never proof that the Cloud currently authorizes this device or project.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
from dataclasses import dataclass

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    PublicFormat,
    load_pem_private_key,
)

from kicad_mcp.cloud_pair import _origin
from kicad_mcp.cloud_pair_keys import LocalApprovalDeniedError
from kicad_mcp.cloud_windows_credentials import _target, read_credential

_DENIED = "local approval denied"
_DEVICE_ID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z",
    re.ASCII,
)
_FINGERPRINT = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_FIELDS = frozenset({"recordId", "origin", "ownerSub", "deviceId", "fingerprint"})


@dataclass(frozen=True, slots=True)
class WindowsLocalBindingInspection:
    """Only locally consistent metadata; NOT authorization to access Cloud."""

    record_id: str
    origin: str
    owner_sub: str
    device_id: str
    fingerprint: str


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    if len({key for key, _ in pairs}) != len(pairs):
        raise LocalApprovalDeniedError(_DENIED)
    return dict(pairs)


def _valid_owner(owner_sub: str) -> bool:
    return (
        isinstance(owner_sub, str)
        and 1 <= len(owner_sub) <= 256
        and all(ord(char) >= 0x20 and ord(char) != 0x7F for char in owner_sub)
    )


def inspect_local_binding(
    *,
    record_id: str,
    expected_origin: str,
    expected_owner_sub: str,
    expected_device_id: str,
) -> WindowsLocalBindingInspection:
    """Fail closed unless both same-user credentials bind to exact selectors.

    Does not generate keys, write credentials, discover projects, start services
    or contact Cloud. No signing key is returned. The untrusted Windows owner
    session can still modify its own vault; proof of approval remains external.
    """
    if os.name != "nt":
        raise LocalApprovalDeniedError(_DENIED)
    try:
        # Reject malformed selectors before reading any credential.
        _target(record_id, "key")
        if (
            not _valid_owner(expected_owner_sub)
            or not isinstance(expected_device_id, str)
            or _DEVICE_ID.fullmatch(expected_device_id) is None
        ):
            raise LocalApprovalDeniedError(_DENIED)
        origin = _origin(expected_origin)[2]
        if origin != expected_origin:
            raise LocalApprovalDeniedError(_DENIED)

        private_bytes = read_credential(record_id, "key")
        binding_bytes = read_credential(record_id, "binding")
        if private_bytes is None or binding_bytes is None:
            raise LocalApprovalDeniedError(_DENIED)

        document = json.loads(binding_bytes, object_pairs_hook=_unique)
        if (
            not isinstance(document, dict)
            or set(document) != _FIELDS
            or not all(isinstance(value, str) for value in document.values())
            or document["recordId"] != record_id
            or document["origin"] != origin
            or document["ownerSub"] != expected_owner_sub
            or document["deviceId"] != expected_device_id
            or _FINGERPRINT.fullmatch(document["fingerprint"]) is None
        ):
            raise LocalApprovalDeniedError(_DENIED)

        key = load_pem_private_key(private_bytes, password=None)
        if not isinstance(key, Ed25519PrivateKey):
            raise LocalApprovalDeniedError(_DENIED)
        public = key.public_key().public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
        fingerprint = hashlib.sha256(public).hexdigest()
        if not hmac.compare_digest(fingerprint, document["fingerprint"]):
            raise LocalApprovalDeniedError(_DENIED)

        return WindowsLocalBindingInspection(
            record_id=record_id,
            origin=origin,
            owner_sub=expected_owner_sub,
            device_id=expected_device_id,
            fingerprint=fingerprint,
        )
    except (OSError, ValueError, TypeError, UnicodeError) as exc:
        raise LocalApprovalDeniedError(_DENIED) from exc
