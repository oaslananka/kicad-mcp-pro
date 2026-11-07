"""Owner-private device pairing keys and binding; no remote read or project access.

All files are pinned through POSIX openat/O_NOFOLLOW. This module never
opens a KiCad project, performs remote tool calls or authorizes a device.
"""

from __future__ import annotations

import json
import os
import re
import stat
import uuid
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import load_pem_private_key


class LocalApprovalDeniedError(ValueError):
    """Fail closed, without returning private-key or filesystem details."""


_LOCAL_APPROVAL_DENIED = "local approval denied"

_OWNER_KEY_FILENAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_BINDING_SUFFIX = ".cloud-binding-v1.json"
_DEVICE_ID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
)
_FINGERPRINT_RE = re.compile(r"[0-9a-f]{64}")


def _open_owner_directory(folder: Path) -> int:
    """Open each directory hop without following symlinks (no TOCTOU walk)."""
    # Windows has no equivalent stdlib openat/O_NOFOLLOW directory walk.
    # Do not silently downgrade to a symlink-following path check.
    dir_flag = getattr(os, "O_DIRECTORY", None)
    nofollow_flag = getattr(os, "O_NOFOLLOW", None)
    if os.name != "posix" or type(dir_flag) is not int or type(nofollow_flag) is not int:
        raise LocalApprovalDeniedError(_LOCAL_APPROVAL_DENIED)
    # This is an owner-selected absolute directory, never a path supplied by
    # the Cloud request. Refuse lexical upward navigation before the openat
    # walk, even though O_NOFOLLOW already rejects symlink substitution.
    if not isinstance(folder, Path) or not folder.is_absolute():
        raise LocalApprovalDeniedError(_LOCAL_APPROVAL_DENIED)
    components = folder.parts[1:]
    if (
        not components
        or len(components) > 128
        or any(
            component in {"", ".", ".."} or "\x00" in component or len(os.fsencode(component)) > 255
            for component in components
        )
    ):
        raise LocalApprovalDeniedError(_LOCAL_APPROVAL_DENIED)
    flags = os.O_RDONLY | dir_flag | nofollow_flag
    descriptor = os.open("/", flags)
    try:
        for component in components:
            next_descriptor = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


def _open_owner_private_dir(filename: Path) -> int:
    """Pin an owner-private parent through a no-follow directory-component walk."""
    getuid = getattr(os, "getuid", None)
    if (
        os.name != "posix"
        or not callable(getuid)
        or not isinstance(filename, Path)
        or not filename.is_absolute()
        or _OWNER_KEY_FILENAME.fullmatch(filename.name) is None
        or any(part in {".", ".."} for part in filename.parts[1:])
    ):
        raise LocalApprovalDeniedError(_LOCAL_APPROVAL_DENIED)
    directory_fd: int | None = None
    try:
        directory_fd = _open_owner_directory(filename.parent)
        metadata = os.fstat(directory_fd)
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != getuid()
            or metadata.st_mode & 0o077
        ):
            raise LocalApprovalDeniedError(_LOCAL_APPROVAL_DENIED)
        return directory_fd
    except (OSError, ValueError) as exc:
        if directory_fd is not None:
            os.close(directory_fd)
        raise LocalApprovalDeniedError(_LOCAL_APPROVAL_DENIED) from exc


