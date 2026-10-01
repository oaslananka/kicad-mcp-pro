"""Studio bridge resources and tools."""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from typing import Any, Literal

from mcp.server.mcpserver import MCPServer as FastMCP

from ..config import get_config
from ..discovery import auto_set_project_from_file
from ..tools.metadata import headless_compatible


class _StudioContextStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._payload: dict[str, Any] | None = None

    def get(self) -> dict[str, Any] | None:
        with self._lock:
            return None if self._payload is None else dict(self._payload)

    def set(self, payload: dict[str, Any]) -> None:
        with self._lock:
            self._payload = dict(payload)


_studio_context_store = _StudioContextStore()


def register(mcp: FastMCP) -> None:
    """Register studio bridge resource and context push tool."""

    @mcp.resource("kicad://studio/context")
    def get_studio_context() -> str:
        """Return the latest KiCad Studio IDE context."""
        payload = _studio_context_store.get()
        if payload is None:
            return "KiCad Studio is not connected."
        return json.dumps(payload, indent=2, ensure_ascii=False)

    @mcp.tool()
    @headless_compatible
    def studio_push_context(
        active_file: str | None = None,
        file_type: Literal["schematic", "pcb", "other"] = "other",
        drc_errors: list[str] | None = None,
        selected_net: str | None = None,
        selected_reference: str | None = None,
        cursor_position: dict[str, object] | None = None,
        snapshot: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Update the active IDE context pushed by KiCad Studio."""
        project_file = _snapshot_string(snapshot, "projectFile")
        project_root = _snapshot_string(snapshot, "projectRoot")
        if not active_file and not project_file and not project_root:
            return {
                "ok": False,
                "code": "NO_ACTIVE_PROJECT",
                "message": (
                    "No active KiCad project or file was included in the "
                    "studio_push_context request."
                ),
                "details": {
                    "active_file": active_file,
                    "file_type": file_type,
                    "snapshot": snapshot or {},
                },
                "fallbackAvailable": True,
            }

        payload = {
            "active_file": active_file,
            "file_type": file_type,
            "drc_errors": drc_errors or [],
            "selected_net": selected_net,
            "selected_reference": selected_reference,
            "cursor_position": cursor_position,
            "snapshot": snapshot or {},
            "updated_at": datetime.now(UTC).isoformat(),
        }
        _studio_context_store.set(payload)

        detected = None
        if active_file and get_config().project_dir is None:
            detected = auto_set_project_from_file(active_file)

        return {
            "ok": True,
            "data": {
                "message": "Studio context updated.",
                "detectedProject": str(detected) if detected is not None else None,
                "activeFile": active_file,
                "projectFile": project_file,
                "projectRoot": project_root,
            },
            "source": "cached",
        }


def _snapshot_string(snapshot: Any, key: str) -> str | None:  # noqa: ANN401
    if snapshot is not None and not isinstance(snapshot, dict):
        raise ValueError("snapshot must be a dictionary")
    if snapshot is None:
        return None
    value = snapshot.get(key)
    if value is not None and not isinstance(value, str):
        raise ValueError("Value must be a string")
    return value if value else None
