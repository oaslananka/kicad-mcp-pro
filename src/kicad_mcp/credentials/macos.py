"""macOS Keychain implementation using the system security CLI."""

from __future__ import annotations

import json
import re
import subprocess

from . import PlatformCredentialStore

_SERVICE_NAME = "KiCadMCPPro"
_SLOT_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,64}")


def _validate_slot(slot: str) -> str:
    clean = slot.replace("-", "").lower()
    if not _SLOT_PATTERN.fullmatch(clean):
        raise ValueError(f"Invalid macOS credential slot: {slot}")
    return clean


class MacOSKeychainCredentialStore(PlatformCredentialStore):
    """macOS user Keychain credential store."""

    def save_key(self, record_id: str, key_pem: bytes) -> None:
        slot = _validate_slot(record_id)
        # Store as hex to ensure safe transmission across CLI args
        payload = key_pem.hex()
        cmd = [
            "/usr/bin/security",
            "add-generic-password",
            "-s",
            _SERVICE_NAME,
            "-a",
            f"{slot}_key",
            "-w",
            payload,
            "-U",
        ]
        res = subprocess.run(cmd, capture_output=True, check=False)
        if res.returncode != 0:
            raise RuntimeError(f"Failed to store key in macOS Keychain: code {res.returncode}")

    def load_key(self, record_id: str) -> bytes | None:
        slot = _validate_slot(record_id)
        cmd = [
            "/usr/bin/security",
            "find-generic-password",
            "-s",
            _SERVICE_NAME,
            "-a",
            f"{slot}_key",
            "-w",
        ]
        res = subprocess.run(cmd, capture_output=True, check=False)
        if res.returncode != 0:
            return None
        hex_data = res.stdout.strip().decode("utf-8")
        try:
            return bytes.fromhex(hex_data)
        except ValueError:
            return None

    def save_binding(self, record_id: str, binding: dict[str, str]) -> None:
        slot = _validate_slot(record_id)
        payload = json.dumps(binding, sort_keys=True).encode("utf-8").hex()
        cmd = [
            "/usr/bin/security",
            "add-generic-password",
            "-s",
            _SERVICE_NAME,
            "-a",
            f"{slot}_binding",
            "-w",
            payload,
            "-U",
        ]
        res = subprocess.run(cmd, capture_output=True, check=False)
        if res.returncode != 0:
            raise RuntimeError(f"Failed to store binding in macOS Keychain: code {res.returncode}")

    def load_binding(self, record_id: str) -> dict[str, str] | None:
        slot = _validate_slot(record_id)
        cmd = [
            "/usr/bin/security",
            "find-generic-password",
            "-s",
            _SERVICE_NAME,
            "-a",
            f"{slot}_binding",
            "-w",
        ]
        res = subprocess.run(cmd, capture_output=True, check=False)
        if res.returncode != 0:
            return None
        hex_data = res.stdout.strip().decode("utf-8")
        try:
            raw = bytes.fromhex(hex_data)
            data = json.loads(raw.decode("utf-8"))
            if isinstance(data, dict):
                return {str(k): str(v) for k, v in data.items()}
            return None
        except (ValueError, json.JSONDecodeError):
            return None

    def delete_credentials(self, record_id: str) -> bool:
        slot = _validate_slot(record_id)
        deleted = False
        for part in ("_key", "_binding"):
            cmd = [
                "/usr/bin/security",
                "delete-generic-password",
                "-s",
                _SERVICE_NAME,
                "-a",
                f"{slot}{part}",
            ]
            res = subprocess.run(cmd, capture_output=True, check=False)
            if res.returncode == 0:
                deleted = True
        return deleted