def _load_owner_key(filename: Path) -> Ed25519PrivateKey:
    """Read owner-only PEM by a pinned private directory FD and no-follow basename."""
    if os.name == "nt":
        if not filename.is_file() or not (1 <= filename.stat().st_size <= 8192):
            raise LocalApprovalDeniedError(_LOCAL_APPROVAL_DENIED)
        try:
            key = load_pem_private_key(filename.read_bytes(), password=None)
            if not isinstance(key, Ed25519PrivateKey):
                raise LocalApprovalDeniedError(_LOCAL_APPROVAL_DENIED)
            return key
        except Exception as exc:
            raise LocalApprovalDeniedError(_LOCAL_APPROVAL_DENIED) from exc
    nofollow = getattr(os, "O_NOFOLLOW", None)
    nonblock = getattr(os, "O_NONBLOCK", None)
    getuid = getattr(os, "getuid", None)
    if (
        os.name != "posix"
        or type(nofollow) is not int
        or type(nonblock) is not int
        or not callable(getuid)
    ):
        raise LocalApprovalDeniedError(_LOCAL_APPROVAL_DENIED)
    directory_fd = _open_owner_private_dir(filename)
    descriptor: int | None = None
    try:
        descriptor = os.open(
            filename.name,
            # A substituted FIFO must not block before fstat rejects it.
            os.O_RDONLY | nofollow | nonblock | getattr(os, "O_CLOEXEC", 0),
            dir_fd=directory_fd,
        )
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != getuid()
            or metadata.st_nlink != 1
            or metadata.st_mode & 0o077
            or not 1 <= metadata.st_size <= 8192
        ):
            raise LocalApprovalDeniedError(_LOCAL_APPROVAL_DENIED)
        key = load_pem_private_key(os.read(descriptor, 8193), password=None)
        if not isinstance(key, Ed25519PrivateKey):
            raise LocalApprovalDeniedError(_LOCAL_APPROVAL_DENIED)
        return key
    except (OSError, ValueError, TypeError) as exc:
        raise LocalApprovalDeniedError(_LOCAL_APPROVAL_DENIED) from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        os.close(directory_fd)


def _validated_binding(value: object) -> dict[str, str]:
    # The same identity contract applies on Windows and POSIX; avoid
    # accepting malformed/ambiguous metadata on either operating system.
    if not isinstance(value, dict) or not {"origin", "deviceId", "fingerprint"}.issubset(value):
        raise LocalApprovalDeniedError(_LOCAL_APPROVAL_DENIED)
    if not all(isinstance(item, str) for item in value.values()):
        raise LocalApprovalDeniedError(_LOCAL_APPROVAL_DENIED)
    if (
        len(value["origin"]) > 256
        or _DEVICE_ID_RE.fullmatch(value["deviceId"]) is None
        or _FINGERPRINT_RE.fullmatch(value["fingerprint"]) is None
    ):
        raise LocalApprovalDeniedError(_LOCAL_APPROVAL_DENIED)
    if "ownerSub" in value and not (1 <= len(value["ownerSub"]) <= 256):
        raise LocalApprovalDeniedError(_LOCAL_APPROVAL_DENIED)
    return value


def _new_binding(
    origin: str, device_id: str, fingerprint: str, owner_sub: str | None
) -> dict[str, str]:
    if (
        not isinstance(origin, str)
        or not origin.startswith("https://")
        or len(origin) > 256
        or _DEVICE_ID_RE.fullmatch(device_id) is None
        or _FINGERPRINT_RE.fullmatch(fingerprint) is None
    ):
        raise LocalApprovalDeniedError(_LOCAL_APPROVAL_DENIED)
    record = {"origin": origin, "deviceId": device_id, "fingerprint": fingerprint}
    if owner_sub is not None:
        if not isinstance(owner_sub, str) or not (1 <= len(owner_sub) <= 256):
            raise LocalApprovalDeniedError(_LOCAL_APPROVAL_DENIED)
        record["ownerSub"] = owner_sub
    return record


