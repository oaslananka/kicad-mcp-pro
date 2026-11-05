"""Offline-only trusted Cloud write-issuer public key pinning.

Only an out-of-band, operator-approved file and SHA-256 pin can establish
the expected Cloud signing identity. This module neither enrolls devices nor
enables write transport or KiCad mutation.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import stat
from pathlib import Path

from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat, load_pem_public_key

from kicad_mcp.cloud_pair_keys import _open_owner_private_dir
from kicad_mcp.cloud_write_contract import LocalWriteDeniedError

_DENIED = "request denied"
_FINGERPRINT = re.compile(r"[0-9a-f]{64}", re.ASCII)


def load_pinned_write_issuer_key(filename: Path, *, expected_spki_sha256: str) -> Ed25519PublicKey:
    """Load only an independently pinned, owner-controlled Ed25519 public key.

    The filename and expected fingerprint must come from the local operator,
    never from an incoming Cloud payload or Connector response. POSIX no-follow
    directory and file descriptors prevent symlink redirection and file swap
    between path validation and read. There is no Windows fallback.
    """
    nofollow = getattr(os, "O_NOFOLLOW", None)
    nonblock = getattr(os, "O_NONBLOCK", None)
    getuid = getattr(os, "getuid", None)
    if (
        os.name != "posix"
        or type(nofollow) is not int
        or type(nonblock) is not int
        or not callable(getuid)
        or not isinstance(filename, Path)
        or not filename.is_absolute()
        or not isinstance(expected_spki_sha256, str)
        or _FINGERPRINT.fullmatch(expected_spki_sha256) is None
    ):
        raise LocalWriteDeniedError(_DENIED)

    directory_fd: int | None = None
    key_fd: int | None = None
    try:
        directory_fd = _open_owner_private_dir(filename)
        key_fd = os.open(
            filename.name,
            os.O_RDONLY | nofollow | nonblock | getattr(os, "O_CLOEXEC", 0),
            dir_fd=directory_fd,
        )
        info = os.fstat(key_fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != getuid()
            or info.st_nlink != 1
            or info.st_mode & 0o077
            or not 80 <= info.st_size <= 8192
        ):
            raise LocalWriteDeniedError(_DENIED)
        pem = os.read(key_fd, 8193)
        if len(pem) != info.st_size or not pem.startswith(b"-----BEGIN PUBLIC KEY-----\n"):
            raise LocalWriteDeniedError(_DENIED)
        key = load_pem_public_key(pem)
        if not isinstance(key, Ed25519PublicKey):
            raise LocalWriteDeniedError(_DENIED)
        der = key.public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
        fingerprint = hashlib.sha256(der).hexdigest()
        if not hmac.compare_digest(fingerprint, expected_spki_sha256):
            raise LocalWriteDeniedError(_DENIED)
        return key
    except (OSError, ValueError, TypeError, UnsupportedAlgorithm) as exc:
        raise LocalWriteDeniedError(_DENIED) from exc
    finally:
        if key_fd is not None:
            os.close(key_fd)
        if directory_fd is not None:
            os.close(directory_fd)
