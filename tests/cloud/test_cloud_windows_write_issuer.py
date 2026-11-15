"""Windows per-user pinned issuer identity, with no Cloud/vault mutations."""

from __future__ import annotations

import hashlib
import os

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from kicad_mcp.cloud_windows_credentials import _target
from kicad_mcp.cloud_windows_write_issuer import load_pinned_windows_write_issuer_key
from kicad_mcp.cloud_write_contract import LocalWriteDeniedError

WINDOWS = pytest.mark.skipif(os.name != "nt", reason="requires Windows owner vault")
RECORD = "1" * 32


def _issuer() -> tuple[bytes, str]:
    public = Ed25519PrivateKey.generate().public_key()
    pem = public.public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)
    der = public.public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
    return pem, hashlib.sha256(der).hexdigest()


@WINDOWS
def test_windows_issuer_loads_only_locally_pinned_ed25519_public_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kicad_mcp import cloud_windows_write_issuer

    pem, pinned = _issuer()
    calls: list[tuple[str, str]] = []

    def lookup(record: str, part: str) -> bytes:
        calls.append((record, part))
        return pem

    monkeypatch.setattr(cloud_windows_write_issuer, "read_credential", lookup)
    key = load_pinned_windows_write_issuer_key(RECORD, expected_spki_sha256=pinned)
    assert key.public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo) == pem
    assert calls == [(RECORD, "write_issuer")]
    assert _target(RECORD, "write_issuer").endswith("/" + RECORD + "/write_issuer")


@WINDOWS
def test_windows_issuer_rejects_wrong_fingerprint_and_untrusted_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kicad_mcp import cloud_windows_write_issuer

    pem, _pinned = _issuer()
    calls: list[str] = []

    def lookup(_record: str, _part: str) -> bytes:
        calls.append("called")
        return pem

    monkeypatch.setattr(cloud_windows_write_issuer, "read_credential", lookup)
    with pytest.raises(LocalWriteDeniedError, match="request denied"):
        load_pinned_windows_write_issuer_key(RECORD, expected_spki_sha256="f" * 64)
    with pytest.raises(LocalWriteDeniedError, match="request denied"):
        load_pinned_windows_write_issuer_key("../other", expected_spki_sha256="f" * 64)
    assert calls == ["called"]


@WINDOWS
@pytest.mark.parametrize("value", [None, b"", b"not a public key", b"other" * 300])
def test_windows_issuer_denies_missing_or_malformed_vault_key(
    monkeypatch: pytest.MonkeyPatch, value: bytes | None
) -> None:
    from kicad_mcp import cloud_windows_write_issuer

    monkeypatch.setattr(cloud_windows_write_issuer, "read_credential", lambda _record, _part: value)
    with pytest.raises(LocalWriteDeniedError, match="request denied"):
        load_pinned_windows_write_issuer_key(RECORD, expected_spki_sha256="f" * 64)


@WINDOWS
def test_windows_issuer_denies_wrong_algorithm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cryptography.hazmat.primitives.asymmetric.ec import SECP256R1, generate_private_key

    from kicad_mcp import cloud_windows_write_issuer

    public = generate_private_key(SECP256R1()).public_key()
    pem = public.public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)
    der = public.public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
    monkeypatch.setattr(cloud_windows_write_issuer, "read_credential", lambda _record, _part: pem)
    fingerprint = hashlib.sha256(der).hexdigest()
    with pytest.raises(LocalWriteDeniedError, match="request denied"):
        load_pinned_windows_write_issuer_key(RECORD, expected_spki_sha256=fingerprint)


