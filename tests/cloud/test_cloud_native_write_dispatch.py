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
        *, reference: str = "R1", request_id: str = REQUEST, digest: str | None = None
    ) -> bytes:
        command = {
            "operation": "pcb_move_footprint",
            "reference": reference,
            "xMm": 3.5,
            "yMm": 4.25,
            "rotationDeg": None,
            "expectedBoardSha256": digest or hashlib.sha256(START.encode()).hexdigest(),
        }
        payload = json.dumps(
            {
                "kind": "connector.write_request",
                "version": 1,
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
                "version": 1,
                "payload": encode(payload),
                "signature": encode(private.sign(PREFIX + payload)),
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
    with pytest.raises(LocalWriteDeniedError, match="request denied"):
        execute(signed())
    assert board.calls == ["begin", "update", "push"], "replay must never rerun native IPC"


@WINDOWS
def test_signed_move_does_not_enter_native_transaction_for_invalid_proof_or_revision(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    folder, board, signed, execute = _fixture(monkeypatch, tmp_path)
    with pytest.raises(LocalWriteDeniedError):
        execute(signed(reference="R2"))
    assert board.calls == [], "unknown footprint was denied before beginning"
    with pytest.raises(LocalWriteDeniedError):
        execute(signed(request_id="55555555-5555-4555-8555-555555555555", digest="0" * 64))
    assert board.calls == [], "stale on-disk revision was denied before beginning"
    assert (folder / "disposable.kicad_pcb").read_bytes() == START.encode()


@WINDOWS
def test_signed_move_revoke_before_commit_discards_without_changing_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    folder, board, signed, execute = _fixture(monkeypatch, tmp_path)
    permissions = iter([True, True, False])
    with pytest.raises(LocalWriteDeniedError):
        execute(signed(), authorized=lambda: next(permissions))
    assert board.calls == ["begin", "update", "drop"]
    assert (folder / "disposable.kicad_pcb").read_bytes() == START.encode()
