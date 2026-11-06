"""Read-only Windows Cloud identity binding inspection; never grants remote access."""

from __future__ import annotations

import hashlib
import json
import secrets
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

import kicad_mcp.cloud_windows_binding as binding
from kicad_mcp.cloud_pair_keys import LocalApprovalDeniedError

RECORD = "a" * 32
DEVICE = "19ee4be9-0aec-448e-9873-721ae113ec02"
OWNER = "provider|owner-42"
ORIGIN = "https://example.com"


def _material() -> tuple[bytes, dict[str, str]]:
    key = Ed25519PrivateKey.generate()
    data = key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
    public = key.public_key().public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
    return data, {
        "recordId": RECORD,
        "origin": ORIGIN,
        "ownerSub": OWNER,
        "deviceId": DEVICE,
        "fingerprint": hashlib.sha256(public).hexdigest(),
    }


def _load(
    monkeypatch: pytest.MonkeyPatch, secret: bytes, document: bytes | dict[str, Any] | None
) -> list[str]:
    records = {
        "key": secret,
        "binding": json.dumps(document, separators=(",", ":")).encode("utf-8")
        if isinstance(document, dict)
        else document,
    }
    accessed: list[str] = []

    def fake_read(record_id: str, part: str) -> bytes | None:
        assert record_id == RECORD
        accessed.append(part)
        return records[part]

    monkeypatch.setattr(binding, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(binding, "read_credential", fake_read)
    return accessed


def _inspect(**overrides: str) -> binding.WindowsLocalBindingInspection:
    params = {
        "record_id": RECORD,
        "expected_origin": ORIGIN,
        "expected_owner_sub": OWNER,
        "expected_device_id": DEVICE,
    }
    params.update(overrides)
    return binding.inspect_local_binding(**params)


def test_binding_matches_expected_owner_device_and_key_without_authorizing_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret, document = _material()
    accessed = _load(monkeypatch, secret, document)
    inspected = _inspect()
    assert inspected == binding.WindowsLocalBindingInspection(
        record_id=RECORD,
        origin=ORIGIN,
        owner_sub=OWNER,
        device_id=DEVICE,
        fingerprint=document["fingerprint"],
    )
    assert not hasattr(inspected, "private_key")
    assert accessed == ["key", "binding"]


@pytest.mark.parametrize("absent_part", ["key", "binding"])
def test_refuses_incomplete_two_part_credential(
    monkeypatch: pytest.MonkeyPatch, absent_part: str
) -> None:
    secret, document = _material()
    values = {"key": secret, "binding": json.dumps(document).encode("utf-8")}
    values[absent_part] = None

    monkeypatch.setattr(binding, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(binding, "read_credential", lambda _slot, part: values[part])
    with pytest.raises(LocalApprovalDeniedError, match="local approval denied"):
        _inspect()


@pytest.mark.parametrize("field", ["ownerSub", "origin", "deviceId", "recordId", "fingerprint"])
def test_refuses_mismatched_bound_field(monkeypatch: pytest.MonkeyPatch, field: str) -> None:
    secret, document = _material()
    document[field] = "other"
    _load(monkeypatch, secret, document)
    with pytest.raises(LocalApprovalDeniedError, match="local approval denied"):
        _inspect()


@pytest.mark.parametrize(
    "selector",
    [
        {"expected_owner_sub": "other"},
        {"expected_origin": "https://evil.example"},
        {"expected_device_id": "a8ee4be9-0aec-448e-9873-721ae113ec02"},
        {"record_id": "B" * 32},
        {"expected_origin": "https://example.com/path"},
        {"expected_origin": "https://user@example.com"},
        {"expected_owner_sub": ""},
        {"expected_device_id": "not-a-uuid"},
    ],
)
def test_refuses_invalid_or_different_selectors_without_creating_access(
    monkeypatch: pytest.MonkeyPatch, selector: dict[str, str]
) -> None:
    secret, document = _material()
    _load(monkeypatch, secret, document)
    with pytest.raises(LocalApprovalDeniedError, match="local approval denied"):
        _inspect(**selector)


@pytest.mark.parametrize(
    "alter",
    [
        lambda value: dict(value, extra="unexpected"),
        lambda value: {key: item for key, item in value.items() if key != "ownerSub"},
        lambda value: dict(value, ownerSub=42),
        lambda value: dict(value, fingerprint="B" * 64),
        lambda value: dict(value, deviceId="19ee4be9-0aec-448e-9873-721ae113ec02 "),
    ],
)
def test_refuses_corrupt_binding_schema(
    monkeypatch: pytest.MonkeyPatch, alter: Callable[[dict[str, str]], dict[str, object]]
) -> None:
    secret, document = _material()
    _load(monkeypatch, secret, alter(document))
    with pytest.raises(LocalApprovalDeniedError, match="local approval denied"):
        _inspect()


@pytest.mark.parametrize(
    "encoded",
    [
        b'{"ownerSub":"x","ownerSub":"x"}',
        b'{"ownerSub":',
        b'{"ownerSub":"\xff"}',
        b"[]",
        b"null",
    ],
)
def test_rejects_duplicate_invalid_utf8_or_nonobject_json(
    monkeypatch: pytest.MonkeyPatch, encoded: bytes
) -> None:
    secret, _ = _material()
    _load(monkeypatch, secret, encoded)
    with pytest.raises(LocalApprovalDeniedError, match="local approval denied"):
        _inspect()


def test_rejects_foreign_or_corrupt_private_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret, document = _material()
    other, _ = _material()
    for invalid in (other, b"not-a-key"):
        _load(monkeypatch, invalid, document)
        with pytest.raises(LocalApprovalDeniedError, match="local approval denied"):
            _inspect()
    assert secret != other


def test_fails_closed_on_unsupported_platform_even_with_mocked_vault(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret, document = _material()
    accessed = _load(monkeypatch, secret, document)
    monkeypatch.setattr(binding, "os", SimpleNamespace(name="posix"))
    with pytest.raises(LocalApprovalDeniedError, match="local approval denied"):
        _inspect()
    assert accessed == []


def test_credential_api_error_is_not_treated_as_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret, document = _material()
    _load(monkeypatch, secret, document)

    def deny(_slot: str, _part: str) -> bytes | None:
        raise LocalApprovalDeniedError("local approval denied")

    monkeypatch.setattr(binding, "read_credential", deny)
    with pytest.raises(LocalApprovalDeniedError, match="local approval denied"):
        _inspect()


@pytest.mark.skipif(binding.os.name != "nt", reason="Native user vault is Windows-only")
def test_real_windows_vault_readonly_binding_inspection() -> None:
    from kicad_mcp.cloud_windows_credentials import create_credential, delete_credential

    secret, document = _material()
    slot = secrets.token_hex(16)
    document["recordId"] = slot
    try:
        create_credential(slot, "key", secret)
        create_credential(slot, "binding", json.dumps(document).encode("utf-8"))
        inspected = binding.inspect_local_binding(
            record_id=slot,
            expected_origin=ORIGIN,
            expected_owner_sub=OWNER,
            expected_device_id=DEVICE,
        )
        assert inspected.fingerprint == document["fingerprint"]
    finally:
        delete_credential(slot, "binding")
        delete_credential(slot, "key")


def test_refuses_unrelated_signing_key_type(monkeypatch: pytest.MonkeyPatch) -> None:
    from cryptography.hazmat.primitives.asymmetric.ed448 import Ed448PrivateKey

    _, document = _material()
    key = Ed448PrivateKey.generate()
    other_type = key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
    _load(monkeypatch, other_type, document)
    with pytest.raises(LocalApprovalDeniedError, match="local approval denied"):
        _inspect()
