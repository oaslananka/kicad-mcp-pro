"""Restartable first enrollment, scoped to the private device-only registry."""

from __future__ import annotations

import hashlib
import os
import time
from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from kicad_mcp import cloud_pair, cloud_pair_keys, cloud_posix_recovery
from kicad_mcp.cloud_managed_connector import _remove_private_file
from kicad_mcp.cloud_pair_keys import LocalApprovalDeniedError
from kicad_mcp.cloud_windows_enrollment import InitialEnrollmentDeniedError, _approved_redeem

JOURNAL = "initial-enrollment.json"
_DENIED = "Saved initial device enrollment cannot be verified. Existing files were kept."


def _journal(root: Path, origin: str) -> dict[str, str]:
    if not os.path.lexists(root / JOURNAL):
        if cloud_posix_recovery._private_names(root / "keys"):
            raise LocalApprovalDeniedError(_DENIED)
        cloud_pair_keys._write_private_json(
            root, JOURNAL, {"origin": origin, "slot": str(uuid4()), "phase": "waiting"}
        )
    data = cloud_pair_keys._read_private_json(root, JOURNAL)
    if (
        set(data) != {"origin", "slot", "phase"}
        or data["origin"] != origin
        or not isinstance(data["slot"], str)
        or not cloud_pair._UUID.fullmatch(data["slot"])
        or data["phase"] not in ("waiting", "redeem")
    ):
        raise LocalApprovalDeniedError(_DENIED)
    return {name: str(value) for name, value in data.items()}


def _challenge(keyfile: Path, origin: str, fingerprint: str) -> tuple[str, str, str, int]:
    name = keyfile.with_suffix(cloud_pair._CHALLENGE_SUFFIX).name
    data = cloud_pair_keys._read_private_json(keyfile.parent, name)
    challenge, code, secret, expiry = (
        data.get("challenge"),
        data.get("code"),
        data.get("secret"),
        data.get("expiry"),
    )
    if (
        set(data) != {"challenge", "code", "secret", "fingerprint", "expiry", "origin"}
        or data["origin"] != origin
        or data["fingerprint"] != fingerprint
        or not isinstance(challenge, str)
        or not cloud_pair._UUID.fullmatch(challenge)
        or not isinstance(code, str)
        or not cloud_pair._USER_CODE.fullmatch(code)
        or not isinstance(secret, str)
        or not cloud_pair._BASE64URL_32.fullmatch(secret)
        or type(expiry) is not int
        or expiry <= 0
    ):
        raise LocalApprovalDeniedError(_DENIED)
    return challenge, code, secret, expiry


def enroll_initial(
    root: Path, origin: str, alias: str, approval: Callable[[str, str, str], None]
) -> tuple[Path, dict[str, str]]:
    """Caller holds session lock; no implicit project or grant is created."""
    journal = _journal(root, origin)
    folder = root / "keys"
    folder.mkdir(mode=0o700, exist_ok=True)
    keyfile = folder / (journal["slot"] + ".pem")
    challenge_file = keyfile.with_suffix(cloud_pair._CHALLENGE_SUFFIX)
    binding_file = folder / (keyfile.name + cloud_pair_keys._BINDING_SUFFIX)
    names = cloud_posix_recovery._private_names(folder)
    if not names.issubset({keyfile.name, challenge_file.name, binding_file.name}):
        raise LocalApprovalDeniedError(_DENIED)
    if keyfile.name not in names and (names or journal["phase"] != "waiting"):
        raise LocalApprovalDeniedError(_DENIED)
    key = cloud_pair._load_or_create(keyfile)
    pin = hashlib.sha256(
        key.public_key().public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
    ).hexdigest()
    if binding_file.name in names:
        if journal["phase"] != "redeem":
            raise LocalApprovalDeniedError(_DENIED)
        binding = cloud_pair_keys._read_owner_binding(keyfile)
        if (
            binding["origin"] != origin
            or binding["fingerprint"] != pin
            or not binding.get("ownerSub")
        ):
            raise LocalApprovalDeniedError(_DENIED)
    else:
        fresh = challenge_file.name not in names
        if fresh:
            if journal["phase"] != "waiting":
                raise LocalApprovalDeniedError(_DENIED)
            cloud_pair._issue_enrollment(cloud_pair._origin(origin), alias, keyfile, key)
        challenge, code, secret, expiry = _challenge(keyfile, origin, pin)
        try:
            if journal["phase"] == "waiting":
                # After a restart the very same challenge may already have
                # been approved. Only open a browser if it is still pending.
                if expiry > time.time_ns() // 1_000_000:
                    cloud_pair._wait_for_owner_approval(
                        cloud_pair._origin(origin),
                        challenge,
                        secret,
                        key,
                        expiry,
                        lambda: approval(origin + "/devices/pairing", challenge, code),
                        allow_existing_approval=not fresh,
                    )
                journal["phase"] = "redeem"
                cloud_pair_keys._write_private_json(root, JOURNAL, journal)
            device, owner = _approved_redeem(
                cloud_pair._origin(origin),
                key,
                challenge=challenge,
                secret=secret,
                fingerprint=pin,
                resume_initial=True,
            )
        except (InitialEnrollmentDeniedError, cloud_pair.CloudPairingDeniedError):
            # A verified terminal refusal permits a new challenge on the
            # next setup, with the same unused key. No deletion of keys.
            journal["phase"] = "waiting"
            cloud_pair_keys._write_private_json(root, JOURNAL, journal)
            _remove_private_file(folder, challenge_file.name)
            raise
        cloud_pair_keys._save_owner_binding(
            keyfile, origin=origin, device_id=device, fingerprint=pin, owner_sub=owner
        )
        binding = cloud_pair_keys._read_owner_binding(keyfile)
    if cloud_pair_keys._read_private_json(root, JOURNAL) != journal:
        raise LocalApprovalDeniedError(_DENIED)
    if os.path.lexists(challenge_file):
        _challenge(keyfile, origin, pin)
        _remove_private_file(folder, challenge_file.name)
    verified = cloud_posix_recovery.inspect_unbound_device(root, origin)
    if verified != (keyfile, binding):
        raise LocalApprovalDeniedError(_DENIED)
    _remove_private_file(root, JOURNAL)
    return keyfile, binding
