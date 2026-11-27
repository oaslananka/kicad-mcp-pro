"""Owner-private rendezvous for a foreground installer-managed POSIX session.

Only a matching generation can request a graceful drain. The session lock
must already be held by the caller of watch; no PID or signal is trusted.
This control never changes pairing, project selection or Cloud grants.
"""

from __future__ import annotations

import asyncio
import os
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from kicad_mcp.cloud_pair_keys import (
    LocalApprovalDeniedError,
    _read_private_json,
    _write_private_json,
)
from kicad_mcp.cloud_windows_write_issuer import _KICAD_CLOUD_ORIGIN

LEASE = "update-lease.json"
REQUEST = "update-request.json"
LOCK = "update-control.lock"
_GENERATION = re.compile(r"[0-9a-f]{32}")
_SLOTS = frozenset({"a", "b"})


def _valid(generation: object, slot: object) -> bool:
    return (
        isinstance(generation, str)
        and _GENERATION.fullmatch(generation) is not None
        and isinstance(slot, str)
        and slot in _SLOTS
    )


def _read(root: Path, name: str) -> tuple[str, str] | None:
    try:
        data = _read_private_json(root, name)
        generation, slot = data.get("generation"), data.get("slot")
        if set(data) == {"generation", "slot"} and _valid(generation, slot):
            return str(generation), str(slot)
    except (OSError, ValueError):
        pass
    return None


def probe(root: Path) -> tuple[str, str] | None:
    """Return a local generation only while the session lock is occupied."""
    from kicad_mcp.cloud_managed_connector import _session_lock_held

    if os.name != "posix":
        return None
    lease = _read(root, LEASE)
    if (
        lease is None
        or not _session_lock_held(root, name=LOCK)
        or not _session_lock_held(root)
        or _read(root, LEASE) != lease
    ):
        return None
    return lease


def request(root: Path, generation: str, slot: str) -> bool:
    """A stale request cannot match the next process's random generation."""
    if not _valid(generation, slot) or probe(root) != (generation, slot):
        return False
    try:
        _write_private_json(root, REQUEST, {"generation": generation, "slot": slot})
        # The owner may already have consumed the request and closed its
        # control lease. The installer must still acquire its session lock.
        return _read(root, REQUEST) == (generation, slot)
    except (OSError, ValueError):
        return False


@asynccontextmanager
async def watch(root: Path, origin: str) -> AsyncIterator[asyncio.Event | None]:
    """Publish a rendezvous only inside the actual owner foreground session."""
    from kicad_mcp.cloud_managed_connector import (
        _connector_session_lock,
        _remove_private_file,
        _session_lock_held,
    )

    generation = os.environ.get("KICAD_CLOUD_UPDATE_GENERATION", "")
    slot = os.environ.get("KICAD_CLOUD_UPDATE_SLOT", "")
    if os.name != "posix" or origin != _KICAD_CLOUD_ORIGIN or not _valid(generation, slot):
        yield None
        return
    if not _session_lock_held(root):
        raise LocalApprovalDeniedError("No local foreground session owns update control.")
    with _connector_session_lock(root, name=LOCK):
        identity = (generation, slot)
        _write_private_json(root, LEASE, {"generation": generation, "slot": slot})
        drain = asyncio.Event()

        async def poll() -> None:
            while not drain.is_set():
                if _read(root, LEASE) != identity or _read(root, REQUEST) == identity:
                    drain.set()
                    return
                try:
                    await asyncio.wait_for(drain.wait(), timeout=0.2)
                except TimeoutError:
                    pass

        waiter = asyncio.create_task(poll())
        try:
            # Catch requests issued during the prior device-only phase too.
            if _read(root, REQUEST) == identity:
                drain.set()
            yield drain
        finally:
            waiter.cancel()
            await asyncio.gather(waiter, return_exceptions=True)
            if _read(root, LEASE) == identity:
                _remove_private_file(root, LEASE)
            # The request remains generation-bound across a device-only ->
            # project transition. It cannot affect a newly launched process.
