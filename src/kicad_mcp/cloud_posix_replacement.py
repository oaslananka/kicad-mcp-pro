"""Stage a browser-approved POSIX replacement without changing active identity."""

from __future__ import annotations

import hashlib
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import uuid4

from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from kicad_mcp import cloud_pair, cloud_pair_keys, cloud_posix_recovery
from kicad_mcp.cloud_pair_keys import LocalApprovalDeniedError
from kicad_mcp.cloud_windows_enrollment import WindowsRecoveryDeniedError, _approved_redeem

Identity = tuple[Path, dict[str, str]]
_PENDING = "replacement-pending"
_REQUEST_FILE = "request.json"
_APPROVED_FILE = "approved.json"
_SWITCH_FILE = "switch.json"
_DENIED = "Saved device replacement could not be verified. Existing registration was kept."


def _directory(path: Path) -> None:
    path.mkdir(mode=0o700, exist_ok=True)
    fd = cloud_pair_keys._open_owner_private_dir(path / "probe")
    os.close(fd)


def _validate_stage(stage: Path, identity: Identity) -> Path:
    old, binding = identity
    _directory(stage)
    journal = stage / _REQUEST_FILE
    if not os.path.lexists(journal):
        if cloud_posix_recovery._private_names(stage):
            raise LocalApprovalDeniedError(_DENIED)
        cloud_pair_keys._write_private_json(
            stage,
            journal.name,
            {
                "previous": old.stem,
                "binding": binding,
                "replacement": str(uuid4()),
            },
        )
    data = cloud_pair_keys._read_private_json(stage, journal.name)
    slot = data.get("replacement")
    if (
        set(data) != {"previous", "binding", "replacement"}
        or data["previous"] != old.stem
        or data["binding"] != binding
        or not isinstance(slot, str)
        or not cloud_pair._UUID.fullmatch(slot)
        or slot == old.stem
    ):
        raise LocalApprovalDeniedError(_DENIED)
    if not cloud_posix_recovery._private_names(stage).issubset(
        {_REQUEST_FILE, _APPROVED_FILE, "keys"}
    ):
        raise LocalApprovalDeniedError(_DENIED)
    _directory(stage / "keys")
    keyfile = stage / "keys" / (slot + ".pem")
    if not cloud_posix_recovery._private_names(keyfile.parent).issubset(
        {
            keyfile.name,
            keyfile.name + cloud_pair_keys._BINDING_SUFFIX,
            keyfile.with_suffix(cloud_pair._CHALLENGE_SUFFIX).name,
        }
    ):
        raise LocalApprovalDeniedError(_DENIED)
    return keyfile


def _approved_challenge(
    stage: Path,
    keyfile: Path,
    origin: str,
    alias: str,
    approval: Callable[[str, str, str], None],
) -> dict[str, Any]:
    approved = stage / _APPROVED_FILE
    challenge_file = keyfile.with_suffix(cloud_pair._CHALLENGE_SUFFIX)
    if os.path.lexists(approved):
        return cloud_pair_keys._read_private_json(stage, approved.name)
    fresh = not os.path.lexists(challenge_file)
    if fresh:
        cloud_pair.start_enrollment(origin, alias, keyfile)
    data = cloud_pair_keys._read_private_json(challenge_file.parent, challenge_file.name)
    if (
        set(data) != {"challenge", "code", "secret", "fingerprint", "expiry", "origin"}
        or data["origin"] != origin
        or not isinstance(data["challenge"], str)
        or not cloud_pair._UUID.fullmatch(data["challenge"])
        or not isinstance(data["code"], str)
        or not cloud_pair._USER_CODE.fullmatch(data["code"])
        or not isinstance(data["secret"], str)
        or not cloud_pair._BASE64URL_32.fullmatch(data["secret"])
        or type(data["expiry"]) is not int
    ):
        raise LocalApprovalDeniedError(_DENIED)
    if data["expiry"] <= time.time_ns() // 1_000_000:
        raise cloud_pair.CloudPairingTimeoutError("Device pairing approval expired.")
    key = cloud_pair_keys._load_owner_key(keyfile)
    pin = hashlib.sha256(
        key.public_key().public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
    ).hexdigest()
    if data["fingerprint"] != pin:
        raise LocalApprovalDeniedError(_DENIED)
    if fresh or not cloud_pair.enrollment_approved(origin, keyfile):
        cloud_pair._wait_for_owner_approval(
            cloud_pair._origin(origin),
            data["challenge"],
            data["secret"],
            key,
            data["expiry"],
            lambda: approval(origin + "/devices/pairing", data["challenge"], data["code"]),
        )
    cloud_pair_keys._write_private_json(stage, approved.name, data)
    return data


