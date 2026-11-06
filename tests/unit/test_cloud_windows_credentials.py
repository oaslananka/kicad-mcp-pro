"""No genuine pairing, owner grant or service is created by these tests."""

from __future__ import annotations

import ctypes
import os
import secrets

import pytest

import kicad_mcp.cloud_windows_credentials as vault
from kicad_mcp.cloud_pair_keys import LocalApprovalDeniedError
from kicad_mcp.cloud_windows_credentials import (
    _target,
    create_credential,
    delete_credential,
    read_credential,
)


@pytest.mark.parametrize(
    ("record_id", "part"),
    [
        ("A" * 32, "key"),
        ("../../" + "a" * 32, "key"),
        ("a" * 31, "key"),
        ("a" * 32, "other"),
        ("a" * 32, ""),
        ("a" * 32 + "\x00", "key"),
    ],
)
def test_target_rejects_untrusted_identity(record_id: str, part: str) -> None:
    with pytest.raises(LocalApprovalDeniedError, match="local approval denied"):
        _target(record_id, part)


def test_targets_are_separate_and_pathless() -> None:
    record_id = "c" * 32
    assert _target(record_id, "key").endswith("/" + record_id + "/key")
    assert _target(record_id, "binding") != _target(record_id, "key")


def test_invalid_payload_fails_before_any_write() -> None:
    record_id = "b" * 32
    for data in (b"", b"x" * 2049, "not bytes", None):
        with pytest.raises(LocalApprovalDeniedError, match="local approval denied"):
            create_credential(record_id, "key", data)  # type: ignore[arg-type]


@pytest.mark.skipif(os.name != "nt", reason="Needs real Windows Credential Manager")
def test_native_user_credential_roundtrip_duplicate_and_revoke() -> None:
    record_id = secrets.token_hex(16)
    payload = b"isolated-test-credential-" + secrets.token_bytes(32)
    try:
        assert read_credential(record_id, "key") is None
        assert delete_credential(record_id, "key") is False
        create_credential(record_id, "key", payload)
        assert read_credential(record_id, "key") == payload
        assert read_credential(record_id, "binding") is None
        with pytest.raises(LocalApprovalDeniedError):
            create_credential(record_id, "key", b"second")
        assert read_credential(record_id, "key") == payload
    finally:
        delete_credential(record_id, "key")
        delete_credential(record_id, "binding")
    assert read_credential(record_id, "key") is None


@pytest.mark.skipif(os.name == "nt", reason="Non-Windows denial")
def test_platform_unsupported_stays_closed() -> None:
    with pytest.raises(LocalApprovalDeniedError):
        read_credential("b" * 32, "key")


class _FakeWindowsCredentialAPI:
    """In-memory Win32 ABI stand-in; never accesses the user's credential vault."""

    def __init__(self) -> None:
        self.entries: dict[str, bytes] = {}
        self.poisoned_field: tuple[str, object] | None = None
        self.references: list[object] = []

    def CredReadW(self, target: str, _kind: int, _flags: int, out: object) -> bool:  # noqa: N802
        data = self.entries.get(target)
        if data is None:
            return False
        from ctypes import wintypes

        entry = vault._CredentialW()
        entry.Type = 1
        entry.Persist = 2
        entry.TargetName = target
        entry.CredentialBlobSize = len(data)
        buffer = (wintypes.BYTE * len(data)).from_buffer_copy(data)
        entry.CredentialBlob = ctypes.cast(buffer, ctypes.POINTER(wintypes.BYTE))
        if self.poisoned_field is not None:
            setattr(entry, *self.poisoned_field)
        pointer = ctypes.pointer(entry)
        ctypes.cast(out, ctypes.POINTER(ctypes.POINTER(vault._CredentialW)))[0] = pointer
        self.references.extend((entry, buffer, pointer))
        return True

    def CredWriteW(self, arg: object, _flags: int) -> bool:  # noqa: N802
        entry = ctypes.cast(arg, ctypes.POINTER(vault._CredentialW)).contents
        self.entries[entry.TargetName] = ctypes.string_at(
            entry.CredentialBlob, entry.CredentialBlobSize
        )
        return True

    def CredDeleteW(self, target: str, _kind: int, _flags: int) -> bool:  # noqa: N802
        return self.entries.pop(target, None) is not None

    def CredFree(self, _pointer: object) -> None:  # noqa: N802
        self.references.clear()


def test_mock_vault_roundtrip_duplicate_and_revoke(monkeypatch: pytest.MonkeyPatch) -> None:
    api = _FakeWindowsCredentialAPI()
    monkeypatch.setattr(vault, "_api", lambda: api)
    monkeypatch.setattr(vault, "_last_error", lambda: 1168)
    identity = "d" * 32
    data = b"test-owner-secret"
    assert vault.read_credential(identity, "key") is None
    vault.create_credential(identity, "key", data)
    assert vault.read_credential(identity, "key") == data
    with pytest.raises(LocalApprovalDeniedError):
        vault.create_credential(identity, "key", b"replacement")
    assert vault.read_credential(identity, "binding") is None
    assert vault.delete_credential(identity, "key") is True
    assert vault.delete_credential(identity, "key") is False


@pytest.mark.parametrize(
    ("attribute", "value"),
    [
        ("Type", 2),
        ("Persist", 3),
        ("TargetName", "other-target"),
        ("CredentialBlobSize", 0),
        ("CredentialBlobSize", 2049),
    ],
)
def test_mock_vault_rejects_corrupt_metadata(
    monkeypatch: pytest.MonkeyPatch, attribute: str, value: object
) -> None:
    api = _FakeWindowsCredentialAPI()
    monkeypatch.setattr(vault, "_api", lambda: api)
    api.entries[_target("e" * 32, "key")] = b"credential"
    api.poisoned_field = (attribute, value)
    with pytest.raises(LocalApprovalDeniedError, match="local approval denied"):
        vault.read_credential("e" * 32, "key")


def test_mock_vault_fails_closed_on_credential_api_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = _FakeWindowsCredentialAPI()
    monkeypatch.setattr(vault, "_api", lambda: api)
    monkeypatch.setattr(vault, "_last_error", lambda: 5)
    with pytest.raises(LocalApprovalDeniedError, match="local approval denied"):
        vault.read_credential("f" * 32, "key")
    with pytest.raises(LocalApprovalDeniedError, match="local approval denied"):
        vault.delete_credential("f" * 32, "key")
