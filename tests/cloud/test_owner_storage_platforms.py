"""Owner credential storage boundaries, simulated Windows/macOS and native POSIX.

Simulated platform tests exercise isolated functions on Linux CI; they do not
constitute packaged Windows ACL or physical macOS Keychain acceptance.
"""

from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.rsa import generate_private_key
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat

from kicad_mcp import cloud_pair, cloud_pair_keys, credentials
from kicad_mcp.credentials import linux, macos, windows

RECORD_ID = "a" * 32
DEVICE_ID = "11111111-1111-4111-8111-111111111111"
FINGERPRINT = "f" * 64
ORIGIN = "https://cloud.example"


@dataclass(frozen=True)
class _FakeProcessResult:
    returncode: int
    stdout: bytes


class OSNamed:
    """Change only module-local OS selection without changing global pathlib."""

    def __init__(self, name: str) -> None:
        self.name = name

    def __getattr__(self, name: str) -> object:
        return getattr(os, name)


@pytest.fixture
def simulated_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cloud_pair_keys, "os", OSNamed("nt"))
    monkeypatch.setattr(cloud_pair, "os", OSNamed("nt"))


def _pem() -> bytes:
    return Ed25519PrivateKey.generate().private_bytes(
        Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()
    )


def _binding() -> dict[str, str]:
    return {
        "origin": ORIGIN,
        "deviceId": DEVICE_ID,
        "fingerprint": FINGERPRINT,
        "ownerSub": "owner",
    }


def test_windows_key_reopens_existing_and_never_overwrites(
    simulated_windows: None, tmp_path: Path
) -> None:
    path = tmp_path / "device.pem"
    key = cloud_pair._load_or_create(path)
    assert path.read_bytes() == key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
    reopened = cloud_pair._load_or_create(path)
    assert reopened.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()) == (
        key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
    )
    with pytest.raises(cloud_pair.CloudPairingError):
        cloud_pair._create_private_key(path)
    assert isinstance(cloud_pair_keys._load_owner_key(path), Ed25519PrivateKey)


@pytest.mark.parametrize("payload", [b"", b"invalid pem"])
def test_windows_key_rejects_missing_or_invalid_pem(
    simulated_windows: None, tmp_path: Path, payload: bytes
) -> None:
    keyfile = tmp_path / "device.pem"
    if payload:
        keyfile.write_bytes(payload)
    with pytest.raises(cloud_pair_keys.LocalApprovalDeniedError):
        cloud_pair_keys._load_owner_key(keyfile)
    if payload:
        with pytest.raises(cloud_pair.CloudPairingError):
            cloud_pair._load_or_create(keyfile)


def test_windows_key_rejects_non_ed25519_algorithm(simulated_windows: None, tmp_path: Path) -> None:
    keyfile = tmp_path / "device.pem"
    keyfile.write_bytes(
        generate_private_key(public_exponent=65537, key_size=2048).private_bytes(
            Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()
        )
    )
    with pytest.raises(cloud_pair_keys.LocalApprovalDeniedError):
        cloud_pair_keys._load_owner_key(keyfile)


def test_windows_key_rejects_symlink_without_changing_original(
    simulated_windows: None, tmp_path: Path
) -> None:
    original = tmp_path / "original.pem"
    expected = _pem()
    original.write_bytes(expected)
    alias = tmp_path / "alias.pem"
    try:
        alias.symlink_to(original)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks not available in this local test environment")
    with pytest.raises(cloud_pair.CloudPairingError):
        cloud_pair._load_or_create(alias)
    assert original.read_bytes() == expected


def test_windows_pair_binding_round_trip_and_reenrollment_denied(
    simulated_windows: None, tmp_path: Path
) -> None:
    keyfile = tmp_path / "device.pem"
    keyfile.write_bytes(_pem())
    cloud_pair._require_unused_binding_path(keyfile)
    cloud_pair_keys._save_owner_binding(
        keyfile,
        origin=ORIGIN,
        device_id=DEVICE_ID,
        fingerprint=FINGERPRINT,
        owner_sub="owner",
    )
    assert cloud_pair_keys._read_owner_binding(keyfile) == _binding()
    with pytest.raises(cloud_pair_keys.LocalApprovalDeniedError):
        cloud_pair_keys._save_owner_binding(
            keyfile, origin=ORIGIN, device_id=DEVICE_ID, fingerprint=FINGERPRINT
        )
    with pytest.raises(cloud_pair.CloudPairingError):
        cloud_pair._require_unused_binding_path(keyfile)


