"""One owner-controlled Cloud Connector per interactive Windows logon session.

The OS releases a named mutex on process termination, including crashes;
no PID file, global settings or credentials are written. This is a process
coordination guard, never an authentication or native-write grant.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from contextlib import contextmanager

_MUTEX_NAME = "Local\\KiCadMcpProSignedCloudConnectorV1"
_ALREADY_EXISTS = 183


class CloudConnectorAlreadyRunningError(ValueError):
    """A signed Connector is already active in this Windows login session."""


class CloudConnectorLockUnavailableError(ValueError):
    """Cannot safely guarantee a single active Connector in this session."""


@contextmanager
def owner_connector_instance() -> Iterator[None]:
    """Prevent parallel signed sessions for one Windows desktop login.

    Task Scheduler and an interactive terminal share this session's mutex
    when they run as the same logged-in user. It is not a cross-user ACL.
    """
    if sys.platform != "win32":
        yield
        return

    import ctypes
    from ctypes import wintypes

    try:
        load = getattr(ctypes, "WinDLL", None)
        if load is None:
            raise OSError("Windows kernel DLL unavailable")
        kernel = load("kernel32.dll", use_last_error=True, winmode=0x800)
        kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        kernel.CreateMutexW.restype = wintypes.HANDLE
        kernel.ReleaseMutex.argtypes = [wintypes.HANDLE]
        kernel.ReleaseMutex.restype = wintypes.BOOL
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        handle = kernel.CreateMutexW(None, True, _MUTEX_NAME)
    except (AttributeError, OSError, TypeError, ValueError) as exc:
        raise CloudConnectorLockUnavailableError(
            "Cannot verify that only one Cloud Connector is running."
        ) from exc

    if not handle:
        raise CloudConnectorLockUnavailableError(
            "Cannot verify that only one Cloud Connector is running."
        )
    exists = ctypes.get_last_error() == _ALREADY_EXISTS
    if exists:
        kernel.CloseHandle(handle)
        raise CloudConnectorAlreadyRunningError(
            "Another Cloud Connector is already running in this Windows login. "
            "Stop its foreground terminal with Ctrl+C before starting a new session. "
            "Do not start a second Connector to change native editing permission."
        )

    try:
        yield
    finally:
        # CloseHandle also releases the mutex on process death; explicitly
        # release on normal completion so future owner sessions can start.
        try:
            kernel.ReleaseMutex(handle)
        finally:
            kernel.CloseHandle(handle)