@WINDOWS
def test_owner_can_pin_independently_verified_public_issuer_in_windows_vault(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kicad_mcp import cloud_windows_write_issuer as issuer

    pem, sha256 = _issuer()
    store: dict[str, bytes] = {}
    writes: list[str] = []

    def read(_record: str, part: str) -> bytes | None:
        return store.get(part)

    def create(_record: str, part: str, value: bytes) -> None:
        assert part not in store
        writes.append(part)
        store[part] = value

    monkeypatch.setattr(issuer, "read_credential", read)
    monkeypatch.setattr(issuer, "create_credential", create)
    issuer.trust_owner_windows_write_issuer(RECORD, pem, expected_spki_sha256=sha256)
    assert writes == ["write_issuer", "write_issuer_pin"]
    assert store["write_issuer"] == pem
    assert store["write_issuer_pin"] == sha256.encode("ascii")
    assert (
        issuer.load_pinned_windows_write_issuer_key(RECORD).public_bytes(
            Encoding.PEM, PublicFormat.SubjectPublicKeyInfo
        )
        == pem
    )
    issuer.trust_owner_windows_write_issuer(RECORD, pem, expected_spki_sha256=sha256)
    assert len(writes) == 2


@WINDOWS
def test_owner_write_issuer_rejects_wrong_sha_without_creating_any_vault_items(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kicad_mcp import cloud_windows_write_issuer as issuer

    pem, _sha256 = _issuer()
    writes: list[str] = []
    monkeypatch.setattr(issuer, "read_credential", lambda *_: None)
    monkeypatch.setattr(issuer, "create_credential", lambda *_args: writes.append("write"))
    with pytest.raises(LocalWriteDeniedError, match="request denied"):
        issuer.trust_owner_windows_write_issuer(RECORD, pem, expected_spki_sha256="f" * 64)
    assert writes == []


@WINDOWS
def test_owner_write_issuer_blocks_partial_or_different_saved_pin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kicad_mcp import cloud_windows_write_issuer as issuer

    pem, sha256 = _issuer()
    writes: list[str] = []
    monkeypatch.setattr(
        issuer,
        "read_credential",
        lambda _record, part: pem if part == "write_issuer" else None,
    )
    monkeypatch.setattr(issuer, "create_credential", lambda *_: writes.append("write"))
    with pytest.raises(LocalWriteDeniedError):
        issuer.trust_owner_windows_write_issuer(RECORD, pem, expected_spki_sha256=sha256)
    assert writes == []


@WINDOWS
def test_owner_write_pin_second_vault_write_failure_rolls_back_public_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kicad_mcp import cloud_windows_write_issuer as issuer

    pem, sha256 = _issuer()
    stored: dict[str, bytes] = {}
    removed: list[str] = []

    monkeypatch.setattr(
        issuer,
        "read_credential",
        lambda _record, part: stored.get(part),
    )

    def write(_record: str, part: str, value: bytes) -> None:
        if part == "write_issuer_pin":
            raise OSError("simulated credential store failure")
        stored[part] = value

    def delete(_record: str, part: str) -> bool:
        removed.append(part)
        stored.pop(part, None)
        return True

    monkeypatch.setattr(issuer, "create_credential", write)
    monkeypatch.setattr(issuer, "delete_credential", delete)
    with pytest.raises(LocalWriteDeniedError):
        issuer.trust_owner_windows_write_issuer(RECORD, pem, expected_spki_sha256=sha256)
    assert stored == {}
    assert removed == ["write_issuer"]


@WINDOWS
def test_load_without_pinned_sha_is_denied_without_reading_private_issuer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kicad_mcp import cloud_windows_write_issuer as issuer

    calls: list[str] = []

    def read(_record: str, part: str) -> bytes | None:
        calls.append(part)
        return None

    monkeypatch.setattr(issuer, "read_credential", read)
    with pytest.raises(LocalWriteDeniedError):
        issuer.load_pinned_windows_write_issuer_key(RECORD)
    assert calls == ["write_issuer_pin"]


@WINDOWS
def test_trusted_issuer_rejects_pem_parser_failure_and_noncanonical_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kicad_mcp import cloud_windows_write_issuer as issuer

    pem, sha256 = _issuer()
    malformed = b"-----BEGIN PUBLIC KEY-----\n" + b"A" * 90
    with pytest.raises(LocalWriteDeniedError):
        issuer.trust_owner_windows_write_issuer(RECORD, malformed, expected_spki_sha256=sha256)

    fake_key = Ed25519PrivateKey.generate().public_key()
    monkeypatch.setattr(issuer, "load_pem_public_key", lambda _pem: fake_key)
    with pytest.raises(LocalWriteDeniedError):
        issuer.trust_owner_windows_write_issuer(RECORD, pem + b"\n", expected_spki_sha256=sha256)
