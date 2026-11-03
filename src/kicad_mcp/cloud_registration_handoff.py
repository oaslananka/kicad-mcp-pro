"""Explicit, local-only handoff from an old Cloud project to a new paired device.

No remote account access, key generation, silent enrollment or Connector startup.
The owner must copy identity selectors from the authenticated Cloud Devices page,
review the selected existing local project and confirm in an interactive terminal.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import uuid
from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from kicad_mcp.cloud_local_registry import (
    _UUID,
    _valid_identity_selectors,
    default_registry_root,
)
from kicad_mcp.cloud_pair_keys import (
    LocalApprovalDeniedError,
    _load_owner_key,
    _open_owner_private_dir,
    _read_owner_binding,
)
from kicad_mcp.cloud_registered_pilot import _single_registered_identity

_DENIED = "Local registration handoff denied. Check your owner-private Cloud setup."


@dataclass(frozen=True)
class RegistrationHandoff:
    root: Path
    previous: tuple[tuple[str, str], ...]
    new: tuple[tuple[str, str], ...]

    def old(self) -> dict[str, str]:
        return dict(self.previous)

    def updated(self) -> dict[str, str]:
        return dict(self.new)


def _regular_private(file: Path) -> None:
    nofollow = getattr(os, "O_NOFOLLOW", None)
    nonblock = getattr(os, "O_NONBLOCK", None)
    getuid = getattr(os, "getuid", None)
    if type(nofollow) is not int or type(nonblock) is not int or not callable(getuid):
        raise LocalApprovalDeniedError(_DENIED)
    try:
        fd_parent = _open_owner_private_dir(file)
        fd = -1
        try:
            fd = os.open(
                file.name,
                os.O_RDONLY | nofollow | nonblock | getattr(os, "O_CLOEXEC", 0),
                dir_fd=fd_parent,
            )
            info = os.fstat(fd)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != getuid()
                or info.st_nlink != 1
                or info.st_mode & 0o077
            ):
                raise LocalApprovalDeniedError(_DENIED)
        finally:
            if fd >= 0:
                os.close(fd)
            os.close(fd_parent)
    except (OSError, TypeError, ValueError) as exc:
        raise LocalApprovalDeniedError(_DENIED) from exc


def _paired_new_key(root: Path, origin: str, device_id: str) -> str:
    keys = root / "keys"
    folder = _open_owner_private_dir(keys / "placeholder.pem")
    os.close(folder)
    matches: list[str] = []
    for binding in keys.iterdir():
        if not binding.name.endswith(".pem.cloud-binding-v1.json"):
            continue
        slot = binding.name.removesuffix(".pem.cloud-binding-v1.json")
        if _UUID.fullmatch(slot) is None:
            raise LocalApprovalDeniedError(_DENIED)
        key = keys / f"{slot}.pem"
        _regular_private(binding)
        bound = _read_owner_binding(key)
        if bound["origin"] != origin or bound["deviceId"] != device_id:
            continue
        _regular_private(key)
        public = (
            _load_owner_key(key)
            .public_key()
            .public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
        )
        if hashlib.sha256(public).hexdigest() != bound["fingerprint"]:
            raise LocalApprovalDeniedError(_DENIED)
        matches.append(slot)
    if len(matches) != 1:
        raise LocalApprovalDeniedError(_DENIED)
    return matches[0]


def prepare_handoff(
    root: Path, *, owner_sub: str, device_id: str, project_id: str
) -> RegistrationHandoff:
    """Verify current owner-only state and a newly paired key; do not mutate."""
    try:
        if (root / "connector-enabled.json").exists() or (
            root / "connector-enabled.json"
        ).is_symlink():
            raise LocalApprovalDeniedError(_DENIED)
        previous = _single_registered_identity(root)
        origin = previous["cloudOrigin"]
        if not _valid_identity_selectors(owner_sub, origin, device_id, project_id):
            raise LocalApprovalDeniedError(_DENIED)
        if previous["deviceId"] == device_id or previous["projectId"] == project_id:
            raise LocalApprovalDeniedError(_DENIED)
        old_record = root / "projects" / f"{previous['projectId']}.json"
        _regular_private(old_record)
        slot = _paired_new_key(root, origin, device_id)
        if slot == previous["keySlot"]:
            raise LocalApprovalDeniedError(_DENIED)
        new_file = root / "projects" / f"{project_id}.json"
        if new_file.exists() or new_file.is_symlink():
            raise LocalApprovalDeniedError(_DENIED)
        prior_archive = root / "archived-project-registrations" / old_record.name
        if prior_archive.exists() or prior_archive.is_symlink():
            raise LocalApprovalDeniedError(_DENIED)
        updated = {
            "ownerSub": owner_sub,
            "cloudOrigin": origin,
            "deviceId": device_id,
            "projectId": project_id,
            "keySlot": slot,
            # Reuse ONLY the previously vetted owner-selected local path.
            "directory": previous["directory"],
            "filenameStem": previous["filenameStem"],
        }
        return RegistrationHandoff(
            root=root,
            previous=tuple(sorted(previous.items())),
            new=tuple(sorted(updated.items())),
        )
    except (OSError, TypeError, KeyError, ValueError) as exc:
        raise LocalApprovalDeniedError(_DENIED) from exc


def activate_handoff(plan: RegistrationHandoff) -> None:
    """Archive the old registration privately, then install exactly one active record.

    Failure rolls back before returning. This function is for the explicit
    owner-initiated CLI only; callers must prompt for consent and require a TTY.
    """
    newer = plan.updated()
    again = prepare_handoff(
        plan.root,
        owner_sub=newer["ownerSub"],
        device_id=newer["deviceId"],
        project_id=newer["projectId"],
    )
    if again != plan:
        raise LocalApprovalDeniedError(_DENIED)
    root_fd = project_fd = archive_fd = -1
    temp: str | None = None
    archived = linked = False
    old_name = f"{plan.old()['projectId']}.json"
    new_name = f"{newer['projectId']}.json"
    try:
        root_fd = _open_owner_private_dir(plan.root / "projects")
        project_fd = _open_owner_private_dir(plan.root / "projects" / old_name)
        try:
            os.mkdir("archived-project-registrations", 0o700, dir_fd=root_fd)
        except FileExistsError:
            pass
        archive_fd = _open_owner_private_dir(
            plan.root / "archived-project-registrations" / old_name
        )
        if os.path.lexists(plan.root / "archived-project-registrations" / old_name):
            raise LocalApprovalDeniedError(_DENIED)
        # The temporary record is created in the target directory itself,
        # O_EXCL + nofollow; never overwrite an existing project record.
        nofollow = getattr(os, "O_NOFOLLOW", None)
        if type(nofollow) is not int:
            raise LocalApprovalDeniedError(_DENIED)
        temp = ".registration-" + uuid.uuid4().hex + ".tmp"
        payload = json.dumps(newer, separators=(",", ":"), sort_keys=True).encode()
        if not 1 <= len(payload) <= 2048:
            raise LocalApprovalDeniedError(_DENIED)
        fd = os.open(
            temp,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | nofollow,
            0o600,
            dir_fd=project_fd,
        )
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.rename(old_name, old_name, src_dir_fd=project_fd, dst_dir_fd=archive_fd)
        archived = True
        os.link(
            temp,
            new_name,
            src_dir_fd=project_fd,
            dst_dir_fd=project_fd,
            follow_symlinks=False,
        )
        linked = True
        os.unlink(temp, dir_fd=project_fd)
        temp = None
        if _single_registered_identity(plan.root) != newer:
            raise LocalApprovalDeniedError(_DENIED)
        os.fsync(project_fd)
        os.fsync(archive_fd)
    except (OSError, TypeError, ValueError) as exc:
        if linked:
            os.unlink(new_name, dir_fd=project_fd)
        if archived:
            os.rename(old_name, old_name, src_dir_fd=archive_fd, dst_dir_fd=project_fd)
        raise LocalApprovalDeniedError(_DENIED) from exc
    finally:
        if temp is not None and project_fd >= 0:
            try:
                os.unlink(temp, dir_fd=project_fd)
            except FileNotFoundError:
                pass
        for fd in (archive_fd, project_fd, root_fd):
            if fd >= 0:
                os.close(fd)


__all__ = ["RegistrationHandoff", "prepare_handoff", "activate_handoff", "default_registry_root"]
