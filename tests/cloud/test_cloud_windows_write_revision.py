"""Win32 content-identity checks for an approved disposable PCB fixture.

These tests inspect, never edit, a user's existing KiCad source. Every
temporary board is created by pytest and remains outside Cloud.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from kicad_mcp.cloud_readonly_boundary import OperatorProject
from kicad_mcp.cloud_write_board_revision import verify_operator_board_revision
from kicad_mcp.cloud_write_contract import LocalWriteDeniedError

WINDOWS = pytest.mark.skipif(os.name != "nt", reason="requires native Win32 handles")
DEVICE = "11111111-1111-4111-8111-111111111111"
PROJECT = "22222222-2222-4222-8222-222222222222"
PCB = b"(kicad_pcb (version 20250114) (generator pcbnew))\n"


def _board(tmp_path: Path) -> tuple[OperatorProject, Path, str]:
    folder = tmp_path / "owner KiCad"
    folder.mkdir()
    board = folder / "disposable.kicad_pcb"
    board.write_bytes(PCB)
    return (
        OperatorProject(
            device_id=DEVICE, project_id=PROJECT, directory=folder, filename_stem="disposable"
        ),
        board,
        hashlib.sha256(PCB).hexdigest(),
    )


@WINDOWS
def test_windows_verified_board_revision_reads_only_pinned_board(tmp_path: Path) -> None:
    policy, board, sha = _board(tmp_path)
    verify_operator_board_revision(policy, sha)
    assert board.read_bytes() == PCB


@WINDOWS
def test_windows_stale_revision_is_denied_without_modifying_board(tmp_path: Path) -> None:
    policy, board, sha = _board(tmp_path)
    with pytest.raises(LocalWriteDeniedError, match="request denied"):
        verify_operator_board_revision(policy, "0" * 64)
    assert board.read_bytes() == PCB
    board.write_bytes(PCB + b"new source content")
    with pytest.raises(LocalWriteDeniedError, match="request denied"):
        verify_operator_board_revision(policy, sha)
    assert board.read_bytes() == PCB + b"new source content"


@WINDOWS
def test_windows_rejected_nonlocal_or_missing_board_does_not_modify_files(tmp_path: Path) -> None:
    policy, board, sha = _board(tmp_path)
    wrong_stem = OperatorProject(
        device_id=DEVICE, project_id=PROJECT, directory=policy.directory, filename_stem="missing"
    )
    with pytest.raises(LocalWriteDeniedError, match="request denied"):
        verify_operator_board_revision(wrong_stem, sha)
    assert board.read_bytes() == PCB


@WINDOWS
def test_windows_hardlinked_board_is_not_an_approved_unique_file(tmp_path: Path) -> None:
    policy, board, sha = _board(tmp_path)
    alias = tmp_path / "alias.kicad_pcb"
    os.link(board, alias)
    try:
        with pytest.raises(LocalWriteDeniedError, match="request denied"):
            verify_operator_board_revision(policy, sha)
    finally:
        alias.unlink()
    assert board.read_bytes() == PCB


@WINDOWS
def test_windows_linked_parent_directory_is_denied(tmp_path: Path) -> None:
    policy, board, sha = _board(tmp_path)
    renamed = tmp_path / "real project"
    policy.directory.rename(renamed)
    try:
        policy.directory.symlink_to(renamed, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Windows user cannot create a directory symlink on this host")
    with pytest.raises(LocalWriteDeniedError, match="request denied"):
        verify_operator_board_revision(policy, sha)
    assert (renamed / board.name).read_bytes() == PCB


@WINDOWS
def test_windows_rejects_malformed_expected_digest_before_io(tmp_path: Path) -> None:
    policy, board, _sha = _board(tmp_path)
    for invalid in ("", "../other", "f" * 200, "G" * 64, "0" * 63):
        with pytest.raises(LocalWriteDeniedError, match="request denied"):
            verify_operator_board_revision(policy, invalid)
    assert board.read_bytes() == PCB


@WINDOWS
def test_windows_zero_byte_board_is_denied(tmp_path: Path) -> None:
    policy, board, _sha = _board(tmp_path)
    board.write_bytes(b"")
    empty_digest = hashlib.sha256(b"").hexdigest()
    with pytest.raises(LocalWriteDeniedError, match="request denied"):
        verify_operator_board_revision(policy, empty_digest)
    assert board.read_bytes() == b""


@WINDOWS
def test_windows_unavailable_native_file_handle_is_denied(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from kicad_mcp import cloud_windows_write_revision

    policy, board, digest = _board(tmp_path)
    monkeypatch.setattr(cloud_windows_write_revision, "_open_checked", lambda *_a, **_k: None)
    with pytest.raises(LocalWriteDeniedError, match="request denied"):
        verify_operator_board_revision(policy, digest)
    assert board.read_bytes() == PCB


@WINDOWS
def test_windows_rejects_posix_file_descriptor_parameter(tmp_path: Path) -> None:
    policy, board, digest = _board(tmp_path)
    with pytest.raises(LocalWriteDeniedError, match="request denied"):
        verify_operator_board_revision(policy, digest, _directory_fd=1)
    assert board.read_bytes() == PCB


@WINDOWS
def test_windows_project_digest_reader_uses_same_pinned_handle_checks(tmp_path: Path) -> None:
    from kicad_mcp.cloud_windows_write_revision import read_windows_board_revision

    policy, board, expected = _board(tmp_path)
    assert read_windows_board_revision(policy) == expected
    assert board.read_bytes() == PCB
    board.write_bytes(PCB + b"changed locally")
    assert read_windows_board_revision(policy) == hashlib.sha256(board.read_bytes()).hexdigest()


@WINDOWS
def test_windows_project_digest_reader_denies_aliased_source(tmp_path: Path) -> None:
    from kicad_mcp.cloud_windows_write_revision import read_windows_board_revision

    policy, board, _expected = _board(tmp_path)
    alias = tmp_path / "linked.kicad_pcb"
    os.link(board, alias)
    try:
        with pytest.raises(LocalWriteDeniedError, match="request denied"):
            read_windows_board_revision(policy)
    finally:
        alias.unlink()
    assert board.read_bytes() == PCB
