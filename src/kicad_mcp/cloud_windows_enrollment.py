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
from urllib3.exceptions import ProtocolError, ReadTimeoutError

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


class WindowsRecoveryDeniedError(WindowsEnrollmentError):
    """Authenticated Cloud refused replacement; no new device was registered."""


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
    recovery: dict[str, str] | None = None,
) -> tuple[str, str]:
    proof = (
        b"kicad-cloud-pairing-proof-v1\x00"
        + challenge.encode("ascii")
        + b"\x00"
        + secret.encode("ascii")
    )
    if recovery is not None:
        proof = (
            b"kicad-cloud-pairing-recovery-v1\x00"
            + challenge.encode("ascii")
            + b"\x00"
            + secret.encode("ascii")
            + b"\x00"
            + recovery["deviceId"].encode("ascii")
            + b"\x00"
            + recovery["ownerSub"].encode("utf-8")
        )
    signature = base64.urlsafe_b64encode(key.sign(proof)).decode("ascii").rstrip("=")
    payload = {
        "challengeId": challenge,
        "deviceCode": secret,
        "signature": signature,
        "connectOnApproval": True,
        **({"recovery": recovery} if recovery is not None else {}),
    }
    endpoint = "/api/v1/pairing/device/redeem"
    try:
        result = cloud_pair._post(target, endpoint, payload, 200)
    except cloud_pair.CloudPairingError as exc:
        # The recovery contract returns only the original binding for an
        # identical approved request. Retry at most once on a lost response,
        # never for ordinary enrollment, a policy refusal or a TLS error.
        if recovery is None or not isinstance(exc.__cause__, (ProtocolError, ReadTimeoutError)):
            raise
        result = cloud_pair._post(target, endpoint, payload, 200)
    if (
        recovery is not None
        and set(result) == {"recoveryDenied"}
        and result["recoveryDenied"] is True
    ):
        raise WindowsRecoveryDeniedError(
            "Cloud kept the existing device. No replacement was registered. "
            "Check the device is enabled and the correct account is signed in."
        )
    required = {"deviceId", "deviceFingerprint", "enabled", "ownerSub"}
    device_id = result.get("deviceId")
    owner_sub = result.get("ownerSub")
    if (
        not required.issubset(result)
        or not isinstance(device_id, str)
        or cloud_pair._UUID.fullmatch(device_id) is None
        or result["deviceFingerprint"] != fingerprint
        or result["enabled"] is not True
        or (
            recovery is not None
            and (owner_sub != recovery["ownerSub"] or device_id == recovery["deviceId"])
        )
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


def _format_enrollment_denied(exc: Exception) -> WindowsEnrollmentError:
    err_msg = str(exc).strip()
    if err_msg and err_msg != _DENIED:
        return WindowsEnrollmentError(f"{_DENIED} ({err_msg})")
    return WindowsEnrollmentError(_DENIED)


def _finish_device_binding(
    record_id: str, origin: str, owner_sub: str, device_id: str, fingerprint: str
) -> WindowsEnrolledDevice:
    document = {
        "recordId": record_id,
        "origin": origin,
        "ownerSub": owner_sub,
        "deviceId": device_id,
        "fingerprint": fingerprint,
    }
    blob = json.dumps(document, sort_keys=True).encode("utf-8")
    existing = read_credential(record_id, "binding")
    if existing is None:
        create_credential(record_id, "binding", blob)
    elif existing != blob:
        raise WindowsEnrollmentError(_DENIED)
    verified = inspect_local_binding(
        record_id=record_id,
        expected_origin=origin,
        expected_owner_sub=owner_sub,
        expected_device_id=device_id,
    )
    if verified.fingerprint != fingerprint:
        raise WindowsEnrollmentError(_DENIED)
    return WindowsEnrolledDevice(record_id, origin, owner_sub, device_id, fingerprint)


def _pending_recovery(
    old_record: str, target: tuple[str, int, str], recovery: dict[str, str]
) -> WindowsEnrolledDevice | None:
    blob = read_credential(old_record, "recovery_pending")
    if blob is None:
        return None
    raw: bytes | None = None
    try:
        from kicad_mcp.cloud_pair_keys import _unique

        data = json.loads(blob, object_pairs_hook=_unique)
        fields = {
            "recordId",
            "origin",
            "deviceId",
            "ownerSub",
            "challenge",
            "secret",
            "fingerprint",
        }
        if (
            not isinstance(data, dict)
            or set(data) != fields
            or not all(isinstance(value, str) for value in data.values())
            or data["origin"] != target[2]
            or data["deviceId"] != recovery["deviceId"]
            or data["ownerSub"] != recovery["ownerSub"]
            or not re.fullmatch(r"[0-9a-f]{32}", data["recordId"])
            or data["recordId"] == old_record
            or not cloud_pair._UUID.fullmatch(data["challenge"])
            or not re.fullmatch(r"[A-Za-z0-9_-]{43}", data["secret"])
            or not re.fullmatch(r"[0-9a-f]{64}", data["fingerprint"])
        ):
            raise WindowsEnrollmentError(_DENIED)
        raw = read_credential(data["recordId"], "key")
        if raw is None:
            raise WindowsEnrollmentError(_DENIED)
        key = load_pem_private_key(raw, password=None)
        if not isinstance(key, Ed25519PrivateKey):
            raise WindowsEnrollmentError(_DENIED)
        der = key.public_key().public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
        if hashlib.sha256(der).hexdigest() != data["fingerprint"]:
            raise WindowsEnrollmentError(_DENIED)
        if read_credential(old_record, "recovery_pending") != blob:
            raise WindowsEnrollmentError(_DENIED)
        device_id, owner = _approved_redeem(
            target,
            key,
            challenge=data["challenge"],
            secret=data["secret"],
            fingerprint=data["fingerprint"],
            recovery=recovery,
        )
        return _finish_device_binding(
            data["recordId"], target[2], owner, device_id, data["fingerprint"]
        )
    except WindowsRecoveryDeniedError:
        # Exact refusal proves no new binding for this request. Never clear
        # an existing local binding or foreign journal.
        if raw is None or read_credential(data["recordId"], "binding") is not None:
            raise WindowsEnrollmentError(_DENIED) from None
        if read_credential(old_record, "recovery_pending") != blob:
            raise WindowsEnrollmentError(_DENIED) from None
        if not delete_credential(old_record, "recovery_pending"):
            raise WindowsEnrollmentError(_DENIED) from None
        _remove_unused_owner_credential(data["recordId"], raw)
        raise
    except (OSError, ValueError, TypeError) as exc:
        raise WindowsEnrollmentError(
            "Device recovery is incomplete. "
            "Saved recovery information was kept; retry the same setup."
        ) from exc


def enroll_windows_device(
    *,
    origin: str,
    alias: str,
    owner_approval: Callable[[str, str, str], None],
    recovery_device_id: str | None = None,
    recovery_owner_sub: str | None = None,
    recovery_record_id: str | None = None,
) -> WindowsEnrolledDevice:
    """Require real browser approval, save signing key/binding only to user vault.

    This is an internal, isolated building block. The public CLI keeps Windows
    Cloud setup disabled until registration and per-user Connector acceptance.
    No PEM, challenge secret or Cloud grant is persisted to disk. A previously
    redeemed device is never reported as fully configured if vault binding fails.
    """
    _validate_windows_device_name(alias)
    recovery = None
    if recovery_device_id is not None or recovery_owner_sub is not None:
        if (
            not isinstance(recovery_device_id, str)
            or cloud_pair._UUID.fullmatch(recovery_device_id) is None
            or not isinstance(recovery_owner_sub, str)
            or not 1 <= len(recovery_owner_sub) <= 256
            or any(ord(char) < 32 or ord(char) == 127 for char in recovery_owner_sub)
        ):
            raise WindowsEnrollmentError(_DENIED)
        recovery = {"deviceId": recovery_device_id, "ownerSub": recovery_owner_sub}
    target = cloud_pair._origin(origin)
    if recovery_record_id is not None:
        if recovery is None or not re.fullmatch(r"[0-9a-f]{32}", recovery_record_id):
            raise WindowsEnrollmentError(_DENIED)
        resumed = _pending_recovery(recovery_record_id, target, recovery)
        if resumed is not None:
            return resumed
    record_id = uuid.uuid4().hex
    key = Ed25519PrivateKey.generate()
    key_blob = key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
    committed = False
    key_saved = False
    redeem_attempted = False
    journal = None
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
        if recovery_record_id is not None and recovery is not None:
            journal = json.dumps(
                {
                    "recordId": record_id,
                    "origin": target[2],
                    **recovery,
                    "challenge": challenge,
                    "secret": secret,
                    "fingerprint": fingerprint,
                },
                sort_keys=True,
            ).encode()
            # A failed vault call may have persisted the journal; preserve its key.
            redeem_attempted = True
            create_credential(recovery_record_id, "recovery_pending", journal)
            if read_credential(recovery_record_id, "recovery_pending") != journal:
                raise WindowsEnrollmentError(_DENIED)
        redeem_attempted = True
        device_id, owner_sub = _approved_redeem(
            target,
            key,
            challenge=challenge,
            secret=secret,
            fingerprint=fingerprint,
            recovery=recovery,
        )
        result = _finish_device_binding(record_id, target[2], owner_sub, device_id, fingerprint)
        committed = True
        return result
    except WindowsRecoveryDeniedError:
        # Exact authenticated refusal: no remote device was created.
        if recovery_record_id is not None and journal is not None:
            if read_credential(recovery_record_id, "recovery_pending") != journal:
                raise WindowsEnrollmentError(_DENIED) from None
            if not delete_credential(recovery_record_id, "recovery_pending"):
                raise WindowsEnrollmentError(_DENIED) from None
        redeem_attempted = False
        raise
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
        raise _format_enrollment_denied(exc) from exc
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
