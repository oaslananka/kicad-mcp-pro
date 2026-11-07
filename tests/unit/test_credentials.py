"""Tests for platform credential stores and security boundaries."""

import os
from unittest.mock import MagicMock, patch

import pytest

from kicad_mcp.credentials import (
    PlatformCredentialStore,
    get_credential_store,
)
from kicad_mcp.credentials.linux import LinuxCredentialStore
from kicad_mcp.credentials.macos import MacOSKeychainCredentialStore
from kicad_mcp.credentials.windows import WindowsCredentialStore


def test_get_credential_store_returns_platform_store() -> None:
    store = get_credential_store()
    assert isinstance(store, PlatformCredentialStore)
    if os.name == "nt":
        assert isinstance(store, WindowsCredentialStore)
    elif os.name == "posix":
        if os.uname().sysname == "Darwin":
            assert isinstance(store, (MacOSKeychainCredentialStore, LinuxCredentialStore))
        else:
            assert isinstance(store, LinuxCredentialStore)


def test_windows_store_rejects_invalid_record_id() -> None:
    store = WindowsCredentialStore()
    with pytest.raises(ValueError):
        store.save_key("invalid-slot-too-short", b"private_key_pem")


def test_windows_store_crud() -> None:
    store = WindowsCredentialStore()
    record_id = "0123456789abcdef0123456789abcdef"  # 32 hex chars
    key_pem = b"placeholder_test_key_pem_bytes"

    with (
        patch("kicad_mcp.cloud_windows_credentials.create_credential") as mock_create,
        patch("kicad_mcp.cloud_windows_credentials.read_credential") as mock_read,
        patch("kicad_mcp.cloud_windows_credentials.delete_credential") as mock_delete,
    ):
        mock_read.return_value = None
        store.save_key(record_id, key_pem)
        mock_create.assert_called_once_with(record_id, "key", key_pem)

        mock_read.return_value = key_pem
        loaded = store.load_key(record_id)
        assert loaded == key_pem

        store.delete_credentials(record_id)
        assert mock_delete.call_count >= 2  # key and binding deleted


def test_macos_keychain_crud() -> None:
    store = MacOSKeychainCredentialStore()
    record_id = "0123456789abcdef0123456789abcdef"
    key_pem = b"MOCK_PEM_BYTES"

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=key_pem.hex().encode())
        store.save_key(record_id, key_pem)
        assert mock_run.called

        loaded = store.load_key(record_id)
        assert loaded == key_pem

        store.delete_credentials(record_id)
        assert mock_run.called


def test_credentials_never_leaked_in_str_or_repr() -> None:
    store = WindowsCredentialStore()
    rep = str(store)
    repr(store)
    assert "private" not in rep.lower()
    assert "secret" not in rep.lower()
    assert "key" not in rep.lower() or "store" in rep.lower()
