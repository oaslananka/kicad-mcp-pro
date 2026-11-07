"""Platform-specific secure credential storage for Cloud pairing keys and bindings.

Implements native platform secret vaults:
- Windows: Generic Credential Store via Advapi32 with user-scoped isolation.
- macOS: Apple Keychain via security service.
- Linux: Owner-private POSIX filesystem with atomic no-follow permissions.
"""

from __future__ import annotations

import os
import sys
from abc import ABC, abstractmethod
from pathlib import Path


class PlatformCredentialStore(ABC):
    """Abstract interface for user-scoped secret and binding storage."""

    @abstractmethod
    def save_key(self, record_id: str, key_pem: bytes) -> None:
        """Store private key PEM bytes for the given record ID."""

    @abstractmethod
    def load_key(self, record_id: str) -> bytes | None:
        """Load private key PEM bytes for the given record ID."""

    @abstractmethod
    def save_binding(self, record_id: str, binding: dict[str, str]) -> None:
        """Store pairing binding metadata for the given record ID."""

    @abstractmethod
    def load_binding(self, record_id: str) -> dict[str, str] | None:
        """Load pairing binding metadata for the given record ID."""

    @abstractmethod
    def delete_credentials(self, record_id: str) -> bool:
        """Delete credentials associated with record ID."""

    def __str__(self) -> str:
        return f"{self.__class__.__name__}()"

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}()"


def get_credential_store(registry_root: Path | None = None) -> PlatformCredentialStore:
    """Return the native credential store for the current operating system."""
    if os.name == "nt":
        from .windows import WindowsCredentialStore

        return WindowsCredentialStore()
    elif sys.platform == "darwin":
        from .macos import MacOSKeychainCredentialStore

        return MacOSKeychainCredentialStore()
    else:
        from .linux import LinuxCredentialStore

        return LinuxCredentialStore(registry_root=registry_root)