def prepare_replacement(
    root: Path,
    identity: Identity,
    alias: str,
    approval: Callable[[str, str, str], None],
) -> Identity:
    """Caller holds session lock. Resume exact approved proof after interruption."""
    _, binding = identity
    if cloud_posix_recovery.inspect_unbound_device(root, binding["origin"]) != identity:
        raise LocalApprovalDeniedError(_DENIED)
    stage = root / _PENDING
    keyfile = _validate_stage(stage, identity)
    data = _approved_challenge(stage, keyfile, binding["origin"], alias, approval)
    key = cloud_pair_keys._load_owner_key(keyfile)
    fingerprint = hashlib.sha256(
        key.public_key().public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
    ).hexdigest()
    if (
        data.get("origin") != binding["origin"]
        or data.get("fingerprint") != fingerprint
        or fingerprint == binding["fingerprint"]
        or not isinstance(data.get("challenge"), str)
        or not cloud_pair._UUID.fullmatch(data["challenge"])
        or not isinstance(data.get("secret"), str)
        or not cloud_pair._BASE64URL_32.fullmatch(data["secret"])
    ):
        raise LocalApprovalDeniedError(_DENIED)
    marker = keyfile.parent / (keyfile.name + cloud_pair_keys._BINDING_SUFFIX)
    if not os.path.lexists(marker):
        device, owner = _approved_redeem(
            cloud_pair._origin(binding["origin"]),
            key,
            challenge=data["challenge"],
            secret=data["secret"],
            fingerprint=fingerprint,
            recovery={"deviceId": binding["deviceId"], "ownerSub": binding["ownerSub"]},
        )
        cloud_pair_keys._save_owner_binding(
            keyfile,
            origin=binding["origin"],
            device_id=device,
            fingerprint=fingerprint,
            owner_sub=owner,
        )
    new = cloud_pair_keys._read_owner_binding(keyfile)
    if (
        new["origin"] != binding["origin"]
        or new.get("ownerSub") != binding["ownerSub"]
        or new["deviceId"] == binding["deviceId"]
        or new["fingerprint"] != fingerprint
    ):
        raise LocalApprovalDeniedError(_DENIED)
    challenge_file = keyfile.with_suffix(cloud_pair._CHALLENGE_SUFFIX)
    if os.path.lexists(challenge_file):
        if cloud_pair_keys._read_private_json(challenge_file.parent, challenge_file.name) != data:
            raise LocalApprovalDeniedError(_DENIED)
        fd = cloud_pair_keys._open_owner_private_dir(challenge_file)
        try:
            os.unlink(challenge_file.name, dir_fd=fd)
            os.fsync(fd)
        finally:
            os.close(fd)
    result = cloud_posix_recovery.inspect_unbound_device(stage, binding["origin"])
    if result != (keyfile, new):
        raise LocalApprovalDeniedError(_DENIED)
    return result


def _move_directory(source: Path, destination: Path) -> None:
    """Move a private directory without overwriting any existing destination."""
    fd = cloud_pair_keys._open_owner_private_dir(source / "probe")
    os.close(fd)
    src = cloud_pair_keys._open_owner_private_dir(source)
    try:
        dst = cloud_pair_keys._open_owner_private_dir(destination)
        try:
            if os.path.lexists(destination):
                raise LocalApprovalDeniedError(_DENIED)
            os.rename(source.name, destination.name, src_dir_fd=src, dst_dir_fd=dst)
            os.fsync(src)
            os.fsync(dst)
        finally:
            os.close(dst)
    finally:
        os.close(src)


def _check_project_location(folder: Path, record: dict[str, str]) -> None:
    name = record["projectId"] + ".json"
    if (
        cloud_posix_recovery._private_names(folder) != {name}
        or cloud_pair_keys._read_private_json(folder, name) != record
    ):
        raise LocalApprovalDeniedError(_DENIED)


