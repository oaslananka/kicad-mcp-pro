"""Embedded file management for KiCad projects.

FAZ 9 — project_list_embedded_files, project_embed_file,
        project_extract_embedded_file, project_remove_embedded_file.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from mcp.server.fastmcp import FastMCP

from ..config import get_config
from ..path_safety import assert_within
from .metadata import headless_compatible


def _project_file() -> Path:
    cfg = get_config()
    if cfg.project_file is None or not cfg.project_file.exists():
        raise ValueError("No project file is configured. Call kicad_set_project() first.")
    return cfg.project_file


def _load_project_payload() -> dict[str, Any]:
    path = _project_file()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Project file '{path}' does not contain valid JSON.") from exc
    if not isinstance(payload, dict):
        raise ValueError("Project file must contain a JSON object at the root.")
    return cast(dict[str, Any], payload)


def _save_project_payload(payload: dict[str, Any]) -> Path:
    path = _project_file()
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def _project_dir() -> Path:
    cfg = get_config()
    if cfg.project_dir is None:
        raise ValueError("No active project directory is configured.")
    return cfg.project_dir


def register(mcp: FastMCP) -> None:
    """Register embedded file management tools."""

    @mcp.tool()
    @headless_compatible
    def project_list_embedded_files() -> str:
        """List all embedded (project-embedded) files in the active project.

        Returns a JSON array of embedded file entries with their metadata
        (name, source path, description).
        """
        payload = _load_project_payload()
        embedded = payload.get("embedded_files", [])
        if isinstance(embedded, dict):
            embedded = list(embedded.values())
        if not isinstance(embedded, list):
            embedded = []
        return json.dumps({"embedded_files": embedded, "count": len(embedded)}, indent=2)

    @mcp.tool()
    @headless_compatible
    def project_embed_file(
        source_path: str,
        target_name: str | None = None,
        description: str = "",
    ) -> str:
        """Embed an external file into the KiCad project as project metadata.

        The file content is stored inline inside the ``.kicad_pro`` JSON.
        Large files (over 1 MB) are rejected to keep project files manageable.

        Parameters
        ----------
        source_path : str
            Absolute or relative path to the file to embed.
        target_name : str | None
            Name to store the file as (defaults to the source file name).
        description : str
            Optional human description of the embedded file.
        """
        cfg = get_config()
        src = Path(source_path)
        if not src.is_absolute():
            src = cfg.resolve_within_project(source_path)
        src = src.resolve()

        if not src.exists():
            raise FileNotFoundError(f"Source file '{src}' does not exist.")
        if not src.is_file():
            raise ValueError(f"'{src}' is not a file.")

        file_size = src.stat().st_size
        if file_size > 1_000_000:
            raise ValueError(f"File '{src}' is {file_size} bytes (max 1 MB for embedding).")

        content = src.read_bytes()
        import base64

        encoded = base64.b64encode(content).decode("ascii")

        name = (target_name or src.name).strip()
        if not name:
            raise ValueError("target_name must not be empty.")

        payload = _load_project_payload()
        embedded = payload.setdefault("embedded_files", [])
        if isinstance(embedded, dict):
            embedded = list(embedded.values())
            payload["embedded_files"] = embedded

        # Remove existing entry with same name
        embedded[:] = [e for e in embedded if e.get("name") != name]

        entry: dict[str, Any] = {
            "name": name,
            "description": description,
            "original_path": str(src),
            "size_bytes": file_size,
            "encoding": "base64",
            "content": encoded,
        }
        embedded.append(entry)
        _save_project_payload(payload)

        return f"File '{name}' embedded into project ({file_size} bytes, base64-encoded)."

    @mcp.tool()
    @headless_compatible
    def project_extract_embedded_file(name: str, output_path: str | None = None) -> str:
        """Extract an embedded file from the project and write it to disk.

        Parameters
        ----------
        name : str
            Name of the embedded file to extract (see ``project_list_embedded_files``).
        output_path : str | None
            Destination file path. If omitted, extracts to the project directory
            using the embedded file name.
        """
        import base64

        payload = _load_project_payload()
        embedded = payload.get("embedded_files", [])
        if isinstance(embedded, dict):
            embedded = list(embedded.values())

        entry = None
        for e in embedded:
            if e.get("name") == name:
                entry = e
                break

        if entry is None:
            names = [e.get("name", "") for e in embedded]
            hint = ", ".join(names[:20]) if names else "(no embedded files)"
            raise ValueError(f"Embedded file '{name}' not found. Available: {hint}")

        encoded = entry.get("content", "")
        try:
            decoded = base64.b64decode(encoded)
        except Exception as exc:
            raise ValueError(f"Failed to decode embedded file '{name}': {exc}") from exc

        if output_path:
            out = Path(output_path)
            if not out.is_absolute():
                out = _project_dir() / out
        else:
            out = _project_dir() / name

        assert_within(_project_dir(), out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(decoded)

        return f"Embedded file '{name}' extracted to {out} ({len(decoded)} bytes)."

    @mcp.tool()
    @headless_compatible
    def project_remove_embedded_file(name: str) -> str:
        """Remove an embedded file entry from the project metadata.

        Parameters
        ----------
        name : str
            Name of the embedded file to remove.
        """
        payload = _load_project_payload()
        embedded = payload.get("embedded_files", [])
        if isinstance(embedded, dict):
            embedded = list(embedded.values())

        before = len(embedded)
        embedded[:] = [e for e in embedded if e.get("name") != name]
        removed = before - len(embedded)

        if removed == 0:
            names = [e.get("name", "") for e in embedded]
            hint = ", ".join(names[:20]) if names else "(no embedded files)"
            raise ValueError(f"Embedded file '{name}' not found. Available: {hint}")

        payload["embedded_files"] = embedded
        _save_project_payload(payload)
        return f"Removed embedded file '{name}' from the project ({removed} entry deleted)."
