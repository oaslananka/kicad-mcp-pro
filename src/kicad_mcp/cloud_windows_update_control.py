"""Owner-local foreground update coordination, not an authorization grant."""

from __future__ import annotations

import asyncio
import ctypes
import json
import os
import re
import sys
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from typing import cast

from kicad_mcp.cloud_pair_keys import LocalApprovalDeniedError, _unique
from kicad_mcp.cloud_windows_credentials import (
    create_credential,
    delete_credential,
    read_credential,
)
from kicad_mcp.cloud_windows_single_instance import _SESSION_MUTEX_HELD
from kicad_mcp.cloud_windows_write_issuer import _KICAD_CLOUD_ORIGIN

_SLOT = "f" * 32
_GENERATION = re.compile(r"[0-9a-f]{32}")


def _supported() -> bool:
    return sys.platform == "win32"


def _owner_held() -> bool:
    return _SESSION_MUTEX_HELD.get()


def _valid(generation: object, slot: object) -> bool:
    return (
        isinstance(generation, str)
        and _GENERATION.fullmatch(generation) is not None
        and isinstance(slot, str)
        and slot in {"a", "b"}
    )


def _name(generation: str) -> str:
    if not _valid(generation, "a"):
        raise LocalApprovalDeniedError("Invalid update generation.")
    return "Global\\KiCadMcpProUpdate-" + generation


def _kernel() -> ctypes.CDLL:
    from ctypes import wintypes

    loader = getattr(ctypes, "WinDLL", None)
    if not _supported() or not callable(loader):
        raise LocalApprovalDeniedError("Windows update control unavailable.")
    kernel = loader("kernel32.dll", use_last_error=True, winmode=0x800)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.CreateMutexW.restype = wintypes.HANDLE
    kernel.OpenMutexW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.OpenMutexW.restype = wintypes.HANDLE
    kernel.ReleaseMutex.argtypes = [wintypes.HANDLE]
    kernel.ReleaseMutex.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    return cast(ctypes.CDLL, kernel)


@contextmanager
def _generation_mutex(generation: str) -> Iterator[None]:
    from kicad_mcp.cloud_windows_credentials import _last_error

    kernel = _kernel()
    handle = kernel.CreateMutexW(None, True, _name(generation))
    if not handle:
        raise LocalApprovalDeniedError("Windows update control unavailable.")
    try:
        if _last_error() == 183:
            raise LocalApprovalDeniedError("Update generation already exists.")
        try:
            yield
        finally:
            kernel.ReleaseMutex(handle)
    finally:
        kernel.CloseHandle(handle)


def _generation_live(generation: str) -> bool:
    from kicad_mcp.cloud_windows_credentials import _last_error

    kernel = _kernel()
    handle = kernel.OpenMutexW(0x00100000, False, _name(generation))
    if not handle:
        if _last_error() == 2:  # ERROR_FILE_NOT_FOUND, not access denied.
            return False
        raise LocalApprovalDeniedError("Cannot verify the current update lease.")
    kernel.CloseHandle(handle)
    return True


def _read(slot_id: str, part: str) -> tuple[str, str] | None:
    raw = read_credential(slot_id, part)
    if raw is None:
        return None
    data = json.loads(raw, object_pairs_hook=_unique)
    if not isinstance(data, dict) or set(data) != {"generation", "slot"}:
        raise LocalApprovalDeniedError("Invalid update control record.")
    generation, slot = data["generation"], data["slot"]
    if not _valid(generation, slot):
        raise LocalApprovalDeniedError("Invalid update control record.")
    return str(generation), str(slot)


def _payload(generation: str, slot: str) -> bytes:
    return json.dumps({"generation": generation, "slot": slot}, sort_keys=True).encode()


def probe() -> tuple[str, str] | None:
    if not _supported():
        return None
    try:
        lease = _read(_SLOT, "update_lease")
        if (
            lease is not None
            and _generation_live(lease[0])
            and _read(_SLOT, "update_lease") == lease
        ):
            return lease
    except (OSError, ValueError, TypeError):
        pass
    return None


def request(generation: str, slot: str) -> bool:
    if not _valid(generation, slot) or probe() != (generation, slot):
        return False
    try:
        # Generation-specific create-only request; retries are idempotent.
        if read_credential(generation, "update_request") is None:
            create_credential(generation, "update_request", _payload(generation, slot))
            # The foreground can consume and remove this request immediately.
            # The installer independently waits for the session mutex.
            return True
        return _read(generation, "update_request") == (generation, slot)
    except (OSError, ValueError, TypeError):
        return False


def _replace_stale_lease(generation: str, slot: str) -> None:
    old = _read(_SLOT, "update_lease")
    if old is not None:
        if _generation_live(old[0]):
            raise LocalApprovalDeniedError("Another update lease is active.")
        delete_credential(_SLOT, "update_lease")
        if old[0] != generation:
            delete_credential(old[0], "update_request")
    create_credential(_SLOT, "update_lease", _payload(generation, slot))


async def _poll_update_lease(identity: tuple[str, str], drain: asyncio.Event) -> None:
    while not drain.is_set():
        try:
            if (
                _read(_SLOT, "update_lease") != identity
                or _read(identity[0], "update_request") == identity
            ):
                drain.set()
                return
        except (OSError, ValueError, TypeError):
            drain.set()
            return
        try:
            await asyncio.wait_for(drain.wait(), timeout=0.2)
        except TimeoutError:
            pass


@asynccontextmanager
async def watch(origin: str) -> AsyncIterator[asyncio.Event | None]:
    generation = os.environ.get("KICAD_CLOUD_UPDATE_GENERATION", "")
    slot = os.environ.get("KICAD_CLOUD_UPDATE_SLOT", "")
    if not _supported() or origin != _KICAD_CLOUD_ORIGIN or not _valid(generation, slot):
        yield None
        return
    if not _owner_held():
        raise LocalApprovalDeniedError("No local owner Connector holds the session mutex.")
    identity = (generation, slot)
    with _generation_mutex(generation):
        _replace_stale_lease(generation, slot)
        drain = asyncio.Event()
        waiter = asyncio.create_task(_poll_update_lease(identity, drain))
        try:
            if _read(generation, "update_request") == identity:
                drain.set()
            yield drain
        finally:
            waiter.cancel()
            await asyncio.gather(waiter, return_exceptions=True)
            if _read(_SLOT, "update_lease") == identity:
                delete_credential(_SLOT, "update_lease")
            if drain.is_set() and _read(generation, "update_request") == identity:
                delete_credential(generation, "update_request")
            # If no drain was observed, preserve a racing request for a
            # same-generation transition. A fresh launch cannot consume it.
