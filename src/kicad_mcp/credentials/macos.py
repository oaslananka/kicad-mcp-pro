"""macOS Keychain implementation using the system security CLI."""

from __future__ import annotations

import json
import re
import subprocess  # nosec B404

from . import PlatformCredentialStore

_SERVICE_NAME = "KiCadMCPPro"
_SECURITY_EXECUTABLE = "/usr/bin/security"
_SLOT_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,64}")


def _validate_slot(slot: str) -> str:
    clean = slot.replace("-", "").lower()
    if not _SLOT_PATTERN.fullmatch(clean):
        raise ValueError(f"Invalid macOS credential slot: {slot}")
    return clean


def _write_secret(slot: str, secret: bytes) -> None:
    """Write a hex-encoded secret without leaking it in process argv.

    macOS security add-generic-password -w VALUE exposes VALUE to process
    inspection. The security -i batch interface accepts a command through
    stdin instead. Only a validated slot and a hex payload enter that command;
    user-controlled characters can never introduce an extra command.
    """
    if not secret:
        raise ValueError("Keychain secret must not be empty")
    # Keep unsupported/oversized items from causing unpredictable Keychain
    # prompting or truncated batch data. Typical PEM keys are much smaller.
    if len(secret) > 65536:
        raise ValueError("Keychain secret exceeds the supported size")
    command = f"add-generic-password -U -s {_SERVICE_NAME} -a {slot} -w {secret.hex()}\nquit\n"
    try:
        result = subprocess.run(
            [_SECURITY_EXECUTABLE, "-i"],
            input=command.encode("ascii"),
            capture_output=True,
            check=False,
            timeout=15,
        )  # nosec B603 # nosemgrep
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError("Keychain write unavailable") from error
    if result.returncode != 0:
        # Do not include stdout/stderr: the batch interpreter may echo input.
        raise RuntimeError("Keychain write failed")


class MacOSKeychainCredentialStore(PlatformCredentialStore):
    """macOS user Keychain credential store."""

    def save_key(self, record_id: str, key_pem: bytes) -> None:
        slot = _validate_slot(record_id)
        _write_secret(f"{slot}_key", key_pem)
        if self.load_key(record_id) != key_pem:
            raise RuntimeError("Keychain key verification failed")

    def load_key(self, record_id: str) -> bytes | None:
        slot = _validate_slot(record_id)
        cmd = [
            _SECURITY_EXECUTABLE,
            "find-generic-password",
            "-s",
            _SERVICE_NAME,
            "-a",
            f"{slot}_key",
            "-w",
        ]
        res = subprocess.run(cmd, capture_output=True, check=False)  # nosec B603 # nosemgrep
        if res.returncode != 0:
            return None
        hex_data = res.stdout.strip().decode("utf-8")
        try:
            return bytes.fromhex(hex_data)
        except ValueError:
            return None

    def save_binding(self, record_id: str, binding: dict[str, str]) -> None:
        slot = _validate_slot(record_id)
        if any(not isinstance(k, str) or not isinstance(v, str) for k, v in binding.items()):
            raise ValueError("Invalid Keychain binding data")
        payload = json.dumps(binding, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        _write_secret(f"{slot}_binding", payload)
        if self.load_binding(record_id) != binding:
            raise RuntimeError("Keychain binding verification failed")

    def load_binding(self, record_id: str) -> dict[str, str] | None:
        slot = _validate_slot(record_id)
        cmd = [
            _SECURITY_EXECUTABLE,
            "find-generic-password",
            "-s",
            _SERVICE_NAME,
            "-a",
            f"{slot}_binding",
            "-w",
        ]
        res = subprocess.run(cmd, capture_output=True, check=False)  # nosec B603 # nosemgrep
        if res.returncode != 0:
            return None
        hex_data = res.stdout.strip().decode("utf-8")
        try:
            raw = bytes.fromhex(hex_data)
            data = json.loads(raw.decode("utf-8"))
            if isinstance(data, dict):
                return {str(k): str(v) for k, v in data.items()}
            return None
        except ValueError:
            return None

    def delete_credentials(self, record_id: str) -> bool:
        slot = _validate_slot(record_id)
        deleted = False
        for part in ("_key", "_binding"):
            cmd = [
                _SECURITY_EXECUTABLE,
                "delete-generic-password",
                "-s",
                _SERVICE_NAME,
                "-a",
                f"{slot}{part}",
            ]
            res = subprocess.run(cmd, capture_output=True, check=False)  # nosec B603 # nosemgrep
            if res.returncode == 0:
                deleted = True
        return deleted