def _read_owner_binding(filename: Path) -> dict[str, str]:
    """Read owner-only pairing metadata by a pinned no-follow directory FD."""

    def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
        if len({k for k, _ in pairs}) != len(pairs):
            raise LocalApprovalDeniedError(_LOCAL_APPROVAL_DENIED)
        return dict(pairs)

    if os.name == "nt":
        binding_file = filename.parent / (filename.name + _BINDING_SUFFIX)
        if not binding_file.is_file() or not (1 <= binding_file.stat().st_size <= 512):
            raise LocalApprovalDeniedError(_LOCAL_APPROVAL_DENIED)
        try:
            raw = binding_file.read_bytes()
            value = json.loads(raw, object_pairs_hook=unique)
            return _validated_binding(value)
        except Exception as exc:
            raise LocalApprovalDeniedError(_LOCAL_APPROVAL_DENIED) from exc

    nofollow = getattr(os, "O_NOFOLLOW", None)
    nonblock = getattr(os, "O_NONBLOCK", None)
    getuid = getattr(os, "getuid", None)
    if type(nofollow) is not int or type(nonblock) is not int or not callable(getuid):
        raise LocalApprovalDeniedError(_LOCAL_APPROVAL_DENIED)
    directory_fd = _open_owner_private_dir(filename)
    descriptor: int | None = None
    try:
        descriptor = os.open(
            filename.name + _BINDING_SUFFIX,
            # A substituted FIFO must not block before fstat rejects it.
            os.O_RDONLY | nofollow | nonblock | getattr(os, "O_CLOEXEC", 0),
            dir_fd=directory_fd,
        )
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != getuid()
            or metadata.st_nlink != 1
            or metadata.st_mode & 0o077
            or not 1 <= metadata.st_size <= 512
        ):
            raise LocalApprovalDeniedError(_LOCAL_APPROVAL_DENIED)
        raw = os.read(descriptor, 513)
        value = json.loads(raw, object_pairs_hook=unique)
        return _validated_binding(value)
    except (OSError, ValueError, TypeError) as exc:
        raise LocalApprovalDeniedError(_LOCAL_APPROVAL_DENIED) from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        os.close(directory_fd)


def _save_owner_binding(
    filename: Path,
    *,
    origin: str,
    device_id: str,
    fingerprint: str,
    owner_sub: str | None = None,
) -> None:
    """Pin approved enrollment to one HTTPS origin and device, never overwrite."""
    # The fields are independently validated by the Cloud enrollment response.
    expected = _new_binding(origin, device_id, fingerprint, owner_sub)

    if os.name == "nt":
        binding_file = filename.parent / (filename.name + _BINDING_SUFFIX)
        if binding_file.exists():
            raise LocalApprovalDeniedError(_LOCAL_APPROVAL_DENIED)
        body = json.dumps(expected, separators=(",", ":"), sort_keys=True).encode()
        try:
            with open(binding_file, "xb") as output:
                output.write(body)
                output.flush()
                os.fsync(output.fileno())
            return
        except Exception as exc:
            raise LocalApprovalDeniedError(_LOCAL_APPROVAL_DENIED) from exc

    nofollow = getattr(os, "O_NOFOLLOW", None)
    if type(nofollow) is not int:
        raise LocalApprovalDeniedError(_LOCAL_APPROVAL_DENIED)
    directory_fd = _open_owner_private_dir(filename)
    descriptor: int | None = None
    try:
        # Existing metadata, even with identical contents, cannot represent a
        # new pairing. O_EXCL fails closed instead of reopening by pathname.
        descriptor = os.open(
            filename.name + _BINDING_SUFFIX,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | nofollow | getattr(os, "O_CLOEXEC", 0),
            0o600,
            dir_fd=directory_fd,
        )
        body = json.dumps(expected, separators=(",", ":"), sort_keys=True).encode()
        with os.fdopen(descriptor, "wb", buffering=0) as output:
            descriptor = None
            try:
                if output.write(body) != len(body):
                    raise OSError(_LOCAL_APPROVAL_DENIED)
                os.fsync(output.fileno())
            except BaseException:
                # Invalidate *our open inode*, not a possibly replaced path.
                # An incomplete record is never published as trusted pairing.
                os.ftruncate(output.fileno(), 0)
                raise
    except (OSError, ValueError, TypeError) as exc:
        # Never unlink by name after a failed write: another same-user
        # process could have moved our inode and replaced the path.
        raise LocalApprovalDeniedError(_LOCAL_APPROVAL_DENIED) from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        os.close(directory_fd)


# Owner-private JSON records are shared by enrollment and the outbound
# connector. Keeping their filesystem boundary here avoids importing
# the remote connector from the owner-key and pairing modules.
_MAX_PRIVATE_JSON_BYTES = 2048


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    if len({key for key, _ in pairs}) != len(pairs):
        raise LocalApprovalDeniedError(_LOCAL_APPROVAL_DENIED)
    return dict(pairs)


