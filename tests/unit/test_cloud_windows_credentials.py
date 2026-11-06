"""No genuine pairing, owner grant or service is created by these tests."""

from __future__ import annotations

import os
import secrets

import pytest

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
