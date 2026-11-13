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
