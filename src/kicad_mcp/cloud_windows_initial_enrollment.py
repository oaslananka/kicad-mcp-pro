"""Restartable initial device-only setup in the current user's Windows vault."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import time
from collections.abc import Callable
from uuid import uuid4

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
    load_pem_private_key,
)

from kicad_mcp import cloud_pair
from kicad_mcp.cloud_pair_keys import _unique
from kicad_mcp.cloud_windows_credentials import (
    create_credential,
    delete_credential,
    read_credential,
)
from kicad_mcp.cloud_windows_device_bootstrap import (
    _DEVICE_SELECTION_SLOT,
    remember_device,
    selected_device,
)
from kicad_mcp.cloud_windows_enrollment import (
    InitialEnrollmentDeniedError,
    WindowsEnrolledDevice,
    WindowsEnrollmentError,
    _approved_redeem,
    _finish_device_binding,
    _same_key,
    _validate_windows_device_name,
)
from kicad_mcp.cloud_windows_write_issuer import _KICAD_CLOUD_ORIGIN

_DENIED = "Saved initial device enrollment cannot be verified. Existing credentials were kept."
_POINTER = "initial_pending"
_CHALLENGE = "initial_challenge"
_APPROVED = "initial_approved"


def _document(raw: bytes) -> dict[str, object]:
    value = json.loads(raw, object_pairs_hook=_unique)
    if not isinstance(value, dict):
        raise WindowsEnrollmentError(_DENIED)
    return value


def _save(slot: str, part: str, data: dict[str, object]) -> bytes:
    blob = json.dumps(data, sort_keys=True).encode()
    create_credential(slot, part, blob)
    if read_credential(slot, part) != blob:
        raise WindowsEnrollmentError(_DENIED)
    return blob


def _remove(slot: str, part: str, expected: bytes) -> None:
    if read_credential(slot, part) != expected or not delete_credential(slot, part):
        raise WindowsEnrollmentError(_DENIED)


def _challenge(raw: bytes, pin: str) -> tuple[str, str, str, int]:
    data = _document(raw)
    challenge, code, secret, expiry = (
        data.get("challenge"),
        data.get("code"),
        data.get("secret"),
        data.get("expiry"),
    )
    if (
        set(data) != {"challenge", "code", "secret", "fingerprint", "expiry"}
        or data["fingerprint"] != pin
        or not isinstance(challenge, str)
        or not cloud_pair._UUID.fullmatch(challenge)
        or not isinstance(code, str)
        or not cloud_pair._USER_CODE.fullmatch(code)
        or not isinstance(secret, str)
        or not cloud_pair._BASE64URL_32.fullmatch(secret)
        or type(expiry) is not int
        or expiry <= 0
    ):
        raise WindowsEnrollmentError(_DENIED)
    return challenge, code, secret, expiry


def _load_key(slot: str, *, may_create: bool) -> Ed25519PrivateKey:
    raw = read_credential(slot, "key")
    if raw is None:
        if not may_create:
            raise WindowsEnrollmentError(_DENIED)
        private = Ed25519PrivateKey.generate()
        raw = private.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
        create_credential(slot, "key", raw)
    loaded = load_pem_private_key(raw, password=None)
    if not isinstance(loaded, Ed25519PrivateKey):
        raise WindowsEnrollmentError(_DENIED)
    _same_key(slot, loaded)
    return loaded


def _issue_challenge(
    slot: str, origin: str, alias: str, private: Ed25519PrivateKey, der: bytes
) -> bytes:
    target = cloud_pair._origin(origin)
    result = cloud_pair._post(
        target,
        "/api/v1/pairing/device/challenge",
        {"alias": alias, "publicKeyDer": base64.b64encode(der).decode("ascii")},
        201,
    )
    challenge, code, secret, fingerprint, expiry = cloud_pair._challenge(result, private)
    url = origin + "/devices/pairing#challenge=" + challenge + "&code=" + code
    if result.get("verificationUriComplete") not in (None, url):
        raise WindowsEnrollmentError(_DENIED)
    challenge_blob = _save(
        slot,
        _CHALLENGE,
        {
            "challenge": challenge,
            "code": code,
            "secret": secret,
            "fingerprint": fingerprint,
            "expiry": expiry,
        },
    )
    return challenge_blob


def _resume_bound_device(
    slot: str, origin: str, pin: str, binding_blob: bytes
) -> WindowsEnrolledDevice:
    data = _document(binding_blob)
    owner, device = data.get("ownerSub"), data.get("deviceId")
    if not isinstance(owner, str) or not isinstance(device, str):
        raise WindowsEnrollmentError(_DENIED)
    return _finish_device_binding(slot, origin, owner, device, pin)


def _finish_pending(
    slot: str,
    origin: str,
    alias: str,
    approval: Callable[[str, str, str], None],
) -> WindowsEnrolledDevice:
    challenge_blob = read_credential(slot, _CHALLENGE)
    approved_blob = read_credential(slot, _APPROVED)
    binding_blob = read_credential(slot, "binding")
    private = _load_key(
        slot, may_create=challenge_blob is None and approved_blob is None and binding_blob is None
    )
    der = private.public_key().public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
    pin = hashlib.sha256(der).hexdigest()
    if binding_blob is not None:
        return _resume_bound_device(slot, origin, pin, binding_blob)
    target = cloud_pair._origin(origin)
    fresh = challenge_blob is None
    if fresh:
        if approved_blob is not None:
            raise WindowsEnrollmentError(_DENIED)
        challenge_blob = _issue_challenge(slot, origin, alias, private, der)
    if challenge_blob is None:
        raise WindowsEnrollmentError(_DENIED)
    challenge, code, secret, expiry = _challenge(challenge_blob, pin)
    marker: dict[str, object] = {"challenge": challenge, "fingerprint": pin}
    try:
        if approved_blob is None:
            if expiry > time.time_ns() // 1_000_000:
                cloud_pair._wait_for_owner_approval(
                    target,
                    challenge,
                    secret,
                    private,
                    expiry,
                    lambda: approval(origin + "/devices/pairing", challenge, code),
                    allow_existing_approval=not fresh,
                )
            approved_blob = _save(slot, _APPROVED, marker)
        elif _document(approved_blob) != marker:
            raise WindowsEnrollmentError(_DENIED)
        _same_key(slot, private)
        device, owner = _approved_redeem(
            target,
            private,
            challenge=challenge,
            secret=secret,
            fingerprint=pin,
            resume_initial=True,
        )
    except (InitialEnrollmentDeniedError, cloud_pair.CloudPairingDeniedError):
        # A definite refusal cannot have registered a device. Keep the key
        # and remove only the exact terminal challenge; next setup can retry.
        if read_credential(slot, "binding") is not None:
            raise WindowsEnrollmentError(_DENIED) from None
        if approved_blob is not None:
            _remove(slot, _APPROVED, approved_blob)
        _remove(slot, _CHALLENGE, challenge_blob)
        raise
    return _finish_device_binding(slot, origin, owner, device, pin)


def _clear_pending_selection(device: WindowsEnrolledDevice, pointer: bytes) -> None:
    slot = device.record_id
    if selected_device() != device or read_credential(_DEVICE_SELECTION_SLOT, _POINTER) != pointer:
        raise WindowsEnrollmentError(_DENIED)
    for part in (_APPROVED, _CHALLENGE):
        raw = read_credential(slot, part)
        if raw is not None:
            _remove(slot, part, raw)
    _remove(_DEVICE_SELECTION_SLOT, _POINTER, pointer)


def _select_pending_device(
    origin: str,
    alias: str,
    approval: Callable[[str, str, str], None],
    selected: WindowsEnrolledDevice | None,
    pointer: bytes,
) -> WindowsEnrolledDevice:
    data = _document(pointer)
    slot = data.get("recordId")
    if (
        set(data) != {"origin", "recordId"}
        or data["origin"] != origin
        or not isinstance(slot, str)
        or not re.fullmatch(r"[0-9a-f]{32}", slot)
        or slot in {"0" * 32, "1" * 32, "2" * 32, "f" * 32}
    ):
        raise WindowsEnrollmentError(_DENIED)
    if selected is not None:
        if selected.record_id != slot or selected.origin != origin:
            raise WindowsEnrollmentError(_DENIED)
        device = selected
    else:
        device = _finish_pending(slot, origin, alias, approval)
        remember_device(device)
    _clear_pending_selection(device, pointer)
    return device


def ensure_device(
    origin: str, alias: str, approval: Callable[[str, str, str], None]
) -> WindowsEnrolledDevice:
    """Caller holds owner connector mutex through selection and cleanup."""
    _validate_windows_device_name(alias)
    if origin != _KICAD_CLOUD_ORIGIN:
        raise WindowsEnrollmentError(_DENIED)
    try:
        selected = selected_device()
        pointer = read_credential(_DEVICE_SELECTION_SLOT, _POINTER)
        if pointer is None:
            if selected is not None:
                if selected.origin != origin:
                    raise WindowsEnrollmentError(_DENIED)
                return selected
            pointer = _save(
                _DEVICE_SELECTION_SLOT, _POINTER, {"origin": origin, "recordId": uuid4().hex}
            )
        return _select_pending_device(origin, alias, approval, selected, pointer)
    except (OSError, ValueError, TypeError) as exc:
        if isinstance(exc, WindowsEnrollmentError):
            raise
        raise WindowsEnrollmentError(
            "Initial device enrollment is incomplete. "
            "Retry the same setup; saved credentials were kept."
        ) from exc
