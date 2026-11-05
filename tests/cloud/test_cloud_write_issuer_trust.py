"""Offline-only operator-pinned Cloud write issuer trust tests."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.rsa import generate_private_key
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    PublicFormat,
)

from kicad_mcp.cloud_readonly_boundary import OperatorProject, VerifiedLocalBinding
from kicad_mcp.cloud_write_contract import LocalWriteDeniedError
from kicad_mcp.cloud_write_issuer_trust import load_pinned_write_issuer_key
from kicad_mcp.cloud_write_proof import verify_offline_signed_write_proof

NOW = 1_800_000_000_000
DEVICE = "11111111-1111-4111-8111-111111111111"
PROJECT = "22222222-2222-4222-8222-222222222222"
SESSION = "33333333-3333-4333-8333-333333333333"
PREFIX = b"kicad-cloud-signed-write-proposal-v1\x00"
GOLDEN = (
    Path(__file__).resolve().parents[1] / "fixtures" / "cloud_write_contract_v1.json"
).read_bytes()


def _material(private: Ed25519PrivateKey) -> tuple[bytes, str]:
    public = private.public_key()
    der = public.public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
    pem = public.public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)
    return pem, hashlib.sha256(der).hexdigest()


def test_unpinned_or_malformed_local_trust_fails_closed(tmp_path: Path) -> None:
    for key, pin in (
        (tmp_path / "issuer.pem", ""),
        (tmp_path / "issuer.pem", "z" * 64),
        (tmp_path / "issuer.pem", "a" * 65),
        (tmp_path / "issuer.pem", "A" * 64),
        (Path("issuer.pem"), "a" * 64),
    ):
        with pytest.raises(LocalWriteDeniedError, match="^request denied$"):
            load_pinned_write_issuer_key(key, expected_spki_sha256=pin)


@pytest.mark.skipif(os.name != "posix", reason="POSIX no-follow/openat controls required")
def test_owner_pinned_public_key_verifies_exact_cloud_write_proof(tmp_path: Path) -> None:
    private_dir = tmp_path / "approved"
    private_dir.mkdir(mode=0o700)
    keyfile = private_dir / "issuer.pem"
    signer = Ed25519PrivateKey.generate()
    public_pem, fingerprint = _material(signer)
    keyfile.write_bytes(public_pem)
    keyfile.chmod(0o600)

    trusted = load_pinned_write_issuer_key(keyfile, expected_spki_sha256=fingerprint)
    payload = GOLDEN
    from base64 import urlsafe_b64encode

    def encode(raw: bytes) -> str:
        return urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

    frame = json.dumps(
        {
            "kind": "connector.signed_write_proposal",
            "version": 1,
            "payload": encode(payload),
            "signature": encode(signer.sign(PREFIX + payload)),
        },
        separators=(",", ":"),
    ).encode()
    verified = VerifiedLocalBinding(
        device_id=DEVICE,
        project_id=PROJECT,
        session_id=SESSION,
        operations=frozenset({"pcb_move_footprint"}),
        session_expires_unix_ms=NOW + 20_000,
    )
    policy = OperatorProject(
        device_id=DEVICE,
        project_id=PROJECT,
        directory=Path("/not-accessed-by-offline-test"),
        filename_stem="not-accessed",
    )
    calls: list[tuple[str, str]] = []

    def reserve(session: str, request: str) -> bool:
        calls.append((session, request))
        return len(calls) == 1

    options = dict(
        trusted_issuer_key=trusted,
        verified=verified,
        operator_project=policy,
        now_unix_ms=NOW,
        consume_once=reserve,
    )
    assert verify_offline_signed_write_proof(frame, **options) == json.loads(payload)
    with pytest.raises(LocalWriteDeniedError, match="^request denied$"):
        verify_offline_signed_write_proof(frame, **options)
    assert len(calls) == 2


@pytest.mark.skipif(os.name != "posix", reason="POSIX no-follow/openat controls required")
def test_replacement_bad_permissions_links_and_invalid_key_are_denied(tmp_path: Path) -> None:
    private_dir = tmp_path / "approved"
    private_dir.mkdir(mode=0o700)
    keyfile = private_dir / "issuer.pem"
    signer = Ed25519PrivateKey.generate()
    pem, pin = _material(signer)
    keyfile.write_bytes(pem)
    keyfile.chmod(0o600)

    other_pem, _ = _material(Ed25519PrivateKey.generate())
    keyfile.write_bytes(other_pem)
    with pytest.raises(LocalWriteDeniedError):
        load_pinned_write_issuer_key(keyfile, expected_spki_sha256=pin)
    keyfile.write_bytes(pem)

    keyfile.chmod(0o644)
    with pytest.raises(LocalWriteDeniedError):
        load_pinned_write_issuer_key(keyfile, expected_spki_sha256=pin)
    keyfile.chmod(0o600)

    linked = private_dir / "hardlink.pem"
    os.link(keyfile, linked)
    with pytest.raises(LocalWriteDeniedError):
        load_pinned_write_issuer_key(keyfile, expected_spki_sha256=pin)
    linked.unlink()

    symlink = private_dir / "alias.pem"
    symlink.symlink_to(keyfile)
    with pytest.raises(LocalWriteDeniedError):
        load_pinned_write_issuer_key(symlink, expected_spki_sha256=pin)
    symlink.unlink()

    public_key_rsa = generate_private_key(public_exponent=65537, key_size=2048).public_key()
    keyfile.write_bytes(
        public_key_rsa.public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)
    )
    with pytest.raises(LocalWriteDeniedError):
        load_pinned_write_issuer_key(keyfile, expected_spki_sha256=pin)

    keyfile.write_bytes(b"-----BEGIN PRIVATE KEY-----\ninvalid\n")
    with pytest.raises(LocalWriteDeniedError):
        load_pinned_write_issuer_key(keyfile, expected_spki_sha256=pin)
    keyfile.write_bytes(pem + b"X" * 9000)
    with pytest.raises(LocalWriteDeniedError):
        load_pinned_write_issuer_key(keyfile, expected_spki_sha256=pin)


@pytest.mark.skipif(os.name != "posix", reason="POSIX no-follow/openat controls required")
def test_public_issuer_trust_requires_owner_private_parent(tmp_path: Path) -> None:
    approved = tmp_path / "approved"
    approved.mkdir(mode=0o700)
    private = Ed25519PrivateKey.generate()
    pem, pin = _material(private)
    keyfile = approved / "issuer.pem"
    keyfile.write_bytes(pem)
    keyfile.chmod(0o600)
    approved.chmod(0o755)
    with pytest.raises(LocalWriteDeniedError):
        load_pinned_write_issuer_key(keyfile, expected_spki_sha256=pin)
