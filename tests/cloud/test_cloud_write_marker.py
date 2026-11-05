"""Offline durable one-shot write proof reservations (never native execution)."""

from __future__ import annotations

import base64
import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from kicad_mcp.cloud_readonly_boundary import OperatorProject, VerifiedLocalBinding
from kicad_mcp.cloud_write_contract import LocalWriteDeniedError
from kicad_mcp.cloud_write_marker import LocalWriteMarker
from kicad_mcp.cloud_write_proof import verify_offline_signed_write_proof

NOW = 1_800_000_000_000
DEVICE = "11111111-1111-4111-8111-111111111111"
PROJECT = "22222222-2222-4222-8222-222222222222"
SESSION = "33333333-3333-4333-8333-333333333333"
REQUEST = "44444444-4444-4444-8444-444444444444"
PREFIX = b"kicad-cloud-signed-write-proposal-v1\x00"
GOLDEN = (
    Path(__file__).resolve().parents[1] / "fixtures" / "cloud_write_contract_v1.json"
).read_bytes()


def _directory(root: Path) -> Path:
    root.mkdir(mode=0o700)
    return root


def test_invalid_identifiers_cannot_create_write_markers(tmp_path: Path) -> None:
    store = LocalWriteMarker(tmp_path / "not-created")
    for request in ("", "../escape", REQUEST.upper(), "a" * 200, "not-a-uuid"):
        assert store.consume_once(SESSION, request) is False
    assert store.consume_once("bad-session", REQUEST) is False
    assert LocalWriteMarker(Path("relative")).consume_once(SESSION, REQUEST) is False
    assert not (tmp_path / "not-created").exists()


@pytest.mark.skipif(os.name != "posix", reason="requires POSIX private-directory and O_EXCL")
def test_marker_is_unique_and_persists_across_restarts(tmp_path: Path) -> None:
    directory = _directory(tmp_path / "approved")
    first = LocalWriteMarker(directory)
    assert first.consume_once(SESSION, REQUEST) is True
    assert LocalWriteMarker(directory).consume_once(SESSION, REQUEST) is False
    assert first.consume_once(str(uuid4()), REQUEST) is False
    assert first.consume_once(SESSION, str(uuid4())) is True
    assert len(list(directory.iterdir())) == 2
    path = directory / (REQUEST + ".used")
    assert path.read_bytes() == SESSION.encode("ascii") + b"\n"
    assert path.stat().st_mode & 0o077 == 0


@pytest.mark.skipif(os.name != "posix", reason="requires POSIX private-directory and O_EXCL")
def test_parallel_marker_reservation_one_winner(tmp_path: Path) -> None:
    directory = _directory(tmp_path / "approved")
    with ThreadPoolExecutor(max_workers=8) as pool:
        decisions = list(
            pool.map(
                lambda _: LocalWriteMarker(directory).consume_once(SESSION, REQUEST),
                range(24),
            )
        )
    assert decisions.count(True) == 1
    assert decisions.count(False) == 23
    assert len(list(directory.iterdir())) == 1


@pytest.mark.skipif(os.name != "posix", reason="requires POSIX private-directory and O_EXCL")
def test_bad_directory_and_preexisting_symlink_fail_closed(tmp_path: Path) -> None:
    absent = LocalWriteMarker(tmp_path / "absent")
    assert absent.consume_once(SESSION, REQUEST) is False
    insecure = _directory(tmp_path / "insecure")
    insecure.chmod(0o755)
    assert LocalWriteMarker(insecure).consume_once(SESSION, REQUEST) is False

    directory = _directory(tmp_path / "approved")
    alias = tmp_path / "alias"
    alias.symlink_to(directory, target_is_directory=True)
    assert LocalWriteMarker(alias).consume_once(SESSION, REQUEST) is False
    target = tmp_path / "protected"
    target.write_text("protected", encoding="utf-8")
    (directory / (REQUEST + ".used")).symlink_to(target)
    assert LocalWriteMarker(directory).consume_once(SESSION, REQUEST) is False
    assert target.read_text(encoding="utf-8") == "protected"


@pytest.mark.skipif(os.name != "posix", reason="requires POSIX fsync")
def test_fsync_failure_is_denied_and_marker_is_not_reusable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = _directory(tmp_path / "approved")
    original = os.fsync

    def fail(_: int) -> None:
        raise OSError("simulated persistence failure")

    monkeypatch.setattr(os, "fsync", fail)
    assert LocalWriteMarker(directory).consume_once(SESSION, REQUEST) is False
    monkeypatch.setattr(os, "fsync", original)
    assert LocalWriteMarker(directory).consume_once(SESSION, REQUEST) is False
    assert len(list(directory.iterdir())) == 1


@pytest.mark.skipif(os.name != "posix", reason="requires POSIX private-directory and O_EXCL")
def test_signed_proof_replay_denied_after_new_store_instance(tmp_path: Path) -> None:
    directory = _directory(tmp_path / "approved")
    private = Ed25519PrivateKey.generate()

    def encode(raw: bytes) -> str:
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

    frame = json.dumps(
        {
            "kind": "connector.signed_write_proposal",
            "version": 1,
            "payload": encode(GOLDEN),
            "signature": encode(private.sign(PREFIX + GOLDEN)),
        },
        separators=(",", ":"),
    ).encode("utf-8")
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
        directory=Path("/not-used-offline"),
        filename_stem="not-used",
    )

    def run(store: LocalWriteMarker) -> dict[str, object]:
        return verify_offline_signed_write_proof(
            frame,
            trusted_issuer_key=private.public_key(),
            verified=verified,
            operator_project=policy,
            now_unix_ms=NOW,
            consume_once=store.consume_once,
        )

    assert run(LocalWriteMarker(directory)) == json.loads(GOLDEN)
    with pytest.raises(LocalWriteDeniedError, match="^request denied$"):
        run(LocalWriteMarker(directory))


@pytest.mark.skipif(os.name != "posix", reason="requires POSIX pinned directory handles")
def test_parent_swap_after_directory_pin_cannot_redirect_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kicad_mcp import cloud_write_marker

    trusted = _directory(tmp_path / "trusted")
    decoy = _directory(tmp_path / "decoy")
    original = cloud_write_marker._open_owner_private_dir

    def replace_after_open(filename: Path) -> int:
        descriptor = original(filename)
        trusted.rename(tmp_path / "pinned-trusted")
        trusted.symlink_to(decoy, target_is_directory=True)
        return descriptor

    monkeypatch.setattr(cloud_write_marker, "_open_owner_private_dir", replace_after_open)
    assert LocalWriteMarker(trusted).consume_once(SESSION, REQUEST) is True
    assert (tmp_path / "pinned-trusted" / (REQUEST + ".used")).is_file()
    assert not (decoy / (REQUEST + ".used")).exists()


@pytest.mark.skipif(os.name != "posix", reason="requires POSIX atomic file creation")
def test_partial_record_write_fails_closed_and_never_reuses_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = _directory(tmp_path / "approved")
    original_write = os.write
    monkeypatch.setattr(os, "write", lambda fd, data: original_write(fd, data[:1]))
    assert LocalWriteMarker(directory).consume_once(SESSION, REQUEST) is False
    monkeypatch.setattr(os, "write", original_write)
    assert LocalWriteMarker(directory).consume_once(SESSION, REQUEST) is False
    assert len(list(directory.iterdir())) == 1
