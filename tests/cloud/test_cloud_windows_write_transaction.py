"""Win32 native transaction guard tests on a disposable PCB fixture only.

The native adapter is deliberately a stub: a passing unit test does not
claim that a real KiCad GUI or Cloud socket has accepted a mutation.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from kicad_mcp.cloud_readonly_boundary import OperatorProject
from kicad_mcp.cloud_windows_write_lock import lock_windows_operator_project
from kicad_mcp.cloud_write_contract import LocalWriteDeniedError
from kicad_mcp.cloud_write_transaction_guard import (
    NativeWriteRecoveryError,
    run_offline_guarded_native_write,
)

WINDOWS = pytest.mark.skipif(os.name != "nt", reason="native Windows CreateFileW required")
DEVICE = "11111111-1111-4111-8111-111111111111"
PROJECT = "22222222-2222-4222-8222-222222222222"
PCB = b"(kicad_pcb (version 20250114) (generator pcbnew))\n"


class NativeStub:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.commit_result = True

    def begin(self) -> bool:
        self.calls.append("begin")
        return True

    def stage(self) -> None:
        self.calls.append("stage")

    def commit(self) -> bool:
        self.calls.append("commit")
        return self.commit_result

    def discard(self) -> bool:
        self.calls.append("discard")
        return True


def _approved(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[OperatorProject, Path, str]:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    marker = tmp_path / "KiCadMCPPro" / "Cloud" / "write-markers"
    marker.mkdir(parents=True)
    folder = tmp_path / "disposable board"
    folder.mkdir()
    board = folder / "disposable.kicad_pcb"
    board.write_bytes(PCB)
    policy = OperatorProject(DEVICE, PROJECT, folder, "disposable")
    return policy, board, hashlib.sha256(PCB).hexdigest()


@WINDOWS
def test_windows_offline_transaction_guard_stages_commits_with_current_board(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    policy, board, digest = _approved(monkeypatch, tmp_path)
    native = NativeStub()
    run_offline_guarded_native_write(
        policy, digest, authorized=lambda: True, cancelled=lambda: False, native=native
    )
    assert native.calls == ["begin", "stage", "commit"]
    assert board.read_bytes() == PCB


@WINDOWS
def test_windows_grant_revoked_between_stage_and_commit_discards(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    policy, board, digest = _approved(monkeypatch, tmp_path)
    native = NativeStub()
    grants = iter((True, False))

    with pytest.raises(LocalWriteDeniedError, match="request denied"):
        run_offline_guarded_native_write(
            policy,
            digest,
            authorized=lambda: next(grants),
            cancelled=lambda: False,
            native=native,
        )
    assert native.calls == ["begin", "stage", "discard"]
    assert board.read_bytes() == PCB


@WINDOWS
def test_windows_stale_board_rejected_before_native_begin(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    policy, board, _digest = _approved(monkeypatch, tmp_path)
    native = NativeStub()
    with pytest.raises(LocalWriteDeniedError, match="request denied"):
        run_offline_guarded_native_write(
            policy, "0" * 64, authorized=lambda: True, cancelled=lambda: False, native=native
        )
    assert native.calls == []
    assert board.read_bytes() == PCB


@WINDOWS
def test_windows_native_commit_uncertainty_stops_without_unsafe_retry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    policy, board, digest = _approved(monkeypatch, tmp_path)
    native = NativeStub()
    native.commit_result = False
    with pytest.raises(NativeWriteRecoveryError, match="native recovery required"):
        run_offline_guarded_native_write(
            policy, digest, authorized=lambda: True, cancelled=lambda: False, native=native
        )
    assert native.calls == ["begin", "stage", "commit"]
    assert board.read_bytes() == PCB


@WINDOWS
def test_windows_second_concurrent_project_lock_is_denied(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    policy, board, _digest = _approved(monkeypatch, tmp_path)
    with lock_windows_operator_project(policy.directory, policy.filename_stem):
        other_writer = lock_windows_operator_project(policy.directory, policy.filename_stem)
        with pytest.raises(LocalWriteDeniedError, match="request denied"):
            other_writer.__enter__()
    assert board.read_bytes() == PCB


@WINDOWS
def test_windows_preexisting_nonempty_lock_is_denied(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from kicad_mcp.cloud_windows_write_marker import default_windows_write_marker_directory

    policy, board, _digest = _approved(monkeypatch, tmp_path)
    private = default_windows_write_marker_directory()
    assert private is not None
    name = hashlib.sha256(
        (str(policy.directory).casefold() + "\x00" + policy.filename_stem).encode()
    ).hexdigest()
    lockfile = private / (name + ".lock")
    lockfile.write_bytes(b"foreign user content")
    second = lock_windows_operator_project(policy.directory, policy.filename_stem)
    with pytest.raises(LocalWriteDeniedError, match="request denied"):
        second.__enter__()
    assert lockfile.read_bytes() == b"foreign user content"
    assert board.read_bytes() == PCB


@WINDOWS
def test_windows_lock_rejects_untrusted_relative_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    policy, board, _digest = _approved(monkeypatch, tmp_path)
    second = lock_windows_operator_project(Path("relative/board"), policy.filename_stem)
    with pytest.raises(LocalWriteDeniedError, match="request denied"):
        second.__enter__()
    assert board.read_bytes() == PCB
