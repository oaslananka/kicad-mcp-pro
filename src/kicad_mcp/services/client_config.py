"""Application-owned, safe, and reversible local AI client configuration service."""

from __future__ import annotations

import hashlib
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


def _hash_record_path(registry_root: Path | None = None) -> Path:
    return _default_registry_file(registry_root).with_name("owned_client_entry_hashes.json")


def _read_entry_hashes(registry_root: Path | None = None) -> dict[str, str]:
    path = _hash_record_path(registry_root)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ClientConfigError("Owned entry integrity registry is unreadable") from exc
    if not isinstance(data, dict) or not all(
        isinstance(k, str) and isinstance(v, str) and len(v) == 64 for k, v in data.items()
    ):
        raise ClientConfigError("Owned entry integrity registry is malformed")
    return data


def _hash_key(client: str, path: Path, namespace: str, server: str) -> str:
    return json.dumps([client, str(path.resolve()), namespace, server], ensure_ascii=False)


def _hash_value(value: object) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _write_entry_hashes(data: dict[str, str], registry_root: Path | None) -> None:
    path = _hash_record_path(registry_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix="kicad_owned_", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, indent=2, sort_keys=True)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def _save_owned_hashes(
    client: str, config_path: Path, content: dict[str, Any], registry_root: Path | None
) -> None:
    hashes = _read_entry_hashes(registry_root)
    for namespace in ("mcpServers", "servers"):
        entries = content.get(namespace)
        if isinstance(entries, dict) and "kicad-mcp-pro" in entries:
            hashes[_hash_key(client, config_path, namespace, "kicad-mcp-pro")] = _hash_value(
                entries["kicad-mcp-pro"]
            )
    _write_entry_hashes(hashes, registry_root)


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


def _unrecord_owned_config(
    client: str, config_path: Path, registry_root: Path | None = None
) -> None:
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


def _prepare_config_contents(
    config_path: Path, snippet: dict[str, Any]
) -> tuple[dict[str, Any], Path | None]:
    """Read/backup a user-owned config before any replacement is attempted."""
    if not config_path.exists():
        config_path.parent.mkdir(parents=True, exist_ok=True)
        return snippet, None
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ClientConfigError(f"Configuration file root must be a JSON object: {config_path}")
    except json.JSONDecodeError as err:
        raise ClientConfigError(f"Malformed JSON in existing config {config_path}: {err}") from err
    backup_path = config_path.with_suffix(".json.bak")
    try:
        shutil.copy2(config_path, backup_path)
    except OSError as err:
        raise ClientConfigError(f"Failed to create backup at {backup_path}: {err}") from err

    for namespace in ("mcpServers", "servers"):
        if namespace not in snippet:
            continue
        entries = data.setdefault(namespace, {})
        incoming = snippet[namespace]
        if not isinstance(entries, dict) or not isinstance(incoming, dict):
            raise ClientConfigError("Existing MCP client server entries are invalid")
        entries.update(incoming)
    for key, value in snippet.items():
        if key not in ("mcpServers", "servers"):
            data[key] = value
    return data, backup_path


def write_client_config_safe(
    client: str,
    config_path: Path,
    snippet: dict[str, Any],
    registry_root: Path | None = None,
) -> WriteConfigResult:
    """Safely merge snippet into client config with backup and registry tracking."""
    config_path = Path(config_path)
    merged_data, backup_path = _prepare_config_contents(config_path, snippet)

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
    _save_owned_hashes(client, config_path, merged_data, registry_root)

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

    if str(config_path.resolve()) not in get_owned_client_configs(registry_root).get(client, []):
        raise ClientConfigError("Configuration entry is not recorded as application-owned")
    namespaces = [
        kind
        for kind in ("mcpServers", "servers")
        if isinstance(data.get(kind), dict) and server_key in data[kind]
    ]
    if not namespaces:
        _unrecord_owned_config(client, config_path, registry_root)
        return False

    hashes = _read_entry_hashes(registry_root)
    for kind in namespaces:
        saved = hashes.get(_hash_key(client, config_path, kind, server_key))
        if saved is None or saved != _hash_value(data[kind][server_key]):
            # A pre-existing path-only record is NOT proof that a modified
            # entry still belongs to this installation.
            raise ClientConfigError("Client entry has changed or ownership is unverified")
    for kind in namespaces:
        del data[kind][server_key]

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
    for kind in namespaces:
        hashes.pop(_hash_key(client, config_path, kind, server_key), None)
    _write_entry_hashes(hashes, registry_root)
    return True
