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
    binding = {"owner": "alice", "project": "Kart T?rk?e"}
    stored: dict[str, bytes] = {}
    calls: list[list[str]] = []

    def fake_run(command: list[str], **kwargs: object) -> MagicMock:
        calls.append(command)
        if command == ["/usr/bin/security", "-i"]:
            # Secret is in private stdin only, never in visible argv.
            batch = kwargs["input"]
            assert isinstance(batch, bytes)
            assert batch.startswith(b"add-generic-password -U -s KiCadMCPPro -a ")
            assert batch.endswith(b"\nquit\n")
            parts = batch.splitlines()[0].split(b" ")
            account = parts[5].decode("ascii")
            payload = bytes.fromhex(parts[7].decode("ascii"))
            stored[account] = payload
            return MagicMock(returncode=0, stdout=b"")
        account = command[command.index("-a") + 1]
        if command[1] == "find-generic-password":
            data = stored.get(account)
            return MagicMock(
                returncode=0 if data is not None else 44,
                stdout=data.hex().encode() if data else b"",
            )
        if command[1] == "delete-generic-password":
            return MagicMock(returncode=0 if stored.pop(account, None) else 44, stdout=b"")
        raise AssertionError(command)

    with patch("subprocess.run", side_effect=fake_run):
        store.save_key(record_id, key_pem)
        store.save_binding(record_id, binding)
        assert store.load_key(record_id) == key_pem
        assert store.load_binding(record_id) == binding
        assert store.delete_credentials(record_id)
        assert store.load_key(record_id) is None
    assert calls[0] == ["/usr/bin/security", "-i"]
    assert all("MOCK_PEM" not in " ".join(command) for command in calls)


def test_macos_keychain_rejects_invalid_or_unverifiable_writes() -> None:
    store = MacOSKeychainCredentialStore()
    record_id = "0123456789abcdef0123456789abcdef"
    with patch("subprocess.run") as run:
        with pytest.raises(ValueError):
            store.save_key("../escaped", b"secret")
        with pytest.raises(ValueError):
            store.save_key(record_id, b"")
        with pytest.raises(ValueError):
            store.save_binding(record_id, {"owner": 3})  # type: ignore[dict-item]
        run.assert_not_called()
        run.return_value = MagicMock(returncode=0, stdout=b"")
        with pytest.raises(RuntimeError, match="verification"):
            store.save_key(record_id, b"secret")
        assert run.call_args_list[0].args[0] == ["/usr/bin/security", "-i"]
        assert b"736563726574" in run.call_args_list[0].kwargs["input"]
        run.reset_mock()
        run.return_value = MagicMock(returncode=1, stdout=b"secret echoed", stderr=b"secret")
        with pytest.raises(RuntimeError, match="write failed") as error:
            store.save_key(record_id, b"secret")
        assert "secret" not in str(error.value)


def test_credentials_never_leaked_in_str_or_repr() -> None:
    store = WindowsCredentialStore()
    rep = str(store)
    repr(store)
    assert "private" not in rep.lower()
    assert "secret" not in rep.lower()
    assert "key" not in rep.lower() or "store" in rep.lower()
