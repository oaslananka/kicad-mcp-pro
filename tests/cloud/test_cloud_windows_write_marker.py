"""Real Win32 atomically exclusive local Cloud-write proof replay tests.

These tests create only disposable marker files under pytest tmp_path and
never start KiCad, connect Cloud, or invoke a native PCB mutation.
"""

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from kicad_mcp.cloud_windows_write_marker import default_windows_write_marker_directory
from kicad_mcp.cloud_write_marker import LocalWriteMarker

WINDOWS = pytest.mark.skipif(os.name != "nt", reason="requires native Windows CreateFileW")
SESSION = "33333333-3333-4333-8333-333333333333"
REQUEST = "44444444-4444-4444-8444-444444444444"


def _approved_directory(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    directory = tmp_path / "KiCadMCPPro" / "Cloud" / "write-markers"
    directory.mkdir(parents=True)
    assert default_windows_write_marker_directory() == directory
    return directory


@WINDOWS
def test_windows_marker_survives_restarts_and_blocks_replay(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    directory = _approved_directory(monkeypatch, tmp_path)
    store = LocalWriteMarker(directory)
    assert store.consume_once(SESSION, REQUEST) is True
    assert LocalWriteMarker(directory).consume_once(SESSION, REQUEST) is False
    assert (
        LocalWriteMarker(directory).consume_once("55555555-5555-4555-8555-555555555555", REQUEST)
        is False
    )
    path = directory / (REQUEST + ".used")
    assert path.read_bytes() == (SESSION + "\n").encode("ascii")
    assert len(list(directory.iterdir())) == 1


@WINDOWS
def test_windows_marker_concurrent_claim_has_only_one_winner(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    directory = _approved_directory(monkeypatch, tmp_path)
    with ThreadPoolExecutor(max_workers=12) as executor:
        results = list(
            executor.map(
                lambda _: LocalWriteMarker(directory).consume_once(SESSION, REQUEST), range(36)
            )
        )
    assert results.count(True) == 1
    assert results.count(False) == 35
    assert len(list(directory.iterdir())) == 1


@WINDOWS
def test_windows_marker_rejects_untrusted_path_and_missing_private_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    expected = default_windows_write_marker_directory()
    assert expected is not None
    assert LocalWriteMarker(expected).consume_once(SESSION, REQUEST) is False
    outsider = tmp_path / "attacker-picked"
    outsider.mkdir()
    assert LocalWriteMarker(outsider).consume_once(SESSION, REQUEST) is False
    assert not (outsider / (REQUEST + ".used")).exists()
    assert not expected.exists()


@WINDOWS
def test_windows_marker_fsync_failure_is_denied_and_non_replayable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    directory = _approved_directory(monkeypatch, tmp_path)
    original = os.fsync

    def fail(_: int) -> None:
        raise OSError("simulated disk flush failure")

    monkeypatch.setattr(os, "fsync", fail)
    assert LocalWriteMarker(directory).consume_once(SESSION, REQUEST) is False
    monkeypatch.setattr(os, "fsync", original)
    assert LocalWriteMarker(directory).consume_once(SESSION, REQUEST) is False
    assert (directory / (REQUEST + ".used")).exists()


@WINDOWS
def test_windows_marker_is_usable_by_signed_write_proof_verifier(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import base64

    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from kicad_mcp.cloud_readonly_boundary import OperatorProject, VerifiedLocalBinding
    from kicad_mcp.cloud_write_contract import LocalWriteDeniedError
    from kicad_mcp.cloud_write_proof import verify_offline_signed_write_proof

    directory = _approved_directory(monkeypatch, tmp_path)
    proof_fixture = (
        Path(__file__).resolve().parents[1] / "fixtures" / "cloud_write_contract_v1.json"
    ).read_bytes()
    command = json.loads(proof_fixture)
    key = Ed25519PrivateKey.generate()

    def encoded(raw: bytes) -> str:
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

    proof = json.dumps(
        {
            "kind": "connector.signed_write_proposal",
            "version": 1,
            "payload": encoded(proof_fixture),
            "signature": encoded(
                key.sign(b"kicad-cloud-signed-write-proposal-v1\x00" + proof_fixture)
            ),
        },
        separators=(",", ":"),
    ).encode("utf-8")
    binding = VerifiedLocalBinding(
        device_id=command["deviceId"],
        project_id=command["projectId"],
        session_id=command["sessionId"],
        operations=frozenset({"pcb_move_footprint"}),
        session_expires_unix_ms=1_800_000_020_000,
    )
    local = OperatorProject(
        device_id=command["deviceId"],
        project_id=command["projectId"],
        directory=tmp_path,
        filename_stem="disposable",
    )

    def verify() -> dict[str, object]:
        return verify_offline_signed_write_proof(
            proof,
            trusted_issuer_key=key.public_key(),
            verified=binding,
            operator_project=local,
            now_unix_ms=1_800_000_000_000,
            consume_once=LocalWriteMarker(directory).consume_once,
        )

    assert verify() == command
    with pytest.raises(LocalWriteDeniedError, match="request denied"):
        verify()
    assert len(list(directory.iterdir())) == 1


@WINDOWS
def test_windows_existing_marker_cannot_be_overwritten(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    directory = _approved_directory(monkeypatch, tmp_path)
    target = directory / (REQUEST + ".used")
    target.write_bytes(b"OTHER_SESSION_KEEP_PRIVATE")
    assert LocalWriteMarker(directory).consume_once(SESSION, REQUEST) is False
    assert target.read_bytes() == b"OTHER_SESSION_KEEP_PRIVATE"


@WINDOWS
def test_windows_symlinked_marker_directory_is_rejected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    approved = _approved_directory(monkeypatch, tmp_path)
    alternate = tmp_path / "untrusted"
    alternate.mkdir()
    approved.rmdir()
    try:
        approved.symlink_to(alternate, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Windows local policy prohibits creating a symlink")
    assert LocalWriteMarker(approved).consume_once(SESSION, REQUEST) is False
    assert not (alternate / (REQUEST + ".used")).exists()


@WINDOWS
def test_windows_missing_user_application_data_is_denied(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    assert default_windows_write_marker_directory() is None
    assert LocalWriteMarker(tmp_path).consume_once(SESSION, REQUEST) is False


@WINDOWS
def test_windows_short_marker_write_consumes_request_without_success(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    directory = _approved_directory(monkeypatch, tmp_path)
    original_write = os.write
    monkeypatch.setattr(os, "write", lambda _fd, payload: len(payload) - 1)
    assert LocalWriteMarker(directory).consume_once(SESSION, REQUEST) is False
    monkeypatch.setattr(os, "write", original_write)
    assert LocalWriteMarker(directory).consume_once(SESSION, REQUEST) is False


@WINDOWS
def test_windows_marker_handle_conversion_failure_denies_replay(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import msvcrt

    directory = _approved_directory(monkeypatch, tmp_path)

    def denied(_handle: int, _flags: int) -> int:
        raise OSError("simulated CRT failure")

    monkeypatch.setattr(msvcrt, "open_osfhandle", denied)
    assert LocalWriteMarker(directory).consume_once(SESSION, REQUEST) is False
    assert (directory / (REQUEST + ".used")).is_file()


@pytest.mark.skipif(os.name == "nt", reason="POSIX-only negative import contract")
def test_windows_marker_default_does_not_select_posix_path() -> None:
    assert default_windows_write_marker_directory() is None
