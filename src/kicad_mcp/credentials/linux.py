"""Linux owner-private filesystem storage retaining existing POSIX permission contracts."""

from __future__ import annotations

import os
from pathlib import Path

from kicad_mcp.cloud_local_registry import default_registry_root
from kicad_mcp.cloud_pair_keys import _read_owner_binding, _save_owner_binding

from . import PlatformCredentialStore


class LinuxCredentialStore(PlatformCredentialStore):
    """Linux protected filesystem store."""

    def __init__(self, registry_root: Path | None = None) -> None:
        self.root = registry_root if registry_root is not None else default_registry_root()

    def _keys_dir(self) -> Path:
        keys_dir = self.root / "keys"
        keys_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
        if hasattr(os, "chmod"):
            os.chmod(keys_dir, 0o700)
        return keys_dir

    def save_key(self, record_id: str, key_pem: bytes) -> None:
        keyfile = self._keys_dir() / f"{record_id}.pem"
        keyfile.write_bytes(key_pem)
        if hasattr(os, "chmod"):
            os.chmod(keyfile, 0o600)

    def load_key(self, record_id: str) -> bytes | None:
        keyfile = self._keys_dir() / f"{record_id}.pem"
        if not keyfile.exists():
            return None
        return keyfile.read_bytes()

    def save_binding(self, record_id: str, binding: dict[str, str]) -> None:
        keyfile = self._keys_dir() / f"{record_id}.pem"
        _save_owner_binding(
            keyfile,
            origin=binding["origin"],
            device_id=binding["deviceId"],
            fingerprint=binding["fingerprint"],
            owner_sub=binding.get("ownerSub"),
        )

    def load_binding(self, record_id: str) -> dict[str, str] | None:
        keyfile = self._keys_dir() / f"{record_id}.pem"
        try:
            return _read_owner_binding(keyfile)
        except Exception:
            return None

    def delete_credentials(self, record_id: str) -> bool:
        keyfile = self._keys_dir() / f"{record_id}.pem"
        binding_file = keyfile.parent / (keyfile.name + ".cloud-binding-v1.json")
        deleted = False
        if keyfile.exists():
            keyfile.unlink(missing_ok=True)
            deleted = True
        if binding_file.exists():
            binding_file.unlink(missing_ok=True)
            deleted = True
        return deleted
