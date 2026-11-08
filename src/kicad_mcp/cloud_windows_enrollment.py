"""Isolated Windows owner-approved device enrollment; not yet a Connector switch.

This module does not expose an AI/stdio command or project access. The Cloud CLI
must remain fail-closed until the Windows project boundary and per-user Connector
are implemented and physically accepted.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
    load_pem_private_key,
)

from kicad_mcp import cloud_pair
from kicad_mcp.cloud_local_registry import _STEM
from kicad_mcp.cloud_windows_binding import inspect_local_binding
from kicad_mcp.cloud_windows_credentials import (
    create_credential,
    delete_credential,
    read_credential,
)
from kicad_mcp.cloud_windows_project_record import inspect_project_reference

_ALIAS = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ._-]{0,63}\Z", re.ASCII)
_DENIED = "Windows device enrollment could not be completed."


class WindowsEnrollmentError(ValueError):
    """No Cloud pairing success may be inferred from a local error."""


class WindowsEnrollmentTimeoutError(WindowsEnrollmentError):
    """Unredeemed owner challenge expired; no remote device was created."""


class WindowsEnrollmentDeniedError(WindowsEnrollmentError):
    """Owner rejected the pending challenge before device redemption."""


class WindowsPartialEnrollmentError(WindowsEnrollmentError):
    """Cloud may already have redeemed; owner must inspect the Devices page."""

    def __init__(self, record_id: str) -> None:
        super().__init__(
            "Cloud device may already be registered, but local binding failed. "
            "Review/revoke the device in your Cloud Devices page. "
            "No Connector or project access was enabled."
        )
        self.record_id = record_id


@dataclass(frozen=True, slots=True)
class WindowsEnrolledDevice:
    """Device proof saved to current-user vault; no Cloud authorization granted."""

    record_id: str
    origin: str
    owner_sub: str
    device_id: str
    fingerprint: str


def _same_key(record_id: str, expected: Ed25519PrivateKey) -> None:
    """Read back the vault identity; reject missing/overwritten key slots."""
    data = read_credential(record_id, "key")
    if not data:
        raise WindowsEnrollmentError(_DENIED)
    actual = load_pem_private_key(data, password=None)
    if not isinstance(actual, Ed25519PrivateKey):
        raise WindowsEnrollmentError(_DENIED)
    want = expected.public_key().public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
    have = actual.public_key().public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
    if want != have:
        raise WindowsEnrollmentError(_DENIED)


def _approved_redeem(
    target: tuple[str, int, str],
    key: Ed25519PrivateKey,
    *,
    challenge: str,
    secret: str,
    fingerprint: str,
) -> tuple[str, str]:
    proof = (
        b"kicad-cloud-pairing-proof-v1\x00"
        + challenge.encode("ascii")
        + b"\x00"
        + secret.encode("ascii")
    )
    signature = base64.urlsafe_b64encode(key.sign(proof)).decode("ascii").rstrip("=")
    result = cloud_pair._post(
        target,
        "/api/v1/pairing/device/redeem",
        {"challengeId": challenge, "deviceCode": secret, "signature": signature},
        200,
    )
    required = {"deviceId", "deviceFingerprint", "enabled", "ownerSub"}
    device_id = result.get("deviceId")
    owner_sub = result.get("ownerSub")
    if (
        not required.issubset(result)
        or not isinstance(device_id, str)
        or cloud_pair._UUID.fullmatch(device_id) is None
        or result["deviceFingerprint"] != fingerprint
        or result["enabled"] is not False
        or not isinstance(owner_sub, str)
        or not 1 <= len(owner_sub) <= 256
        or any(ord(char) < 32 or ord(char) == 127 for char in owner_sub)
    ):
        raise WindowsEnrollmentError(_DENIED)
    return device_id, owner_sub


def _remove_unused_owner_credential(record_id: str, key_blob: bytes) -> None:
    """Delete only the temporary key originally written by this enrollment."""
    try:
        # A same-user racing write must never be deleted as a side effect.
        if read_credential(record_id, "key") == key_blob:
            delete_credential(record_id, "key")
    except (OSError, ValueError):
        # Errors remain fail-closed, with no claim of Cloud access.
        pass


def _validate_windows_device_name(alias: str) -> None:
    if os.name != "nt":
        raise WindowsEnrollmentError("Windows Credential Manager is required.")
    if not isinstance(alias, str) or _ALIAS.fullmatch(alias) is None:
        raise WindowsEnrollmentError("Invalid device display name.")


def enroll_windows_device(
    *,
    origin: str,
    alias: str,
    owner_approval: Callable[[str, str, str], None],
) -> WindowsEnrolledDevice:
    """Require real browser approval, save signing key/binding only to user vault.

    This is an internal, isolated building block. The public CLI keeps Windows
    Cloud setup disabled until registration and per-user Connector acceptance.
    No PEM, challenge secret or Cloud grant is persisted to disk. A previously
    redeemed device is never reported as fully configured if vault binding fails.
    """
    _validate_windows_device_name(alias)
    target = cloud_pair._origin(origin)
    record_id = uuid.uuid4().hex
    key = Ed25519PrivateKey.generate()
    key_blob = key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
    committed = False
    key_saved = False
    redeem_attempted = False
    try:
        create_credential(record_id, "key", key_blob)
        key_saved = True
        _same_key(record_id, key)
        der = key.public_key().public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
        challenge_data = cloud_pair._post(
            target,
            "/api/v1/pairing/device/challenge",
            {"alias": alias, "publicKeyDer": base64.b64encode(der).decode("ascii")},
            201,
        )
        challenge, code, secret, fingerprint, expiry = cloud_pair._challenge(challenge_data, key)
        url = f"{target[2]}/devices/pairing#challenge={challenge}&code={code}"
        if challenge_data.get("verificationUriComplete") not in (None, url):
            raise WindowsEnrollmentError(_DENIED)
        cloud_pair._wait_for_owner_approval(
            target,
            challenge,
            secret,
            key,
            expiry,
            lambda: owner_approval(target[2] + "/devices/pairing", challenge, code),
        )
        # Check the credential again before redeem; do not trust a racing
        # same-user vault write merely because the in-memory key still exists.
        _same_key(record_id, key)
        # Once a one-use redeem was *sent*, the server may have accepted it
        # even if the HTTPS response is lost. Preserve owner key for recovery.
        redeem_attempted = True
        device_id, owner_sub = _approved_redeem(
            target, key, challenge=challenge, secret=secret, fingerprint=fingerprint
        )
        document = {
            "recordId": record_id,
            "origin": target[2],
            "ownerSub": owner_sub,
            "deviceId": device_id,
            "fingerprint": fingerprint,
        }
        create_credential(
            record_id, "binding", json.dumps(document, sort_keys=True).encode("utf-8")
        )
        inspected = inspect_local_binding(
            record_id=record_id,
            expected_origin=target[2],
            expected_owner_sub=owner_sub,
            expected_device_id=device_id,
        )
        if inspected.fingerprint != hashlib.sha256(der).hexdigest():
            raise WindowsEnrollmentError(_DENIED)
        committed = True
        return WindowsEnrolledDevice(
            record_id=record_id,
            origin=target[2],
            owner_sub=owner_sub,
            device_id=device_id,
            fingerprint=fingerprint,
        )
    except cloud_pair.CloudPairingDeniedError as exc:
        if redeem_attempted:
            raise WindowsPartialEnrollmentError(record_id) from exc
        raise WindowsEnrollmentDeniedError(
            "Device pairing was denied in the browser. No device was registered. "
            "Start cloud setup again if you want to retry."
        ) from exc
    except cloud_pair.CloudPairingTimeoutError as exc:
        # The redeem request has not been sent. The finally clause wipes
        # our temporary owner key; no Cloud device/project was registered.
        if redeem_attempted:
            raise WindowsPartialEnrollmentError(record_id) from exc
        raise WindowsEnrollmentTimeoutError(
            "Browser device approval expired; no Connector was started. "
            "Start cloud setup again and approve within five minutes."
        ) from exc
    except (OSError, ValueError, TypeError) as exc:
        if redeem_attempted:
            # Leave the owner key for explicit recovery/revocation: deleting it
            # would leave an unmanageable remotely registered device.
            raise WindowsPartialEnrollmentError(record_id) from exc
        raise WindowsEnrollmentError(_DENIED) from exc
    finally:
        if key_saved and not committed and not redeem_attempted:
            _remove_unused_owner_credential(record_id, key_blob)


class WindowsPartialProjectRegistrationError(WindowsEnrollmentError):
    """Cloud project API may have accepted a request; require owner review."""


@dataclass(frozen=True, slots=True)
class WindowsRegisteredProject:
    """Owner-scoped vault reference; still no local project directory or access."""

    registration_id: str
    record_id: str
    origin: str
    owner_sub: str
    device_id: str
    fingerprint: str
    project_id: str
    filename_stem: str


def register_windows_project(
    device: WindowsEnrolledDevice,
    *,
    alias: str,
    filename_stem: str,
) -> WindowsRegisteredProject:
    """Register read-only project metadata with a signed device; no local path.

    The Cloud may still require owner approval of the device/project. This
    function cannot enable the Connector or grant access to local KiCad files.
    """
    if os.name != "nt":
        raise WindowsEnrollmentError("Windows Credential Manager is required.")
    if (
        not isinstance(device, WindowsEnrolledDevice)
        or not isinstance(alias, str)
        or _ALIAS.fullmatch(alias) is None
        or not isinstance(filename_stem, str)
        or _STEM.fullmatch(filename_stem) is None
        or filename_stem in {".", ".."}
    ):
        raise WindowsEnrollmentError("Invalid local project name.")
    # Selectors are checked against independently stored, owner-approved
    # Credential Manager material, not merely the caller's dataclass.
    verified = inspect_local_binding(
        record_id=device.record_id,
        expected_origin=device.origin,
        expected_owner_sub=device.owner_sub,
        expected_device_id=device.device_id,
    )
    if verified.fingerprint != device.fingerprint:
        raise WindowsEnrollmentError(_DENIED)
    raw = read_credential(device.record_id, "key")
    if not raw:
        raise WindowsEnrollmentError(_DENIED)
    key = load_pem_private_key(raw, password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise WindowsEnrollmentError(_DENIED)
    public = key.public_key().public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
    if hashlib.sha256(public).hexdigest() != verified.fingerprint:
        raise WindowsEnrollmentError(_DENIED)

    target = cloud_pair._origin(device.origin)
    proof = (
        b"kicad-cloud-device-project-v1\x00"
        + device.device_id.encode("ascii")
        + b"\x00"
        + alias.encode("utf-8")
    )
    signature = base64.urlsafe_b64encode(key.sign(proof)).decode("ascii").rstrip("=")
    request_attempted = False
    try:
        request_attempted = True
        result = cloud_pair._post(
            target,
            "/api/v1/pairing/device/project",
            {"deviceId": device.device_id, "alias": alias, "signature": signature},
            200,
        )
        project_id = result.get("projectId")
        if (
            not isinstance(project_id, str)
            or cloud_pair._UUID.fullmatch(project_id) is None
            or result.get("alias") != alias
            or result.get("ownerSub") != device.owner_sub
            # The Cloud API can return true for an owner-enabled project.
            # This flag is *not* a local Connector grant or socket state.
            # Both bool values are valid; other types are rejected.
            or type(result.get("enabled")) is not bool
        ):
            raise WindowsEnrollmentError(_DENIED)
        registration_id = uuid.uuid4().hex
        if registration_id == device.record_id:
            raise WindowsEnrollmentError(_DENIED)
        document = {
            "registrationId": registration_id,
            "recordId": device.record_id,
            "origin": device.origin,
            "ownerSub": device.owner_sub,
            "deviceId": device.device_id,
            "fingerprint": device.fingerprint,
            "projectId": project_id,
            "filenameStem": filename_stem,
        }
        create_credential(
            registration_id, "registration", json.dumps(document, sort_keys=True).encode("utf-8")
        )
        verified_project = inspect_project_reference(
            registration_id=registration_id,
            record_id=device.record_id,
            expected_origin=device.origin,
            expected_owner_sub=device.owner_sub,
            expected_device_id=device.device_id,
            expected_project_id=project_id,
            expected_filename_stem=filename_stem,
        )
        if verified_project.fingerprint != device.fingerprint:
            raise WindowsEnrollmentError(_DENIED)
        return WindowsRegisteredProject(
            registration_id=registration_id,
            record_id=device.record_id,
            origin=device.origin,
            owner_sub=device.owner_sub,
            device_id=device.device_id,
            fingerprint=device.fingerprint,
            project_id=project_id,
            filename_stem=filename_stem,
        )
    except (OSError, ValueError, TypeError) as exc:
        if request_attempted:
            raise WindowsPartialProjectRegistrationError(
                "Cloud project request may have succeeded, but its private "
                "Windows project reference is unverified. Review your Cloud "
                "Devices/projects page before retrying. No local Connector was enabled."
            ) from exc
        raise WindowsEnrollmentError(_DENIED) from exc