@pytest.mark.parametrize(
    "payload",
    [
        b"{}",
        b'{"origin":"https://a","origin":"https://b"}',
        json.dumps({**_binding(), "fingerprint": "broken"}).encode(),
        json.dumps({**_binding(), "deviceId": "invalid"}).encode(),
        json.dumps({**_binding(), "ownerSub": ""}).encode(),
        b"bad json",
    ],
)
def test_windows_binding_rejects_invalid_record(
    simulated_windows: None, tmp_path: Path, payload: bytes
) -> None:
    (tmp_path / "device.pem.cloud-binding-v1.json").write_bytes(payload)
    with pytest.raises(cloud_pair_keys.LocalApprovalDeniedError):
        cloud_pair_keys._read_owner_binding(tmp_path / "device.pem")


@pytest.mark.parametrize(
    "origin,device,fingerprint,owner",
    [
        ("http://wrong.example", DEVICE_ID, FINGERPRINT, None),
        (ORIGIN, "not-a-uuid", FINGERPRINT, None),
        (ORIGIN, DEVICE_ID, "not-a-fingerprint", None),
        (ORIGIN, DEVICE_ID, FINGERPRINT, ""),
    ],
)
def test_windows_binding_rejects_bad_identity_at_write(
    simulated_windows: None,
    tmp_path: Path,
    origin: str,
    device: str,
    fingerprint: str,
    owner: str | None,
) -> None:
    with pytest.raises(cloud_pair_keys.LocalApprovalDeniedError):
        cloud_pair_keys._save_owner_binding(
            tmp_path / "device.pem",
            origin=origin,
            device_id=device,
            fingerprint=fingerprint,
            owner_sub=owner,
        )
    assert not list(tmp_path.glob("*.cloud-binding-v1.json"))


def test_windows_private_json_atomic_replacement_and_bounds(
    simulated_windows: None, tmp_path: Path
) -> None:
    name = "state.json"
    cloud_pair_keys._write_private_json(tmp_path, name, {"state": "pending"})
    assert cloud_pair_keys._read_private_json(tmp_path, name) == {"state": "pending"}
    cloud_pair_keys._write_private_json(tmp_path, name, {"state": "approved"})
    assert cloud_pair_keys._read_private_json(tmp_path, name) == {"state": "approved"}
    with pytest.raises(cloud_pair_keys.LocalApprovalDeniedError):
        cloud_pair_keys._write_private_json(tmp_path, name, {"large": "x" * 2500})
    assert not list(tmp_path.glob("*.tmp"))
    assert cloud_pair_keys._read_private_json(tmp_path, name) == {"state": "approved"}


@pytest.mark.parametrize("payload", [b"", b"[]", b'{"x":1,"x":2}', b"not-json"])
def test_windows_private_json_denies_malformed_content(
    simulated_windows: None, tmp_path: Path, payload: bytes
) -> None:
    (tmp_path / "state.json").write_bytes(payload)
    with pytest.raises(cloud_pair_keys.LocalApprovalDeniedError):
        cloud_pair_keys._read_private_json(tmp_path, "state.json")