def complete_replacement(
    root: Path,
    previous: Identity,
    replacement: Identity,
    project: dict[str, str] | None,
) -> None:
    """Record the exact switch before any active directory is moved."""
    stage = root / _PENDING
    if (
        cloud_posix_recovery.inspect_unbound_device(root, previous[1]["origin"]) != previous
        or cloud_posix_recovery.inspect_unbound_device(stage, previous[1]["origin"]) != replacement
        or os.path.lexists(stage / _SWITCH_FILE)
    ):
        raise LocalApprovalDeniedError(_DENIED)
    cloud_pair_keys._write_private_json(
        stage,
        _SWITCH_FILE,
        {
            "previous": previous[0].stem,
            "oldBinding": previous[1],
            "replacement": replacement[0].stem,
            "newBinding": replacement[1],
            "project": project,
        },
    )
    resume_switch(root, previous[1]["origin"])


def _verify_switch(stage: Path, origin: str) -> dict[str, Any]:
    data = cloud_pair_keys._read_private_json(stage, _SWITCH_FILE)
    if set(data) != {"previous", "oldBinding", "replacement", "newBinding", "project"}:
        raise LocalApprovalDeniedError(_DENIED)
    for name in ("previous", "replacement"):
        if not isinstance(data[name], str) or not cloud_pair._UUID.fullmatch(data[name]):
            raise LocalApprovalDeniedError(_DENIED)
    old, new = (
        cloud_pair_keys._validated_binding(data[field]) for field in ("oldBinding", "newBinding")
    )
    if (
        old["origin"] != origin
        or new["origin"] != origin
        or not old.get("ownerSub")
        or old["ownerSub"] != new.get("ownerSub")
        or old["deviceId"] == new["deviceId"]
        or old["fingerprint"] == new["fingerprint"]
        or data["previous"] == data["replacement"]
    ):
        raise LocalApprovalDeniedError(_DENIED)
    request = cloud_pair_keys._read_private_json(stage, _REQUEST_FILE)
    if request != {
        "previous": data["previous"],
        "binding": old,
        "replacement": data["replacement"],
    }:
        raise LocalApprovalDeniedError(_DENIED)
    project = data["project"]
    if project is not None:
        from kicad_mcp.cloud_registered_pilot import _validated_registration

        if not isinstance(project, dict) or not isinstance(project.get("projectId"), str):
            raise LocalApprovalDeniedError(_DENIED)
        _validated_registration(project, project["projectId"])
        if (
            project["cloudOrigin"] != origin
            or project["ownerSub"] != old["ownerSub"]
            or project["deviceId"] != old["deviceId"]
            or project["keySlot"] != data["previous"]
        ):
            raise LocalApprovalDeniedError(_DENIED)
    return data


def _archive_old_project(root: Path, archive: Path, project: dict[str, str] | None) -> None:
    if project is None:
        if cloud_posix_recovery._private_names(root / "projects") or os.path.lexists(
            archive / "projects"
        ):
            raise LocalApprovalDeniedError(_DENIED)
    elif os.path.lexists(archive / "projects"):
        _check_project_location(archive / "projects", project)
        if os.path.lexists(root / "projects"):
            raise LocalApprovalDeniedError(_DENIED)
    else:
        _check_project_location(root / "projects", project)
        _move_directory(root / "projects", archive / "projects")


