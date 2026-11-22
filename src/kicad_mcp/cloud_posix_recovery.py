"""Explicit owner-approved recovery of a single paired POSIX identity."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Callable
from pathlib import Path

from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from kicad_mcp import cloud_pair, cloud_pair_keys
from kicad_mcp.cloud_local_registry import _UUID
from kicad_mcp.cloud_managed_connector import _ENABLED_FILE, _connector_session_lock
from kicad_mcp.cloud_pair_keys import (
    _BINDING_SUFFIX,
    LocalApprovalDeniedError,
    _open_owner_private_dir,
)

_DENIED = "Existing device keys require registration repair. Run cloud status."


def _private_names(folder: Path) -> set[str]:
    if not os.path.lexists(folder):
        return set()
    fd = _open_owner_private_dir(folder / "registry-check")
    try:
        return set(os.listdir(fd))
    finally:
        os.close(fd)


def inspect_unbound_device(root: Path, origin: str) -> tuple[Path, dict[str, str]] | None:
    """Return a uniquely bound identity, never select by age or filename order."""
    names = _private_names(root / "keys")
    if not names:
        return None
    candidates = [name for name in names if name.endswith(".pem")]
    if len(candidates) != 1:
        raise LocalApprovalDeniedError(_DENIED)
    name = candidates[0]
    keyfile = root / "keys" / name
    if _UUID.fullmatch(keyfile.stem) is None or names != {name, name + _BINDING_SUFFIX}:
        raise LocalApprovalDeniedError(_DENIED)
    binding = cloud_pair_keys._read_owner_binding(keyfile)
    key = cloud_pair_keys._load_owner_key(keyfile)
    public = key.public_key().public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
    if (
        binding["origin"] != origin
        or not binding.get("ownerSub")
        or hashlib.sha256(public).hexdigest() != binding["fingerprint"]
    ):
        raise LocalApprovalDeniedError(_DENIED)
    return keyfile, binding


def recover_unbound_project(
    root: Path,
    origin: str,
    directory: Path,
    stem: str,
    confirm: Callable[[dict[str, str]], bool],
) -> dict[str, str] | None:
    """Only restore a selected project with express consent, never enroll anew."""
    candidate = inspect_unbound_device(root, origin)
    if candidate is None:
        return None
    keyfile, binding = candidate
    with _connector_session_lock(root):
        if _private_names(root / "projects") or os.path.lexists(root / _ENABLED_FILE):
            raise LocalApprovalDeniedError(_DENIED)
        if not confirm(binding.copy()):
            raise LocalApprovalDeniedError("Registration recovery was declined. No changes made.")
        if inspect_unbound_device(root, origin) != candidate:
            raise LocalApprovalDeniedError(_DENIED)
        if _private_names(root / "projects") or os.path.lexists(root / _ENABLED_FILE):
            raise LocalApprovalDeniedError(_DENIED)
        response = cloud_pair.register_device_project(origin, keyfile, stem)
        project_id = response["projectId"]
        if not isinstance(project_id, str) or _UUID.fullmatch(project_id) is None:
            raise LocalApprovalDeniedError(_DENIED)
        if response.get("ownerSub") != binding["ownerSub"] or response.get("alias") != stem:
            raise LocalApprovalDeniedError(_DENIED)
        if inspect_unbound_device(root, origin) != candidate or _private_names(root / "projects"):
            raise LocalApprovalDeniedError(_DENIED)
        record = {
            "ownerSub": binding["ownerSub"],
            "cloudOrigin": origin,
            "deviceId": binding["deviceId"],
            "projectId": project_id,
            "keySlot": keyfile.stem,
            "directory": str(directory),
            "filenameStem": stem,
        }
        projects = root / "projects"
        projects.mkdir(mode=0o700, exist_ok=True)
        cloud_pair_keys._write_private_json(projects, f"{project_id}.json", record)
        return record
