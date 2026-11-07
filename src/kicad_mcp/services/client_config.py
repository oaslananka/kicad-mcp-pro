"""Application-owned, safe, and reversible local AI client configuration service."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from kicad_mcp.cloud_pair import default_registry_root


class ClientConfigError(Exception):
    """Raised when client configuration cannot be read or written safely."""


@dataclass
class WriteConfigResult:
    """Outcome of writing or updating a client configuration."""

    success: bool
    backup_path: Path | None = None
    message: str = ""


def _default_registry_file(registry_root: Path | None = None) -> Path:
    if registry_root is not None:
        return registry_root / "owned_client_configs.json"
    return default_registry_root() / "owned_client_configs.json"


def get_owned_client_configs(registry_root: Path | None = None) -> dict[str, list[str]]:
    """Return dictionary mapping client identifiers to owned config paths."""
    reg_file = _default_registry_file(registry_root)
    if not reg_file.is_file():
        return {}
    try:
        data = json.loads(reg_file.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return {str(k): [str(p) for p in v] for k, v in data.items() if isinstance(v, list)}
    except Exception:
        return {}
    return {}


def _record_owned_config(client: str, config_path: Path, registry_root: Path | None = None) -> None:
    reg_file = _default_registry_file(registry_root)
    reg_file.parent.mkdir(parents=True, exist_ok=True)
    owned = get_owned_client_configs(registry_root)
    resolved = str(config_path.resolve())
    paths = owned.setdefault(client, [])
    if resolved not in paths:
        paths.append(resolved)
    reg_file.write_text(json.dumps(owned, indent=2), encoding="utf-8")


def _unrecord_owned_config(client: str, config_path: Path, registry_root: Path | None = None) -> None:
    reg_file = _default_registry_file(registry_root)
    if not reg_file.is_file():
        return
    owned = get_owned_client_configs(registry_root)
    resolved = str(config_path.resolve())
    if client in owned:
        owned[client] = [p for p in owned[client] if p != resolved]
        if not owned[client]:
            del owned[client]
        reg_file.write_text(json.dumps(owned, indent=2), encoding="utf-8")


def write_client_config_safe(
    client: str,
    config_path: Path,
    snippet: dict[str, Any],
    registry_root: Path | None = None,
) -> WriteConfigResult:
    """Safely merge snippet into client config with backup and registry tracking."""
    config_path = Path(config_path)
    backup_path: Path | None = None

    if config_path.exists():
        try:
            content = config_path.read_text(encoding="utf-8")
            data = json.loads(content)
            if not isinstance(data, dict):
                raise ClientConfigError(f"Configuration file root must be a JSON object: {config_path}")
        except json.JSONDecodeError as err:
            raise ClientConfigError(f"Malformed JSON in existing config {config_path}: {err}") from err

        # Create .json.bak backup
        backup_path = config_path.with_suffix(".json.bak")
        try:
            shutil.copy2(config_path, backup_path)
        except OSError as err:
            raise ClientConfigError(f"Failed to create backup at {backup_path}: {err}") from err

        # Safe merge mcpServers
        if "mcpServers" in snippet:
            servers = data.setdefault("mcpServers", {})
            if isinstance(servers, dict) and isinstance(snippet["mcpServers"], dict):
                servers.update(snippet["mcpServers"])
            else:
                data["mcpServers"] = snippet["mcpServers"]

        for k, v in snippet.items():
            if k != "mcpServers":
                data[k] = v
        merged_data = data
    else:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        merged_data = snippet

    try:
        # Atomic write
        tmp_fd, tmp_path = tempfile.mkstemp(
            prefix="kicad_cfg_",
            suffix=".tmp",
            dir=str(config_path.parent),
        )
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            json.dump(merged_data, f, indent=2)
            f.write("\n")
        os.replace(tmp_path, config_path)
    except OSError as err:
        raise ClientConfigError(f"Failed to write config at {config_path}: {err}") from err

    _record_owned_config(client, config_path, registry_root)

    return WriteConfigResult(
        success=True,
        backup_path=backup_path,
        message=f"Configured {client} at {config_path}",
    )


def remove_client_config_entry(
    client: str,
    config_path: Path,
    server_key: str = "kicad-mcp-pro",
    registry_root: Path | None = None,
) -> bool:
    """Remove server_key entry from config_path while preserving other servers."""
    config_path = Path(config_path)
    if not config_path.is_file():
        return False

    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception as err:
        raise ClientConfigError(f"Failed to read existing config at {config_path}: {err}") from err

    servers = data.get("mcpServers")
    if not isinstance(servers, dict) or server_key not in servers:
        _unrecord_owned_config(client, config_path, registry_root)
        return False

    del servers[server_key]
    data["mcpServers"] = servers

    try:
        tmp_fd, tmp_path = tempfile.mkstemp(
            prefix="kicad_cfg_",
            suffix=".tmp",
            dir=str(config_path.parent),
        )
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        os.replace(tmp_path, config_path)
    except OSError as err:
        raise ClientConfigError(f"Failed to update config at {config_path}: {err}") from err

    _unrecord_owned_config(client, config_path, registry_root)
    return True