def resume_switch(root: Path, origin: str) -> bool:
    """Resume only a recorded switch. Caller holds the owner session lock."""
    from kicad_mcp.cloud_managed_connector import _ENABLED_FILE, _FOREGROUND_FILE

    stage = root / _PENDING
    if not os.path.lexists(stage / _SWITCH_FILE):
        return False
    if os.path.lexists(root / _ENABLED_FILE) or os.path.lexists(root / _FOREGROUND_FILE):
        raise LocalApprovalDeniedError(_DENIED)
    data = _verify_switch(stage, origin)
    archive = stage / "old"
    _directory(archive)
    final = root / ("replaced-" + data["previous"])
    if os.path.lexists(final):
        raise LocalApprovalDeniedError(_DENIED)
    old_location = archive if os.path.lexists(archive / "keys") else root
    new_location = stage if os.path.lexists(stage / "keys") else root
    if old_location == new_location:
        raise LocalApprovalDeniedError(_DENIED)
    for location, slot, binding in (
        (old_location, data["previous"], data["oldBinding"]),
        (new_location, data["replacement"], data["newBinding"]),
    ):
        if cloud_posix_recovery.inspect_unbound_device(location, origin) != (
            location / "keys" / (slot + ".pem"),
            binding,
        ):
            raise LocalApprovalDeniedError(_DENIED)
    _archive_old_project(root, archive, data["project"])
    if old_location == root:
        _move_directory(root / "keys", archive / "keys")
    if new_location == stage:
        _move_directory(stage / "keys", root / "keys")
    if cloud_posix_recovery.inspect_unbound_device(root, origin) != (
        root / "keys" / (data["replacement"] + ".pem"),
        data["newBinding"],
    ):
        raise LocalApprovalDeniedError(_DENIED)
    if cloud_posix_recovery._private_names(root / "projects"):
        raise LocalApprovalDeniedError(_DENIED)
    # Do not retain the pairing code/secret after the new device is selected.
    fd = cloud_pair_keys._open_owner_private_dir(stage / _APPROVED_FILE)
    try:
        if os.path.lexists(stage / _APPROVED_FILE):
            cloud_pair_keys._read_private_json(stage, _APPROVED_FILE)
            os.unlink(_APPROVED_FILE, dir_fd=fd)
            os.fsync(fd)
    finally:
        os.close(fd)
    _move_directory(stage, final)
    return True


def pending_replacement(root: Path) -> bool:
    return os.path.lexists(root / _PENDING)


def recover_device_locked(
    root: Path,
    origin: str,
    alias: str,
    approval: Callable[[str, str, str], None],
) -> bool:
    """Diagnose a failed session or resume a previously approved replacement."""
    from kicad_mcp.cloud_device_inventory_status import inspect_inventory
    from kicad_mcp.cloud_managed_connector import _ENABLED_FILE, _FOREGROUND_FILE
    from kicad_mcp.cloud_once import _load_bound_owner_key
    from kicad_mcp.cloud_posix_device_bootstrap import read_project

    if os.path.lexists(root / _ENABLED_FILE) or os.path.lexists(root / _FOREGROUND_FILE):
        raise LocalApprovalDeniedError(_DENIED)
    if resume_switch(root, origin):
        return True
    identity = cloud_posix_recovery.inspect_unbound_device(root, origin)
    if identity is None:
        return False
    keyfile, binding = identity
    project = read_project(root, identity)
    if not pending_replacement(root):
        key = _load_bound_owner_key(keyfile, origin, binding["deviceId"])
        state = inspect_inventory(
            origin,
            binding["ownerSub"],
            binding["deviceId"],
            project["projectId"] if project else None,
            key,
        )
        if state not in {"unverified", "device_revoked"}:
            return False
    try:
        staged = prepare_replacement(root, identity, alias, approval)
    except (
        WindowsRecoveryDeniedError,
        cloud_pair.CloudPairingDeniedError,
        cloud_pair.CloudPairingTimeoutError,
    ):
        _archive_refused_stage(root, identity)
        raise LocalApprovalDeniedError(
            "Device replacement was not approved. Existing registration kept. "
            "Retry the same setup if needed."
        ) from None
    complete_replacement(root, identity, staged, project)
    return True


def recover_device(
    root: Path,
    origin: str,
    alias: str,
    approval: Callable[[str, str, str], None],
) -> bool:
    from kicad_mcp.cloud_managed_connector import _connector_session_lock

    with _connector_session_lock(root):
        return recover_device_locked(root, origin, alias, approval)


def _archive_refused_stage(root: Path, identity: Identity) -> None:
    """Only a terminal refusal can retire an uncommitted preparation."""
    stage = root / _PENDING
    keyfile = _validate_stage(stage, identity)
    if os.path.lexists(keyfile.parent / (keyfile.name + cloud_pair_keys._BINDING_SUFFIX)):
        raise LocalApprovalDeniedError(_DENIED)
    final = root / ("rejected-" + keyfile.stem)
    if os.path.lexists(final):
        raise LocalApprovalDeniedError(_DENIED)
    for item in (stage / _APPROVED_FILE, keyfile.with_suffix(cloud_pair._CHALLENGE_SUFFIX)):
        if os.path.lexists(item):
            cloud_pair_keys._read_private_json(item.parent, item.name)
            fd = cloud_pair_keys._open_owner_private_dir(item)
            try:
                os.unlink(item.name, dir_fd=fd)
                os.fsync(fd)
            finally:
                os.close(fd)
    _move_directory(stage, final)
