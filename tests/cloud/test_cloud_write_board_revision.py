"""Offline-only owner board revision and no-follow tests."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from kicad_mcp.cloud_readonly_boundary import OperatorProject
from kicad_mcp.cloud_write_board_revision import verify_operator_board_revision
from kicad_mcp.cloud_write_contract import LocalWriteDeniedError

DEVICE = "11111111-1111-4111-8111-111111111111"
PROJECT = "22222222-2222-4222-8222-222222222222"
BOARD = b"(kicad_pcb (version 20240108) (generator pcbnew))\n"


def approved(root: Path) -> tuple[OperatorProject, Path, str]:
    directory = root / "approved"
    directory.mkdir(mode=0o700)
    file = directory / "disposable.kicad_pcb"
    file.write_bytes(BOARD)
    file.chmod(0o600)
    return (
        OperatorProject(DEVICE, PROJECT, directory, "disposable"),
        file,
        hashlib.sha256(BOARD).hexdigest(),
    )


def reject(policy: OperatorProject, digest: str) -> None:
    with pytest.raises(LocalWriteDeniedError, match="^request denied$"):
        verify_operator_board_revision(policy, digest)


def test_invalid_policy_or_fingerprint_does_not_grant_revision(tmp_path: Path) -> None:
    policy, _, digest = approved(tmp_path)
    for invalid in ("", digest.upper(), "z" * 64, digest + "00"):
        reject(policy, invalid)
    reject(OperatorProject(DEVICE, PROJECT, policy.directory, "../unsafe"), digest)
    reject(OperatorProject(DEVICE, PROJECT, Path("relative"), "disposable"), digest)


@pytest.mark.skipif(os.name != "posix", reason="requires POSIX pinned file descriptors")
def test_exact_revision_and_stale_bytes_no_mutation(tmp_path: Path) -> None:
    policy, board, digest = approved(tmp_path)
    before = board.read_bytes()
    assert verify_operator_board_revision(policy, digest) is None
    assert board.read_bytes() == before
    reject(policy, "0" * 64)
    board.write_bytes(before + b"stale")
    reject(policy, digest)
    assert board.read_bytes() == before + b"stale"


@pytest.mark.skipif(os.name != "posix", reason="requires POSIX pinned file descriptors")
def test_symlinks_hardlinks_and_permissions_fail_closed(tmp_path: Path) -> None:
    policy, board, digest = approved(tmp_path)
    board.chmod(0o666)
    reject(policy, digest)
    board.chmod(0o444)
    reject(policy, digest)
    board.chmod(0o600)
    alias = policy.directory / "other"
    os.link(board, alias)
    reject(policy, digest)
    alias.unlink()
    board.unlink()
    outside = tmp_path / "outside.kicad_pcb"
    outside.write_bytes(BOARD)
    board.symlink_to(outside)
    reject(policy, digest)
    assert outside.read_bytes() == BOARD
    board.unlink()
    board.write_bytes(BOARD)
    board.chmod(0o600)
    policy.directory.chmod(0o777)
    reject(policy, digest)


@pytest.mark.skipif(os.name != "posix", reason="requires POSIX pinned file descriptors")
def test_swapped_directory_and_missing_board_fail_closed(tmp_path: Path) -> None:
    policy, board, digest = approved(tmp_path)
    wrong = tmp_path / "alias"
    wrong.symlink_to(policy.directory, target_is_directory=True)
    reject(OperatorProject(DEVICE, PROJECT, wrong, "disposable"), digest)
    board.unlink()
    reject(policy, digest)


@pytest.mark.skipif(os.name != "posix", reason="requires POSIX pinned file descriptors")
def test_board_modified_during_hash_read_is_denied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kicad_mcp import cloud_write_board_revision

    policy, board, digest = approved(tmp_path)
    read = os.read
    changed = False

    def mutate_after_read(fd: int, size: int) -> bytes:
        nonlocal changed
        result = read(fd, size)
        if not changed:
            changed = True
            board.write_bytes(BOARD + b"interfered")
        return result

    monkeypatch.setattr(cloud_write_board_revision.os, "read", mutate_after_read)
    reject(policy, digest)
    assert changed
    assert board.read_bytes() == BOARD + b"interfered"


@pytest.mark.skipif(os.name != "posix", reason="requires POSIX pinned file descriptors")
def test_large_board_and_fifo_denied_before_content_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kicad_mcp import cloud_write_board_revision

    policy, board, digest = approved(tmp_path)
    with board.open("r+b") as handle:
        handle.truncate(cloud_write_board_revision.MAX_BOARD_BYTES + 1)

    def forbidden_read(_fd: int, _size: int) -> bytes:
        raise AssertionError("unsafe board was read")

    monkeypatch.setattr(cloud_write_board_revision.os, "read", forbidden_read)
    reject(policy, digest)
    board.unlink()
    os.mkfifo(board)
    reject(policy, digest)


@pytest.mark.skipif(os.name != "posix", reason="requires native POSIX openat no-follow")
def test_posix_pinned_revision_and_snapshot_share_exact_trusted_file(tmp_path: Path) -> None:
    from kicad_mcp.cloud_write_board_revision import (
        read_operator_board_revision,
        read_operator_board_snapshot,
    )

    policy, board, sha = approved(tmp_path)
    original = board.read_bytes()
    assert read_operator_board_revision(policy) == sha
    assert read_operator_board_snapshot(policy) == (sha, original.decode("utf-8"))
    assert board.read_bytes() == original
    board.write_bytes(original + b"new revision")
    new_sha, content = read_operator_board_snapshot(policy)
    assert new_sha == hashlib.sha256(board.read_bytes()).hexdigest()
    assert content == board.read_text()
    with pytest.raises(LocalWriteDeniedError):
        verify_operator_board_revision(policy, sha)


@pytest.mark.skipif(os.name != "posix", reason="requires native POSIX openat no-follow")
def test_posix_snapshot_rejects_symlink_hardlink_and_untrusted_permissions(tmp_path: Path) -> None:
    from kicad_mcp.cloud_write_board_revision import (
        read_operator_board_revision,
        read_operator_board_snapshot,
    )

    policy, board, _ = approved(tmp_path)

    def deny() -> None:
        for reader in (read_operator_board_revision, read_operator_board_snapshot):
            with pytest.raises(LocalWriteDeniedError, match="^request denied$"):
                reader(policy)

    board.chmod(0o666)
    deny()
    board.chmod(0o600)
    alias = policy.directory / "alias.kicad_pcb"
    os.link(board, alias)
    deny()
    alias.unlink()
    original = board.read_bytes()
    board.unlink()
    board.symlink_to(tmp_path / "outside.kicad_pcb")
    deny()
    board.unlink()
    board.write_bytes(original)
    board.chmod(0o600)
    policy.directory.chmod(0o777)
    deny()


@pytest.mark.skipif(os.name != "posix", reason="requires native POSIX openat no-follow")
def test_posix_snapshot_drops_racing_read_and_rejects_non_utf8(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kicad_mcp import cloud_write_board_revision as revision

    policy, board, _ = approved(tmp_path)
    read = os.read
    mutated = False

    def mutate_after_read(fd: int, size: int) -> bytes:
        nonlocal mutated
        result = read(fd, size)
        if not mutated:
            mutated = True
            board.write_bytes(BOARD + b"changed mid-read")
        return result

    monkeypatch.setattr(revision.os, "read", mutate_after_read)
    with pytest.raises(LocalWriteDeniedError, match="^request denied$"):
        revision.read_operator_board_snapshot(policy)
    assert mutated
    monkeypatch.undo()
    board.write_bytes(BOARD + b"\xff")
    assert (
        revision.read_operator_board_revision(policy)
        == hashlib.sha256(board.read_bytes()).hexdigest()
    )
    with pytest.raises(LocalWriteDeniedError, match="^request denied$"):
        revision.read_operator_board_snapshot(policy)
