"""Non-authoritative Windows project reference regression and native vault tests."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
from collections.abc import Callable
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

import kicad_mcp.cloud_windows_binding as owner_binding
import kicad_mcp.cloud_windows_project_record as project
from kicad_mcp.cloud_pair_keys import LocalApprovalDeniedError
from kicad_mcp.cloud_windows_credentials import _target

RECORD = "a" * 32
REGISTRATION = "b" * 32
ORIGIN = "https://example.com"
OWNER = "provider|owner-42"
DEVICE = "19ee4be9-0aec-448e-9873-721ae113ec02"
PROJECT = "29ee4be9-0aec-448e-9873-721ae113ec02"
STEM = "demo_board"


def _material() -> tuple[bytes, dict[str, str], dict[str, str]]:
    key = Ed25519PrivateKey.generate()
    private = key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
    public = key.public_key().public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
    fingerprint = hashlib.sha256(public).hexdigest()
    binding = {
        "recordId": RECORD,
        "origin": ORIGIN,
        "ownerSub": OWNER,
        "deviceId": DEVICE,
        "fingerprint": fingerprint,
    }
    registration = {
        "registrationId": REGISTRATION,
        "recordId": RECORD,
        "origin": ORIGIN,
        "ownerSub": OWNER,
        "deviceId": DEVICE,
        "fingerprint": fingerprint,
        "projectId": PROJECT,
        "filenameStem": STEM,
    }
    return private, binding, registration


@pytest.fixture
def credential_data(
    monkeypatch: pytest.MonkeyPatch,
) -> dict[tuple[str, str], bytes]:
    private, binding, registration = _material()
    data: dict[tuple[str, str], bytes] = {
        (RECORD, "key"): private,
        (RECORD, "binding"): json.dumps(binding).encode("utf-8"),
        (REGISTRATION, "registration"): json.dumps(registration).encode("utf-8"),
    }

    def read(record_id: str, part: str) -> bytes | None:
        return data.get((record_id, part))

    monkeypatch.setattr(owner_binding, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(project, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(owner_binding, "read_credential", read)
    monkeypatch.setattr(project, "read_credential", read)
    return data


def _inspect(**overrides: str) -> project.WindowsLocalProjectReference:
    selectors = {
        "registration_id": REGISTRATION,
        "record_id": RECORD,
        "expected_origin": ORIGIN,
        "expected_owner_sub": OWNER,
        "expected_device_id": DEVICE,
        "expected_project_id": PROJECT,
        "expected_filename_stem": STEM,
    }
    selectors.update(overrides)
    return project.inspect_project_reference(**selectors)


def _edit_registration(
    data: dict[tuple[str, str], bytes],
    alter: Callable[[dict[str, str]], dict[str, object]],
) -> None:
    raw = data[(REGISTRATION, "registration")]
    document = json.loads(raw)
    data[(REGISTRATION, "registration")] = json.dumps(alter(document)).encode("utf-8")


def test_exact_bound_project_reference_never_grants_access(
    credential_data: dict[tuple[str, str], bytes],
) -> None:
    result = _inspect()
    assert result == project.WindowsLocalProjectReference(
        registration_id=REGISTRATION,
        record_id=RECORD,
        origin=ORIGIN,
        owner_sub=OWNER,
        device_id=DEVICE,
        project_id=PROJECT,
        filename_stem=STEM,
        fingerprint=json.loads(credential_data[(REGISTRATION, "registration")])["fingerprint"],
    )
    assert not hasattr(result, "private_key")
    assert not hasattr(result, "project_directory")
    assert not hasattr(result, "authorized")
    assert not hasattr(result, "enabled")
    assert _target(REGISTRATION, "registration").endswith("/registration")


@pytest.mark.parametrize(
    ("slot", "part"),
    [(RECORD, "key"), (RECORD, "binding"), (REGISTRATION, "registration")],
)
def test_missing_part_never_falls_back_to_another_project(
    credential_data: dict[tuple[str, str], bytes], slot: str, part: str
) -> None:
    credential_data.pop((slot, part))
    with pytest.raises(LocalApprovalDeniedError, match="local approval denied"):
        _inspect()


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("registrationId", "c" * 32),
        ("recordId", "d" * 32),
        ("origin", "https://attacker.example"),
        ("ownerSub", "different"),
        ("deviceId", "39ee4be9-0aec-448e-9873-721ae113ec02"),
        ("fingerprint", "f" * 64),
        ("projectId", "49ee4be9-0aec-448e-9873-721ae113ec02"),
        ("filenameStem", "wrong_board"),
    ],
)
def test_rejects_mismatch_with_independently_selected_identity(
    credential_data: dict[tuple[str, str], bytes], key: str, value: str
) -> None:
    _edit_registration(credential_data, lambda data: dict(data, **{key: value}))
    with pytest.raises(LocalApprovalDeniedError, match="local approval denied"):
        _inspect()


@pytest.mark.parametrize(
    "extra", ["directory", "permissions", "allowed", "credential", "projectPath"]
)
def test_rejects_path_or_permission_fields(
    credential_data: dict[tuple[str, str], bytes], extra: str
) -> None:
    _edit_registration(credential_data, lambda data: dict(data, **{extra: "value"}))
    with pytest.raises(LocalApprovalDeniedError, match="local approval denied"):
        _inspect()


@pytest.mark.parametrize(
    "selector",
    [
        {"registration_id": "A" * 32},
        {"registration_id": RECORD},
        {"record_id": "d" * 32},
        {"expected_origin": "https://other.example"},
        {"expected_owner_sub": "other"},
        {"expected_device_id": "39ee4be9-0aec-448e-9873-721ae113ec02"},
        {"expected_project_id": "49ee4be9-0aec-448e-9873-721ae113ec02"},
        {"expected_project_id": "../../escape"},
        {"expected_filename_stem": "../escape"},
        {"expected_filename_stem": "bad/name"},
        {"expected_filename_stem": ""},
        {"expected_filename_stem": "Z" * 81},
    ],
)
def test_rejects_untrusted_selectors(
    credential_data: dict[tuple[str, str], bytes], selector: dict[str, str]
) -> None:
    with pytest.raises(LocalApprovalDeniedError, match="local approval denied"):
        _inspect(**selector)


@pytest.mark.parametrize(
    "raw",
    [
        b"{}",
        b"[]",
        b"null",
        b'{"registrationId":"a","registrationId":"b"}',
        b'{"projectId":"\xff"}',
        b'{"projectId":',
        b"x" * 2049,
        b"",
    ],
)
def test_rejects_malformed_duplicate_or_oversized_registry_blob(
    credential_data: dict[tuple[str, str], bytes], raw: bytes
) -> None:
    credential_data[(REGISTRATION, "registration")] = raw
    with pytest.raises(LocalApprovalDeniedError, match="local approval denied"):
        _inspect()


@pytest.mark.parametrize("missing", ["projectId", "ownerSub", "filenameStem"])
def test_rejects_missing_required_metadata(
    credential_data: dict[tuple[str, str], bytes], missing: str
) -> None:
    _edit_registration(
        credential_data, lambda data: {key: value for key, value in data.items() if key != missing}
    )
    with pytest.raises(LocalApprovalDeniedError, match="local approval denied"):
        _inspect()


def test_rejects_nontext_metadata(credential_data: dict[tuple[str, str], bytes]) -> None:
    _edit_registration(credential_data, lambda data: dict(data, projectId=42))
    with pytest.raises(LocalApprovalDeniedError, match="local approval denied"):
        _inspect()


def test_rejects_foreign_private_key_even_when_project_metadata_matches(
    credential_data: dict[tuple[str, str], bytes],
) -> None:
    credential_data[(RECORD, "key")] = Ed25519PrivateKey.generate().private_bytes(
        Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()
    )
    with pytest.raises(LocalApprovalDeniedError, match="local approval denied"):
        _inspect()


def test_registration_vault_error_is_not_interpreted_as_absent(
    monkeypatch: pytest.MonkeyPatch,
    credential_data: dict[tuple[str, str], bytes],
) -> None:
    def reject(_slot: str, _part: str) -> bytes | None:
        raise LocalApprovalDeniedError("local approval denied")

    monkeypatch.setattr(project, "read_credential", reject)
    with pytest.raises(LocalApprovalDeniedError, match="local approval denied"):
        _inspect()


def test_unsupported_os_refuses_before_reading_credential(
    monkeypatch: pytest.MonkeyPatch,
    credential_data: dict[tuple[str, str], bytes],
) -> None:
    monkeypatch.setattr(project, "os", SimpleNamespace(name="posix"))
    with pytest.raises(LocalApprovalDeniedError, match="local approval denied"):
        _inspect()


@pytest.mark.skipif(os.name != "nt", reason="Needs native Windows user vault")
def test_native_ephemeral_project_reference_read_only_roundtrip() -> None:
    from kicad_mcp.cloud_windows_credentials import create_credential, delete_credential

    private, bound, registration = _material()
    key_slot, project_slot = secrets.token_hex(16), secrets.token_hex(16)
    bound["recordId"] = key_slot
    registration["recordId"] = key_slot
    registration["registrationId"] = project_slot
    try:
        create_credential(key_slot, "key", private)
        create_credential(key_slot, "binding", json.dumps(bound).encode("utf-8"))
        create_credential(project_slot, "registration", json.dumps(registration).encode("utf-8"))
        result = project.inspect_project_reference(
            registration_id=project_slot,
            record_id=key_slot,
            expected_origin=ORIGIN,
            expected_owner_sub=OWNER,
            expected_device_id=DEVICE,
            expected_project_id=PROJECT,
            expected_filename_stem=STEM,
        )
        assert result.fingerprint == bound["fingerprint"]
        assert not hasattr(result, "project_directory")
        assert delete_credential(project_slot, "registration")
        with pytest.raises(LocalApprovalDeniedError, match="local approval denied"):
            project.inspect_project_reference(
                registration_id=project_slot,
                record_id=key_slot,
                expected_origin=ORIGIN,
                expected_owner_sub=OWNER,
                expected_device_id=DEVICE,
                expected_project_id=PROJECT,
                expected_filename_stem=STEM,
            )
    finally:
        delete_credential(project_slot, "registration")
        delete_credential(key_slot, "binding")
        delete_credential(key_slot, "key")
