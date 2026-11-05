"""Offline only: real KiCad IPC lifecycle with a disposable in-memory board."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from kicad_mcp.cloud_readonly_boundary import OperatorProject
from kicad_mcp.cloud_write_contract import LocalWriteDeniedError
from kicad_mcp.cloud_write_native_ipc import OfflineTrustedPcbIpcAdapter
from kicad_mcp.cloud_write_transaction_guard import (
    NativeWriteRecoveryError,
    run_offline_guarded_native_write,
)
from kicad_mcp.pcb.transaction_lifecycle import PcbTransactionLifecycleService

_DEVICE = "11111111-1111-4111-8111-111111111111"
_PROJECT = "22222222-2222-4222-8222-222222222222"
_TEXT = "(kicad_pcb (version 20240108) (generator pcbnew))\n"
_POSIX = pytest.mark.skipif(os.name != "posix", reason="requires pinned POSIX directory locks")


class Board:
    def __init__(self, project_path: Path, name: str, text: str = _TEXT) -> None:
        self.project = SimpleNamespace(path=str(project_path))
        self.name = name
        self.text = text
        self.pending: str | None = None
        self.calls: list[str] = []
        self.commit_handle = object()
        self.commit_supported = True

    def get_project(self) -> object:
        return self.project

    def get_as_string(self) -> str:
        return self.text

    def begin_commit(self) -> object | None:
        self.calls.append("begin")
        return self.commit_handle if self.commit_supported else None

    def push_commit(self, _commit: object, _message: str = "") -> None:
        self.calls.append("push")
        if self.pending is not None:
            self.text = self.pending
            self.pending = None

    def drop_commit(self, _commit: object) -> None:
        self.calls.append("drop")
        self.pending = None

    def stage_move(self) -> str:
        self.calls.append("stage")
        self.pending = self.text + "(footprint moved)"
        return "R1"

    def verified(self, result: str) -> bool:
        return result == "R1" and self.text.endswith("(footprint moved)")


def setup(tmp_path: Path) -> tuple[OperatorProject, Board, str]:
    directory = tmp_path / "disposable"
    directory.mkdir(mode=0o700)
    (directory / "test.kicad_pcb").write_text(_TEXT, encoding="utf-8")
    (directory / "test.kicad_pcb").chmod(0o600)
    (directory / "test.kicad_pro").write_text("{}", encoding="utf-8")
    policy = OperatorProject(_DEVICE, _PROJECT, directory, "test")
    board = Board(directory / "test.kicad_pro", "test.kicad_pcb")
    return policy, board, hashlib.sha256(_TEXT.encode()).hexdigest()


def adapter(
    policy: OperatorProject,
    board_ref: list[Board],
    digest: str,
) -> OfflineTrustedPcbIpcAdapter:
    def run_direct(operation: str, command: object) -> object:
        del operation
        return command()  # type: ignore[operator] - test fake queue

    service = PcbTransactionLifecycleService(
        get_board=lambda: board_ref[0],  # type: ignore[return-value] - test fake KiCad board
        run_mutation=run_direct,  # type: ignore[arg-type] - test fake command queue
        connection_errors=(OSError,),
        get_connection_epoch=lambda: 1,
    )
    return OfflineTrustedPcbIpcAdapter(
        service=service,
        policy=policy,
        expected_board_sha256=digest,
        command=lambda board: board.stage_move(),
        verifier=lambda board, result: board.verified(result),
    )


def run(
    policy: OperatorProject,
    digest: str,
    native: OfflineTrustedPcbIpcAdapter,
    *,
    authorized: object = None,
) -> None:
    owner_grant = authorized if callable(authorized) else (lambda: True)
    run_offline_guarded_native_write(
        policy,
        digest,
        authorized=owner_grant,
        cancelled=lambda: False,
        native=native,
    )


@_POSIX
def test_real_ipc_lifecycle_stages_verifies_and_pushes_one_undo_unit(tmp_path: Path) -> None:
    policy, board, digest = setup(tmp_path)
    native = adapter(policy, [board], digest)
    run(policy, digest, native)
    assert board.calls == ["begin", "stage", "push"]
    assert board.text.endswith("(footprint moved)")
    assert (policy.directory / "test.kicad_pcb").read_text(encoding="utf-8") == _TEXT


@_POSIX
@pytest.mark.parametrize(
    "wrong",
    ["different_project", "wrong_board", "dirty_snapshot", "bad_snapshot_type", "no_project"],
)
def test_wrong_live_board_never_opens_native_transaction(tmp_path: Path, wrong: str) -> None:
    policy, board, digest = setup(tmp_path)
    if wrong == "different_project":
        board.project.path = str(tmp_path / "another.kicad_pro")
    elif wrong == "wrong_board":
        board.name = "unapproved.kicad_pcb"
    elif wrong == "dirty_snapshot":
        board.text += " (unsaved-change)"
    elif wrong == "bad_snapshot_type":
        board.get_as_string = lambda: b"wrong"  # type: ignore[method-assign]
    else:
        board.get_project = lambda: None  # type: ignore[method-assign]
    with pytest.raises(LocalWriteDeniedError, match="request denied"):
        run(policy, digest, adapter(policy, [board], digest))
    assert "begin" not in board.calls


@_POSIX
def test_nontransactional_native_is_rejected_without_staging(tmp_path: Path) -> None:
    policy, board, digest = setup(tmp_path)
    board.commit_supported = False
    with pytest.raises(LocalWriteDeniedError, match="request denied"):
        run(policy, digest, adapter(policy, [board], digest))
    assert board.calls == ["begin"]


@_POSIX
def test_revoked_grant_after_stage_uses_real_verified_drop(tmp_path: Path) -> None:
    policy, board, digest = setup(tmp_path)
    count = 0

    def grant() -> bool:
        nonlocal count
        count += 1
        return count == 1

    with pytest.raises(LocalWriteDeniedError, match="request denied"):
        run(policy, digest, adapter(policy, [board], digest), authorized=grant)
    assert board.calls == ["begin", "stage", "drop"]
    assert board.text == _TEXT
    assert board.pending is None


@_POSIX
def test_active_project_switch_after_stage_never_pushes(tmp_path: Path) -> None:
    policy, board, digest = setup(tmp_path)
    current = [board]
    native = adapter(policy, current, digest)
    original_stage = board.stage_move

    def switch() -> str:
        result = original_stage()
        current[0] = Board(tmp_path / "other.kicad_pro", "other.kicad_pcb")
        return result

    board.stage_move = switch  # type: ignore[method-assign]
    with pytest.raises(NativeWriteRecoveryError, match="native recovery required"):
        run(policy, digest, native)
    assert "push" not in board.calls


@_POSIX
def test_stale_disk_revision_never_calls_native_begin(tmp_path: Path) -> None:
    policy, board, digest = setup(tmp_path)
    (policy.directory / "test.kicad_pcb").write_text("stale", encoding="utf-8")
    with pytest.raises(LocalWriteDeniedError, match="request denied"):
        run(policy, digest, adapter(policy, [board], digest))
    assert board.calls == []


@_POSIX
def test_missing_active_project_accessor_is_rejected(tmp_path: Path) -> None:
    policy, board, digest = setup(tmp_path)
    board.get_project = None  # type: ignore[method-assign]
    with pytest.raises(LocalWriteDeniedError, match="request denied"):
        run(policy, digest, adapter(policy, [board], digest))
    assert board.calls == []


@_POSIX
def test_invalid_signed_digest_is_rejected_before_native_begin(tmp_path: Path) -> None:
    policy, board, _ = setup(tmp_path)
    native = adapter(policy, [board], "not-a-sha256-digest")
    assert native.begin() is False
    assert board.calls == []


@_POSIX
def test_missing_in_memory_snapshot_method_is_rejected(tmp_path: Path) -> None:
    policy, board, digest = setup(tmp_path)
    board.get_as_string = None  # type: ignore[method-assign]
    native = adapter(policy, [board], digest)
    assert native.begin() is False
    assert board.calls == []


@_POSIX
def test_unstarted_and_repeated_native_commands_fail_closed(tmp_path: Path) -> None:
    policy, board, digest = setup(tmp_path)
    native = adapter(policy, [board], digest)
    assert native.commit() is False
    assert native.discard() is False
    with pytest.raises(LocalWriteDeniedError, match="request denied"):
        native.stage()
    assert board.calls == []
    assert native.begin() is True
    assert native.begin() is False
    assert board.calls == ["begin"]
    assert native.discard() is True
    assert board.calls == ["begin", "drop"]


@_POSIX
def test_existing_native_transaction_does_not_allow_new_begin(tmp_path: Path) -> None:
    policy, board, digest = setup(tmp_path)
    native = adapter(policy, [board], digest)
    assert native._service.begin().startswith("Transaction group started.")
    assert native.begin() is False
    assert board.calls == ["begin"]
    assert native._service.drop() == "Transaction group discarded successfully."
