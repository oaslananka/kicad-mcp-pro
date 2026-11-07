"""Application-owned lifecycle manager for the KiCad Cloud Connector.

Manages start, stop, single instance, safe active-project switching,
and status monitoring without requiring systemd on Windows/macOS.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from kicad_mcp.cloud_local_registry import default_registry_root
from kicad_mcp.cloud_managed_connector import (
    _CONNECTED_STATUS_MAX_AGE_MS,
    _CONNECTING_STATUS_MAX_AGE_MS,
    _ENABLED_FILE,
    _STATUS_FIELDS,
    _STATUS_FILE,
    _identity_state,
    _remove_private_file,
    _run_connector,
    _write_status,
)
from kicad_mcp.cloud_pair_keys import _read_private_json, _write_private_json
from kicad_mcp.cloud_registered_pilot import _single_registered_identity

_ACTIVE_PROJECT_FILE = "active_project.json"

logger = logging.getLogger(__name__)


class ConnectorState(StrEnum):
    OFF = "off"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    UNAVAILABLE = "unavailable"


@dataclass
class ConnectorStatus:
    state: ConnectorState
    active_project_id: str | None = None
    updated_at: float | None = None
    error: str | None = None


class ConnectorLifecycleManager:
    """Manages the in-process / application-owned Cloud Connector task."""

    def __init__(self, registry_root: Path | None = None) -> None:
        self.root = registry_root if registry_root is not None else default_registry_root()
        self._task: asyncio.Task[int] | None = None
        self._stop_event: asyncio.Event | None = None
        self._lock = asyncio.Lock()

    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    def get_status(self) -> ConnectorStatus:
        active_proj = self.get_active_project_id()
        if not (self.root / _ENABLED_FILE).exists() and not self.is_running():
            return ConnectorStatus(state=ConnectorState.OFF, active_project_id=active_proj)

        if not self.is_running():
            return ConnectorStatus(state=ConnectorState.UNAVAILABLE, active_project_id=active_proj)

        try:
            status_data = _read_private_json(self.root, _STATUS_FILE)
            raw_state = status_data.get("state")
            updated = status_data.get("updatedAtUnixMs")
            if (
                status_data.keys() != _STATUS_FIELDS
                or type(updated) is not int
                or status_data.get("pid") != os.getpid()
            ):
                return ConnectorStatus(
                    state=ConnectorState.UNAVAILABLE, active_project_id=active_proj
                )
            age = time.time_ns() // 1_000_000 - updated
            if raw_state == "connected" and 0 <= age <= _CONNECTED_STATUS_MAX_AGE_MS:
                return ConnectorStatus(
                    state=ConnectorState.CONNECTED, active_project_id=active_proj
                )
            if raw_state == "connecting" and 0 <= age <= _CONNECTING_STATUS_MAX_AGE_MS:
                return ConnectorStatus(
                    state=ConnectorState.CONNECTING, active_project_id=active_proj
                )
            return ConnectorStatus(state=ConnectorState.UNAVAILABLE, active_project_id=active_proj)
        except Exception:
            if self.is_running():
                return ConnectorStatus(
                    state=ConnectorState.CONNECTING, active_project_id=active_proj
                )
            return ConnectorStatus(state=ConnectorState.OFF, active_project_id=active_proj)

    async def start(self) -> bool:
        """Start the owner-managed connector. Returns True if started, False if already running."""
        async with self._lock:
            if self.is_running():
                return False

            try:
                record = self._resolve_active_record()
            except Exception:
                logger.exception("Cannot start connector: registration resolution failed")
                return False

            # Enable file
            enabled_payload = _identity_state(record)
            _write_private_json(self.root, _ENABLED_FILE, enabled_payload)
            _write_status(self.root, "connecting")

            self._stop_event = asyncio.Event()
            self._task = asyncio.create_task(
                _run_connector(root=self.root, stop_event=self._stop_event)
            )
            return True

    async def stop(self) -> bool:
        """Stop connector, fence in-flight reads, and mark disabled."""
        async with self._lock:
            if self._stop_event is not None:
                self._stop_event.set()
            _remove_private_file(self.root, _ENABLED_FILE)

            if self._task is not None:
                try:
                    await asyncio.wait_for(asyncio.shield(self._task), timeout=5.0)
                except TimeoutError:
                    self._task.cancel()
                    # A cancelled child returns a result; cancellation of the
                    # caller still propagates rather than being swallowed.
                    results = await asyncio.gather(self._task, return_exceptions=True)
                    for result in results:
                        if isinstance(result, BaseException) and not isinstance(
                            result, asyncio.CancelledError
                        ):
                            raise result from None
                except asyncio.CancelledError:
                    self._task.cancel()
                    raise
                finally:
                    self._task = None

            try:
                _write_status(self.root, "unavailable")
            except OSError:
                pass
            return True

    def get_active_project_id(self) -> str | None:
        """Return the unique verified registration, never an arbitrary record."""
        try:
            record = _single_registered_identity(self.root)
            try:
                pointer = _read_private_json(self.root, _ACTIVE_PROJECT_FILE)
            except Exception:
                if (self.root / _ACTIVE_PROJECT_FILE).exists():
                    return None
                return record["projectId"]
            return (
                record["projectId"]
                if pointer.get("activeProjectId") == record["projectId"]
                else None
            )
        except (OSError, ValueError):
            return None

    def _resolve_active_record(self) -> dict[str, str]:
        record = _single_registered_identity(self.root)
        if self.get_active_project_id() != record["projectId"]:
            raise ValueError("Active project does not match the verified registration")
        return record

    def enable_connector(self) -> None:
        """Synchronously mark the connector enabled."""
        record = self._resolve_active_record()
        enabled_payload = _identity_state(record)
        _write_private_json(self.root, _ENABLED_FILE, enabled_payload)
        _write_status(self.root, "connecting")

    def disable_connector(self) -> None:
        """Synchronously mark the connector disabled."""
        _remove_private_file(self.root, _ENABLED_FILE)
        try:
            _write_status(self.root, "unavailable")
        except OSError:
            pass

    def set_active_project(self, project_path_or_id: str) -> None:
        """Select only the uniquely verified local registration."""
        record = _single_registered_identity(self.root)
        if project_path_or_id not in (record["projectId"], record["directory"]):
            raise ValueError("Project is not the verified registration")
        _write_private_json(
            self.root, _ACTIVE_PROJECT_FILE, {"activeProjectId": record["projectId"]}
        )

    async def switch_active_project(self, project_id: str) -> bool:
        """Select the registered project; unverified identifiers fail closed."""
        async with self._lock:
            # Never switch the active registry binding under an in-flight read.
            # Stop the connector before selecting another project.
            if self.is_running():
                return self.get_active_project_id() == project_id
            try:
                self.set_active_project(project_id)
            except (OSError, ValueError):
                return False
            return True
