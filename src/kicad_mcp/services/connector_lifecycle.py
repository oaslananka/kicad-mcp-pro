"""Application-owned lifecycle manager for the KiCad Cloud Connector.

Manages start, stop, single instance, safe active-project switching,
and status monitoring without requiring systemd on Windows/macOS.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from kicad_mcp.cloud_local_registry import default_registry_root
from kicad_mcp.cloud_managed_connector import (
    _ENABLED_FILE,
    _STATUS_FILE,
    _identity_state,
    _read_private_json,
    _remove_private_file,
    _run_connector,
    _write_private_json,
    _write_status,
)
from kicad_mcp.cloud_registered_pilot import _single_registered_identity

logger = logging.getLogger(__name__)


class ConnectorState(str, Enum):
    OFF = "off"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    UNAVAILABLE = "unavailable"


@dataclass
class ConnectorStatus:
    state: ConnectorState
    active_project_id: Optional[str] = None
    updated_at: Optional[float] = None
    error: Optional[str] = None


class ConnectorLifecycleManager:
    """Manages the in-process / application-owned Cloud Connector task."""

    def __init__(self, registry_root: Optional[Path] = None) -> None:
        self.root = registry_root if registry_root is not None else default_registry_root()
        self._task: Optional[asyncio.Task[int]] = None
        self._stop_event: Optional[asyncio.Event] = None
        self._lock = asyncio.Lock()

    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    def get_status(self) -> ConnectorStatus:
        active_proj = self.get_active_project_id()
        if not (self.root / _ENABLED_FILE).exists() and not self.is_running():
            return ConnectorStatus(state=ConnectorState.OFF, active_project_id=active_proj)

        try:
            status_data = _read_private_json(self.root, _STATUS_FILE)
            raw_state = status_data.get("state")
            if raw_state == "connected":
                return ConnectorStatus(state=ConnectorState.CONNECTED, active_project_id=active_proj)
            if raw_state == "connecting":
                return ConnectorStatus(state=ConnectorState.CONNECTING, active_project_id=active_proj)
            return ConnectorStatus(state=ConnectorState.UNAVAILABLE, active_project_id=active_proj)
        except Exception:
            if self.is_running():
                return ConnectorStatus(state=ConnectorState.CONNECTING, active_project_id=active_proj)
            return ConnectorStatus(state=ConnectorState.OFF, active_project_id=active_proj)

    async def start(self) -> bool:
        """Start the owner-managed connector. Returns True if started, False if already running."""
        async with self._lock:
            if self.is_running():
                return False

            try:
                record = self._resolve_active_record()
            except Exception as exc:
                logger.error("Cannot start connector: registration resolution failed: %s", exc)
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

            if self._task is not None:
                try:
                    await asyncio.wait_for(asyncio.shield(self._task), timeout=5.0)
                except (asyncio.TimeoutError, asyncio.CancelledError):
                    self._task.cancel()
                self._task = None

            _remove_private_file(self.root, _ENABLED_FILE)
            try:
                _write_status(self.root, "unavailable")
            except Exception:
                pass
            return True

    def get_active_project_id(self) -> Optional[str]:
        """Read the active project ID."""
        active_file = self.root / "active_project.json"
        if active_file.exists():
            try:
                data = json.loads(active_file.read_text(encoding="utf-8"))
                return data.get("activeProjectId")
            except Exception:
                pass

        # Fall back to first registered project
        projects_dir = self.root / "projects"
        if projects_dir.exists():
            projs = sorted(p.stem for p in projects_dir.glob("*.json"))
            if projs:
                return projs[0]
        return None

    def _resolve_active_record(self) -> dict[str, str]:
        active_id = self.get_active_project_id()
        if active_id:
            record_path = self.root / "projects" / f"{active_id}.json"
            if record_path.exists():
                return json.loads(record_path.read_text(encoding="utf-8"))
        return _single_registered_identity(self.root)

    async def switch_active_project(self, project_id: str) -> bool:
        """Switch active project with read-fencing. Fails closed if project does not exist."""
        record_file = self.root / "projects" / f"{project_id}.json"
        if not record_file.exists():
            return False

        async with self._lock:
            was_running = self.is_running()
            if was_running:
                # Stop existing connector to fence in-flight reads
                if self._stop_event:
                    self._stop_event.set()
                if self._task:
                    try:
                        await asyncio.wait_for(asyncio.shield(self._task), timeout=3.0)
                    except (asyncio.TimeoutError, asyncio.CancelledError):
                        self._task.cancel()
                    self._task = None

            # Update active project pointer
            active_file = self.root / "active_project.json"
            active_file.write_text(
                json.dumps({"activeProjectId": project_id, "updatedAt": time.time()}),
                encoding="utf-8",
            )
            if hasattr(os, "chmod"):
                os.chmod(active_file, 0o600)

            if was_running:
                # Restart connector with new project identity
                record = json.loads(record_file.read_text(encoding="utf-8"))
                _write_private_json(self.root, _ENABLED_FILE, _identity_state(record))
                _write_status(self.root, "connecting")
                self._stop_event = asyncio.Event()
                self._task = asyncio.create_task(
                    _run_connector(root=self.root, stop_event=self._stop_event)
                )

            return True