def test_windows_private_json_failed_replace_preserves_old_record(
    simulated_windows: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cloud_pair_keys._write_private_json(tmp_path, "state.json", {"value": "safe"})
    previous_replace = Path.replace

    def refuse(self: Path, target: Path) -> Path:
        if self.name.endswith(".tmp"):
            raise OSError("cannot replace")
        return previous_replace(self, target)

    monkeypatch.setattr(Path, "replace", refuse)
    with pytest.raises(cloud_pair_keys.LocalApprovalDeniedError):
        cloud_pair_keys._write_private_json(tmp_path, "state.json", {"value": "unsafe"})
    assert cloud_pair_keys._read_private_json(tmp_path, "state.json") == {"value": "safe"}
    assert not list(tmp_path.glob("*.tmp"))


def test_windows_private_json_denies_missing_document(
    simulated_windows: None, tmp_path: Path
) -> None:
    with pytest.raises(cloud_pair_keys.LocalApprovalDeniedError):
        cloud_pair_keys._read_private_json(tmp_path, "missing.json")
    assert cloud_pair_keys._current_uid() == 0


@pytest.mark.parametrize(
    "returncode,payload,expected",
    [(0, b"4142\n", b"AB"), (0, b"not-hex", None), (44, b"", None)],
)
def test_macos_keychain_load_key_returns_only_valid_hex(
    monkeypatch: pytest.MonkeyPatch, returncode: int, payload: bytes, expected: bytes | None
) -> None:
    commands: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs: object) -> _FakeProcessResult:
        commands.append(cmd)
        assert kwargs == {"capture_output": True, "check": False}
        return _FakeProcessResult(returncode, payload)

    monkeypatch.setattr(macos, "subprocess", SimpleNamespace(run=fake_run))
    assert macos.MacOSKeychainCredentialStore().load_key(RECORD_ID) == expected
    assert commands == [
        [
            "/usr/bin/security",
            "find-generic-password",
            "-s",
            "KiCadMCPPro",
            "-a",
            RECORD_ID + "_key",
            "-w",
        ]
    ]


@pytest.mark.parametrize(
    "payload,expected",
    [
        (
            json.dumps({"owner": "example", "version": 1}).encode().hex().encode(),
            {"owner": "example", "version": "1"},
        ),
        (b"not-hex", None),
        (json.dumps(["not-a-binding"]).encode().hex().encode(), None),
        (b"7b", None),
    ],
)
def test_macos_keychain_binding_rejects_invalid_format(
    monkeypatch: pytest.MonkeyPatch,
    payload: bytes,
    expected: dict[str, str] | None,
) -> None:
    commands: list[list[str]] = []

    def fake_run(cmd: list[str], **_kwargs: object) -> _FakeProcessResult:
        commands.append(cmd)
        return _FakeProcessResult(0, payload)

    monkeypatch.setattr(macos, "subprocess", SimpleNamespace(run=fake_run))
    assert macos.MacOSKeychainCredentialStore().load_binding(RECORD_ID) == expected
    assert commands[0][-2:] == [RECORD_ID + "_binding", "-w"]


def test_macos_keychain_missing_record_and_disabled_writes(monkeypatch: pytest.MonkeyPatch) -> None:
    commands: list[list[str]] = []

    def missing(cmd: list[str], **_kwargs: object) -> _FakeProcessResult:
        commands.append(cmd)
        return _FakeProcessResult(44, b"")

    monkeypatch.setattr(macos, "subprocess", SimpleNamespace(run=missing))
    store = macos.MacOSKeychainCredentialStore()
    assert store.load_binding(RECORD_ID) is None
    assert store.delete_credentials(RECORD_ID) is False
    assert len(commands) == 3
    with pytest.raises(RuntimeError, match="unavailable"):
        store.save_key(RECORD_ID, b"secret")
    with pytest.raises(RuntimeError, match="unavailable"):
        store.save_binding(RECORD_ID, _binding())
    with pytest.raises(ValueError):
        store.load_binding("../unsafe")


def test_macos_keychain_delete_only_own_aliases(monkeypatch: pytest.MonkeyPatch) -> None:
    commands: list[list[str]] = []

    def fake_run(cmd: list[str], **_kwargs: object) -> _FakeProcessResult:
        commands.append(cmd)
        return _FakeProcessResult(0 if cmd[-1].endswith("_binding") else 44, b"")

    monkeypatch.setattr(macos, "subprocess", SimpleNamespace(run=fake_run))
    assert macos.MacOSKeychainCredentialStore().delete_credentials(RECORD_ID)
    assert [cmd[-1] for cmd in commands] == [
        RECORD_ID + "_key",
        RECORD_ID + "_binding",
    ]


