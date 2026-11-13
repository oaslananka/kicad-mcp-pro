"""Signed Cloud write -> canonical native live IPC: Windows disposable project tests.

The board is an injected KiCad-API-shaped fake; these tests are NOT proof that
the public Cloud socket or a physical KiCad GUI executed a remote edit.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from kipy.board import Board
from kipy.geometry import Angle, Vector2

from kicad_mcp.cloud_native_write_dispatch import execute_verified_signed_pcb_move
from kicad_mcp.cloud_readonly_boundary import OperatorProject, VerifiedLocalBinding
from kicad_mcp.cloud_write_contract import LocalWriteDeniedError
from kicad_mcp.pcb.transaction_lifecycle import PcbTransactionLifecycleService
from kicad_mcp.utils.units import _coord_nm

WINDOWS = pytest.mark.skipif(os.name != "nt", reason="requires pinned Windows project lock")
DEVICE = "11111111-1111-4111-8111-111111111111"
PROJECT = "22222222-2222-4222-8222-222222222222"
SESSION = "33333333-3333-4333-8333-333333333333"
REQUEST = "44444444-4444-4444-8444-444444444444"
NOW = 1_800_000_000_000
START = "(kicad_pcb (version 20250114) (generator pcbnew))\n"
PREFIX = b"kicad-cloud-signed-write-proposal-v1\x00"
PREFIX_V2 = b"kicad-cloud-signed-write-proposal-v2\x00"


class FakeBoard:
    def __init__(self, folder: Path) -> None:
        self.project = SimpleNamespace(path=str(folder))
        self.name = "disposable.kicad_pcb"
        self.reference_field = SimpleNamespace(text=SimpleNamespace(value="R1"))
        self.footprint = SimpleNamespace(
            reference_field=self.reference_field,
            position=Vector2.from_xy_mm(1, 1),
            angle=Angle.from_degrees(0),
        )
        self.contents = START
        self.undo = object()
        self.calls: list[str] = []

    def get_project(self) -> object:
        return self.project

    def get_as_string(self) -> str:
        return self.contents

    def get_footprints(self) -> list[object]:
        return [self.footprint]

    def begin_commit(self) -> object:
        self.calls.append("begin")
        return self.undo

    def update_items(self, _items: object) -> list[object]:
        self.calls.append("update")
        self.contents = START + "(footprint moved)"
        return [self.footprint]

    def push_commit(self, _undo: object, _message: str = "") -> None:
        self.calls.append("push")

    def drop_commit(self, _undo: object) -> None:
        self.calls.append("drop")
        self.contents = START
        self.footprint.position = Vector2.from_xy_mm(1, 1)


def _fixture(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    (tmp_path / "KiCadMCPPro" / "Cloud" / "write-markers").mkdir(parents=True)
    folder = tmp_path / "disposable"
    folder.mkdir()
    (folder / "disposable.kicad_pcb").write_bytes(START.encode("utf-8"))
    (folder / "disposable.kicad_pro").write_text("{}", encoding="utf-8")
    policy = OperatorProject(DEVICE, PROJECT, folder, "disposable")
    verified = VerifiedLocalBinding(
        DEVICE, PROJECT, frozenset({"pcb_move_footprint"}), SESSION, NOW + 20000
    )
    private = Ed25519PrivateKey.generate()
    board = FakeBoard(folder)

    def queue(_operation: str, callback):
        return callback()

    service = PcbTransactionLifecycleService(
        get_board=lambda: cast(Board, board),
        run_mutation=queue,
        connection_errors=(OSError,),
        get_connection_epoch=lambda: 1,
    )
    used: set[tuple[str, str]] = set()

    def consume(sid: str, rid: str) -> bool:
        token = (sid, rid)
        if token in used:
            return False
        used.add(token)
        return True

    def signed(
        *,
        reference: str = "R1",
        request_id: str = REQUEST,
        digest: str | None = None,
        version: int = 1,
        live_digest: str | None = None,
    ) -> bytes:
        command = {
            "operation": "pcb_move_footprint",
            "reference": reference,
            "xMm": 3.5,
            "yMm": 4.25,
            "rotationDeg": None,
            "expectedBoardSha256": digest or hashlib.sha256(START.encode()).hexdigest(),
        }
        if version == 2:
            command["expectedLiveBoardSha256"] = live_digest
        payload = json.dumps(
            {
                "kind": "connector.write_request",
                "version": version,
                "requestId": request_id,
                "deviceId": DEVICE,
                "projectId": PROJECT,
                "sessionId": SESSION,
                "deadlineUnixMs": NOW + 5000,
                "command": command,
            },
            separators=(",", ":"),
        ).encode("utf-8")
        from base64 import urlsafe_b64encode

        def encode(v: bytes) -> str:
            return urlsafe_b64encode(v).decode("ascii").rstrip("=")

        return json.dumps(
            {
                "kind": "connector.signed_write_proposal",
                "version": version,
                "payload": encode(payload),
                "signature": encode(
                    private.sign((PREFIX_V2 if version == 2 else PREFIX) + payload)
                ),
            },
            separators=(",", ":"),
        ).encode("utf-8")

    def execute(
        proof: bytes,
        *,
        authorized: Callable[[], bool] = lambda: True,
        cancelled: Callable[[], bool] = lambda: False,
    ) -> dict[str, object]:
        return execute_verified_signed_pcb_move(
            proof,
            issuer_key=private.public_key(),
            verified=verified,
            operator_project=policy,
            consume_once=consume,
            authorized=authorized,
            cancelled=cancelled,
            service=service,
            now_unix_ms=NOW,
        )

    return folder, board, signed, execute


@WINDOWS
def test_signed_native_move_uses_canonical_transaction_and_reports_unsaved_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    folder, board, signed, execute = _fixture(monkeypatch, tmp_path)
    original = (folder / "disposable.kicad_pcb").read_bytes()
    result = execute(signed())
    assert result == {
        "requestId": REQUEST,
        "projectId": PROJECT,
        "operation": "pcb_move_footprint",
        "nativeCommitted": True,
        "savedToDisk": False,
    }
    assert board.calls == ["begin", "update", "push"]
    assert _coord_nm(board.footprint.position, "x") == 3500000
    assert _coord_nm(board.footprint.position, "y") == 4250000
    assert (folder / "disposable.kicad_pcb").read_bytes() == original
    replay_proof = signed()
    with pytest.raises(LocalWriteDeniedError, match="request denied"):
        execute(replay_proof)
    assert board.calls == ["begin", "update", "push"], "replay must never rerun native IPC"


@WINDOWS
def test_signed_move_does_not_enter_native_transaction_for_invalid_proof_or_revision(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    folder, board, signed, execute = _fixture(monkeypatch, tmp_path)
    wrong_reference = signed(reference="R2")
    with pytest.raises(LocalWriteDeniedError):
        execute(wrong_reference)
    assert board.calls == [], "unknown footprint was denied before beginning"
    stale_revision = signed(request_id="55555555-5555-4555-8555-555555555555", digest="0" * 64)
    with pytest.raises(LocalWriteDeniedError):
        execute(stale_revision)
    assert board.calls == [], "stale on-disk revision was denied before beginning"
    assert (folder / "disposable.kicad_pcb").read_bytes() == START.encode()


@WINDOWS
def test_signed_move_revoke_before_commit_discards_without_changing_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    folder, board, signed, execute = _fixture(monkeypatch, tmp_path)
    permissions = iter([True, True, False])
    proposal = signed()

    def current_permission() -> bool:
        return next(permissions)

    with pytest.raises(LocalWriteDeniedError):
        execute(proposal, authorized=current_permission)
    assert board.calls == ["begin", "update", "drop"]
    assert (folder / "disposable.kicad_pcb").read_bytes() == START.encode()


@WINDOWS
def test_v2_separately_pins_normalized_live_and_raw_disk_board_snapshots(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    folder, board, signed, execute = _fixture(monkeypatch, tmp_path)
    board.contents = START + "(normalized-by-live-kicad)"
    live_sha = hashlib.sha256(board.contents.encode("utf-8")).hexdigest()
    disk_bytes = (folder / "disposable.kicad_pcb").read_bytes()
    proof = signed(version=2, live_digest=live_sha)
    result = execute(proof)
    assert result["nativeCommitted"] is True
    assert result["savedToDisk"] is False
    assert board.calls == ["begin", "update", "push"]
    assert (folder / "disposable.kicad_pcb").read_bytes() == disk_bytes


@WINDOWS
def test_v2_rejects_stale_live_sha_before_begin_without_mutating_disk(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    folder, board, signed, execute = _fixture(monkeypatch, tmp_path)
    board.contents = START + "(normalized-by-live-kicad)"
    stale_live_sha = "0" * 64
    proof = signed(version=2, live_digest=stale_live_sha)
    with pytest.raises(LocalWriteDeniedError, match="request denied"):
        execute(proof)
    assert board.calls == []
    assert (folder / "disposable.kicad_pcb").read_bytes() == START.encode()


@WINDOWS
def test_v1_still_rejects_different_live_and_disk_sha(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    folder, board, signed, execute = _fixture(monkeypatch, tmp_path)
    board.contents = START + "(normalized-by-live-kicad)"
    proof = signed()
    with pytest.raises(LocalWriteDeniedError, match="request denied"):
        execute(proof)
    assert board.calls == []
    assert (folder / "disposable.kicad_pcb").read_bytes() == START.encode()


@WINDOWS
def test_revision_prepare_returns_distinct_approved_disk_and_live_shas(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from kicad_mcp.cloud_native_write_dispatch import prepare_native_write_revisions

    folder, board, _signed, _execute = _fixture(monkeypatch, tmp_path)
    board.contents = START + "(kicad normalized)"
    policy = OperatorProject(DEVICE, PROJECT, folder, "disposable")
    revisions = prepare_native_write_revisions(
        policy, authorized=lambda: True, cancelled=lambda: False, get_board=lambda: board
    )
    assert revisions == {
        "expectedBoardSha256": hashlib.sha256(START.encode()).hexdigest(),
        "expectedLiveBoardSha256": hashlib.sha256(board.contents.encode()).hexdigest(),
    }
    assert revisions["expectedBoardSha256"] != revisions["expectedLiveBoardSha256"]
    assert board.calls == []


@WINDOWS
def test_revision_prepare_denies_wrong_active_board_or_revocation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from kicad_mcp.cloud_native_write_dispatch import prepare_native_write_revisions

    folder, board, _signed, _execute = _fixture(monkeypatch, tmp_path)
    policy = OperatorProject(DEVICE, PROJECT, folder, "disposable")
    board.project.path = str(tmp_path / "another owner project")
    with pytest.raises(LocalWriteDeniedError, match="request denied"):
        prepare_native_write_revisions(
            policy, authorized=lambda: True, cancelled=lambda: False, get_board=lambda: board
        )
    board.project.path = str(folder)
    permissions = iter((True, False))

    def current_permission() -> bool:
        return next(permissions)

    with pytest.raises(LocalWriteDeniedError, match="request denied"):
        prepare_native_write_revisions(
            policy, authorized=current_permission, cancelled=lambda: False, get_board=lambda: board
        )
    assert board.calls == []
    assert (folder / "disposable.kicad_pcb").read_bytes() == START.encode()


@WINDOWS
def test_revision_prepare_denies_racing_live_board_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from kicad_mcp.cloud_native_write_dispatch import prepare_native_write_revisions

    folder, board, _signed, _execute = _fixture(monkeypatch, tmp_path)
    policy = OperatorProject(DEVICE, PROJECT, folder, "disposable")
    versions = iter((START, START + "(changed while preparing)"))

    def change_during_preparation() -> str:
        return next(versions)

    board.get_as_string = change_during_preparation  # type: ignore[method-assign]
    with pytest.raises(LocalWriteDeniedError, match="request denied"):
        prepare_native_write_revisions(
            policy, authorized=lambda: True, cancelled=lambda: False, get_board=lambda: board
        )
    assert board.calls == []
    assert (folder / "disposable.kicad_pcb").read_bytes() == START.encode()
