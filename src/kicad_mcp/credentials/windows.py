"""Windows Credential Manager implementation using Generic Credentials."""

from __future__ import annotations

import json

from kicad_mcp import cloud_windows_credentials as win_cred

from . import PlatformCredentialStore


def _normalize_record_id(record_id: str) -> str:
    clean = record_id.replace("-", "").lower()
    if not win_cred._RECORD_ID.fullmatch(clean):
        raise ValueError(
            f"Invalid Windows credential record_id: must be 32 hex chars, got {record_id}"
        )
    return clean


class WindowsCredentialStore(PlatformCredentialStore):
    """Windows user-scoped Credential Manager store."""

    def save_key(self, record_id: str, key_pem: bytes) -> None:
        rec = _normalize_record_id(record_id)
        win_cred.create_credential(rec, "key", key_pem)

    def load_key(self, record_id: str) -> bytes | None:
        rec = _normalize_record_id(record_id)
        return win_cred.read_credential(rec, "key")

    def save_binding(self, record_id: str, binding: dict[str, str]) -> None:
        rec = _normalize_record_id(record_id)
        data = json.dumps(binding, sort_keys=True).encode("utf-8")
        win_cred.create_credential(rec, "binding", data)

    def load_binding(self, record_id: str) -> dict[str, str] | None:
        rec = _normalize_record_id(record_id)
        raw = win_cred.read_credential(rec, "binding")
        if raw is None:
            return None
        data = json.loads(raw.decode("utf-8"))
        if isinstance(data, dict):
            return {str(k): str(v) for k, v in data.items()}
        return None

    def delete_credentials(self, record_id: str) -> bool:
        rec = _normalize_record_id(record_id)
        k = win_cred.delete_credential(rec, "key")
        b = win_cred.delete_credential(rec, "binding")
        return k or b