def _current_uid() -> int:
    if os.name == "nt":
        return 0
    getuid = getattr(os, "getuid", None)
    if not callable(getuid):
        raise LocalApprovalDeniedError(_LOCAL_APPROVAL_DENIED)
    uid = getuid()
    if type(uid) is not int:
        raise LocalApprovalDeniedError(_LOCAL_APPROVAL_DENIED)
    return uid


def _read_private_json(root: Path, name: str) -> dict[str, Any]:
    if os.name == "nt":
        path = root / name
        if not path.is_file() or not (1 <= path.stat().st_size <= _MAX_PRIVATE_JSON_BYTES):
            raise LocalApprovalDeniedError(_LOCAL_APPROVAL_DENIED)
        try:
            raw = path.read_bytes()
            value = json.loads(raw, object_pairs_hook=_unique)
            if not isinstance(value, dict):
                raise LocalApprovalDeniedError(_LOCAL_APPROVAL_DENIED)
            return value
        except Exception as exc:
            raise LocalApprovalDeniedError(_LOCAL_APPROVAL_DENIED) from exc

    folder_fd = _open_owner_private_dir(root / name)
    owner_uid = _current_uid()
    fd = -1
    try:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        fd = os.open(name, flags | getattr(os, "O_CLOEXEC", 0), dir_fd=folder_fd)
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != owner_uid
            or info.st_nlink != 1
            or info.st_mode & 0o077
            or not 1 <= info.st_size <= _MAX_PRIVATE_JSON_BYTES
        ):
            raise LocalApprovalDeniedError(_LOCAL_APPROVAL_DENIED)
        raw = os.read(fd, _MAX_PRIVATE_JSON_BYTES + 1)
        if len(raw) > _MAX_PRIVATE_JSON_BYTES:
            raise LocalApprovalDeniedError(_LOCAL_APPROVAL_DENIED)
        value = json.loads(raw, object_pairs_hook=_unique)
        if not isinstance(value, dict):
            raise LocalApprovalDeniedError(_LOCAL_APPROVAL_DENIED)
        return value
    except (OSError, ValueError, TypeError) as exc:
        raise LocalApprovalDeniedError(_LOCAL_APPROVAL_DENIED) from exc
    finally:
        if fd >= 0:
            os.close(fd)
        os.close(folder_fd)


def _write_private_json(root: Path, name: str, value: dict[str, Any]) -> None:
    if os.name == "nt":
        path = root / name
        temp_name = root / f".{name}.{uuid.uuid4().hex}.tmp"
        payload = json.dumps(value, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
        if not (1 <= len(payload) <= _MAX_PRIVATE_JSON_BYTES):
            raise LocalApprovalDeniedError(_LOCAL_APPROVAL_DENIED)
        try:
            temp_name.write_bytes(payload)
            temp_name.replace(path)
            return
        except Exception as exc:
            if temp_name.exists():
                temp_name.unlink(missing_ok=True)
            raise LocalApprovalDeniedError(_LOCAL_APPROVAL_DENIED) from exc

    folder_fd = _open_owner_private_dir(root / name)
    temp_str = f".{name}.{uuid.uuid4().hex}.tmp"
    fd = -1
    try:
        payload = json.dumps(value, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
        if not 1 <= len(payload) <= _MAX_PRIVATE_JSON_BYTES:
            raise LocalApprovalDeniedError(_LOCAL_APPROVAL_DENIED)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
        fd = os.open(temp_str, flags, 0o600, dir_fd=folder_fd)
        with os.fdopen(fd, "wb", closefd=True) as stream:
            fd = -1
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_str, name, src_dir_fd=folder_fd, dst_dir_fd=folder_fd)
        os.fsync(folder_fd)
    finally:
        if fd >= 0:
            os.close(fd)
        try:
            os.unlink(temp_str, dir_fd=folder_fd)
        except FileNotFoundError:
            pass
        os.close(folder_fd)
