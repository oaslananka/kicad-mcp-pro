"""Offline-only guard around a reviewed KiCad-native transaction.

This intentionally exposes no Connector route, write permission or KiCad
adapter. The trusted caller must bind the operator-approved board to the
active native KiCad project, verify an authenticated one-use proof and use the
existing IPC transaction lifecycle for begin/stage/commit/discard. The lock
serializes only cooperating writers; it does not lock an external KiCad GUI.
"""

from __future__ import annotations

import importlib
import os
import re
import stat
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Protocol, cast

from kicad_mcp.cloud_pair_keys import _open_owner_private_dir
from kicad_mcp.cloud_readonly_boundary import OperatorProject
from kicad_mcp.cloud_write_board_revision import verify_operator_board_revision
from kicad_mcp.cloud_write_contract import LocalWriteDeniedError

_DENIED = "request denied"
_RECOVERY = "native recovery required"
_STEM = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}", re.ASCII)


class NativeWriteRecoveryError(RuntimeError):
    """A native commit or rollback outcome is uncertain: never retry blindly."""


class _FlockModule(Protocol):
    LOCK_EX: int
    LOCK_NB: int

    def flock(self, fd: int, operation: int) -> None: ...


class NativeWriteTransaction(Protocol):
    """Trusted native IPC adapter, not a client-supplied command interpreter.

    begin must return True only if an atomic transaction is held; False means
    no transaction started. stage only changes the unpublished transaction.
    commit returns True only after KiCad native read-back verification.
    discard returns True only after proving pre-transaction restoration.
    """

    def begin(self) -> object: ...

    def stage(self) -> object: ...

    def commit(self) -> bool: ...

    def discard(self) -> bool: ...


def _validate_policy(policy: OperatorProject) -> Path:
    if (
        not isinstance(policy, OperatorProject)
        or not isinstance(policy.directory, Path)
        or not policy.directory.is_absolute()
        or not isinstance(policy.filename_stem, str)
        or _STEM.fullmatch(policy.filename_stem) is None
        or policy.filename_stem in {".", ".."}
    ):
        raise LocalWriteDeniedError(_DENIED)
    return policy.directory / (policy.filename_stem + ".cloud-write.lock")


@contextmanager
def _locked_operator_directory(policy: OperatorProject) -> Iterator[int]:
    """Pin the private folder and hold a nonblocking cross-process POSIX lock."""
    nofollow = getattr(os, "O_NOFOLLOW", None)
    nonblock = getattr(os, "O_NONBLOCK", None)
    getuid = getattr(os, "getuid", None)
    if (
        os.name != "posix"
        or type(nofollow) is not int
        or type(nonblock) is not int
        or not callable(getuid)
    ):
        raise LocalWriteDeniedError(_DENIED)
    path = _validate_policy(policy)
    folder_fd: int | None = None
    lock_fd: int | None = None
    try:
        flock_module = cast(_FlockModule, importlib.import_module("fcntl"))

        folder_fd = _open_owner_private_dir(path)
        lock_fd = os.open(
            path.name,
            os.O_RDWR
            | os.O_CREAT
            | nofollow
            | nonblock
            | getattr(os, "O_NOCTTY", 0)
            | getattr(os, "O_CLOEXEC", 0),
            0o600,
            dir_fd=folder_fd,
        )
        info = os.fstat(lock_fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != getuid()
            or info.st_nlink != 1
            or info.st_mode & 0o077
            or info.st_size != 0
        ):
            raise LocalWriteDeniedError(_DENIED)
        flock_module.flock(lock_fd, flock_module.LOCK_EX | flock_module.LOCK_NB)
    except (OSError, ImportError, ValueError) as exc:
        if lock_fd is not None:
            os.close(lock_fd)
        if folder_fd is not None:
            os.close(folder_fd)
        raise LocalWriteDeniedError(_DENIED) from exc

    try:
        # An open fd pins a directory even if its pathname is renamed later.
        # Check the current name still denotes that very directory before
        # invoking the trusted native adapter.
        if folder_fd is None:
            raise LocalWriteDeniedError(_DENIED)
        yield folder_fd
    finally:
        if lock_fd is not None:
            os.close(lock_fd)
        if folder_fd is not None:
            os.close(folder_fd)


def _assert_same_operator_directory(policy: OperatorProject, folder_fd: int) -> None:
    try:
        pinned = os.fstat(folder_fd)
        current = os.stat(policy.directory, follow_symlinks=False)
        if not stat.S_ISDIR(current.st_mode) or (current.st_dev, current.st_ino) != (
            pinned.st_dev,
            pinned.st_ino,
        ):
            raise LocalWriteDeniedError(_DENIED)
    except (OSError, ValueError, TypeError) as exc:
        raise LocalWriteDeniedError(_DENIED) from exc


def _require_fresh_owner_permission(
    authorized: Callable[[], bool], cancelled: Callable[[], bool]
) -> None:
    try:
        if authorized() is not True or cancelled() is not False:
            raise LocalWriteDeniedError(_DENIED)
    except Exception as exc:
        raise LocalWriteDeniedError(_DENIED) from exc


def run_offline_guarded_native_write(
    policy: OperatorProject,
    expected_board_sha256: str,
    *,
    authorized: Callable[[], bool],
    cancelled: Callable[[], bool],
    native: NativeWriteTransaction,
) -> None:
    """Stage then commit a native transaction under two pinned SHA checks.

    The trusted caller must have already consumed an authenticated one-use
    proof and checked device/session/project/owner consent. The same live
    authorization and cancellation must be checked again before commit.
    Any ambiguous begin/commit or unproven discard requires manual native
    state reconciliation; the request must not be retried automatically.
    """
    if not callable(authorized) or not callable(cancelled):
        raise LocalWriteDeniedError(_DENIED)
    with _locked_operator_directory(policy) as folder_fd:
        _assert_same_operator_directory(policy, folder_fd)
        _require_fresh_owner_permission(authorized, cancelled)
        verify_operator_board_revision(policy, expected_board_sha256, _directory_fd=folder_fd)
        # A throwing begin may have created a native transaction before the
        # acknowledgement was lost. Never guess whether a rollback is safe.
        try:
            began = native.begin()
        except Exception as exc:
            raise NativeWriteRecoveryError(_RECOVERY) from exc
        if began is False:
            raise LocalWriteDeniedError(_DENIED)
        if began is not True:
            raise NativeWriteRecoveryError(_RECOVERY)
        try:
            if native.stage() is not None:
                raise LocalWriteDeniedError(_DENIED)
            _assert_same_operator_directory(policy, folder_fd)
            verify_operator_board_revision(policy, expected_board_sha256, _directory_fd=folder_fd)
            _require_fresh_owner_permission(authorized, cancelled)
        except Exception as exc:
            try:
                restored = native.discard()
            except Exception as rollback_error:
                raise NativeWriteRecoveryError(_RECOVERY) from rollback_error
            if restored is not True:
                raise NativeWriteRecoveryError(_RECOVERY) from exc
            raise LocalWriteDeniedError(_DENIED) from exc
        try:
            if native.commit() is not True:
                raise NativeWriteRecoveryError(_RECOVERY)
        except Exception as exc:
            # Commit may already have been published. Calling discard here
            # could silently hide an ambiguous edit; require reconciliation.
            raise NativeWriteRecoveryError(_RECOVERY) from exc