def test_windows_credential_manager_round_trip_and_delete(monkeypatch: pytest.MonkeyPatch) -> None:
    stored: dict[tuple[str, str], bytes] = {}
    delete_calls: list[tuple[str, str]] = []

    def create(rec: str, kind: str, data: bytes) -> None:
        stored[(rec, kind)] = data

    def read(rec: str, kind: str) -> bytes | None:
        return stored.get((rec, kind))

    def delete(rec: str, kind: str) -> bool:
        delete_calls.append((rec, kind))
        return stored.pop((rec, kind), None) is not None

    monkeypatch.setattr(
        windows,
        "win_cred",
        SimpleNamespace(
            create_credential=create,
            read_credential=read,
            delete_credential=delete,
            _RECORD_ID=windows.win_cred._RECORD_ID,
        ),
    )
    store = windows.WindowsCredentialStore()
    assert store.load_binding(RECORD_ID) is None
    store.save_key(RECORD_ID, b"private key")
    store.save_binding(RECORD_ID, _binding())
    assert store.load_key(RECORD_ID) == b"private key"
    assert store.load_binding(RECORD_ID) == _binding()
    assert store.delete_credentials(RECORD_ID)
    assert delete_calls == [(RECORD_ID, "key"), (RECORD_ID, "binding")]
    assert store.delete_credentials(RECORD_ID) is False
    with pytest.raises(ValueError):
        store.save_binding("../unsafe", _binding())


def test_windows_credential_manager_rejects_non_mapping_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(windows.win_cred, "read_credential", lambda *_: b'["not-a-binding"]')
    assert windows.WindowsCredentialStore().load_binding(RECORD_ID) is None


def test_platform_credential_factory_selects_owner_scope(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(credentials, "os", OSNamed("nt"))
    assert isinstance(credentials.get_credential_store(), windows.WindowsCredentialStore)
    monkeypatch.setattr(credentials, "os", OSNamed("posix"))
    monkeypatch.setattr(credentials, "sys", SimpleNamespace(platform="darwin"))
    assert isinstance(credentials.get_credential_store(), macos.MacOSKeychainCredentialStore)
    monkeypatch.setattr(credentials, "sys", SimpleNamespace(platform="linux"))
    store = credentials.get_credential_store(registry_root=tmp_path)
    assert isinstance(store, linux.LinuxCredentialStore)
    assert store.root == tmp_path


@pytest.mark.skipif(os.name != "posix", reason="Real POSIX file modes required")
def test_linux_private_credential_round_trip_and_revocation(tmp_path: Path) -> None:
    store = linux.LinuxCredentialStore(registry_root=tmp_path / "registry")
    assert store.load_key(RECORD_ID) is None
    assert store.load_binding(RECORD_ID) is None
    assert store.delete_credentials(RECORD_ID) is False
    key = _pem()
    store.save_key(RECORD_ID, key)
    keyfile = store.root / "keys" / f"{RECORD_ID}.pem"
    assert stat.S_IMODE(keyfile.stat().st_mode) == 0o600
    assert stat.S_IMODE(keyfile.parent.stat().st_mode) == 0o700
    assert store.load_key(RECORD_ID) == key
    store.save_binding(RECORD_ID, _binding())
    assert store.load_binding(RECORD_ID) == _binding()
    assert store.delete_credentials(RECORD_ID)
    assert not keyfile.exists()
    assert not (keyfile.parent / f"{keyfile.name}.cloud-binding-v1.json").exists()
    assert store.delete_credentials(RECORD_ID) is False


@pytest.mark.skipif(os.name != "posix", reason="Real POSIX file modes required")
def test_linux_binding_rejects_reenrollment_and_tampering(tmp_path: Path) -> None:
    store = linux.LinuxCredentialStore(registry_root=tmp_path / "registry")
    store.save_key(RECORD_ID, _pem())
    store.save_binding(RECORD_ID, _binding())
    with pytest.raises(cloud_pair_keys.LocalApprovalDeniedError):
        store.save_binding(RECORD_ID, _binding())
    assert store.load_binding(RECORD_ID) == _binding()
    path = store.root / "keys" / f"{RECORD_ID}.pem.cloud-binding-v1.json"
    path.write_text('{"origin":"https://a","origin":"https://b"}', encoding="utf-8")
    assert store.load_binding(RECORD_ID) is None
    assert store.delete_credentials(RECORD_ID)
