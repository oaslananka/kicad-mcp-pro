"""One verified, owner-bound Cloud PCB move through the canonical native KiCad IPC service.

This is the device-side execution boundary, not a public Cloud route. The
caller must supply an independently pinned server issuer, a signed session
binding, the owner-selected local project, a crash-durable replay consumer
and current local authorization. It never accepts client-selected paths.
A trusted local caller may additionally request a pinned save and independent
on-disk footprint-position readback. Public Cloud WRITE is not enabled here.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, cast

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from kicad_mcp.cloud_readonly_boundary import OperatorProject, VerifiedLocalBinding
from kicad_mcp.cloud_windows_write_revision import (
    read_windows_board_revision,
    read_windows_board_snapshot,
)
from kicad_mcp.cloud_write_board_revision import MAX_BOARD_BYTES
from kicad_mcp.cloud_write_contract import LocalWriteDeniedError
from kicad_mcp.cloud_write_native_ipc import (
    OfflineTrustedPcbIpcAdapter,
    _require_approved_live_board,
)
from kicad_mcp.cloud_write_proof import verify_offline_signed_write_proof
from kicad_mcp.cloud_write_transaction_guard import run_offline_guarded_native_write
from kicad_mcp.models.common import _FootprintLike
from kicad_mcp.pcb.board_access import board_footprints
from kicad_mcp.pcb.footprint_transform import (
    RotationAttribute,
    apply_footprint_rotation,
    get_current_footprint_rotation,
    verify_footprint_rotation,
)
from kicad_mcp.utils.units import _coord_nm, mm_to_nm

if TYPE_CHECKING:
    from kipy.board import Board
    from kipy.board_types import BoardItem

    from kicad_mcp.pcb.transaction_lifecycle import PcbTransactionLifecycleService

_DENIED = "request denied"


def _footprint(board: object, reference: str) -> _FootprintLike:
    """A duplicate reference is ambiguous; never move an arbitrary first match."""
    matches = [
        candidate
        for candidate in board_footprints(board)
        if getattr(
            getattr(getattr(candidate, "reference_field", None), "text", None), "value", None
        )
        == reference
    ]
    if len(matches) != 1:
        raise LocalWriteDeniedError(_DENIED)
    return cast(_FootprintLike, matches[0])


def _live_board_sha256(board: object) -> str:
    snapshot_reader = getattr(board, "get_as_string", None)
    if not callable(snapshot_reader):
        raise LocalWriteDeniedError(_DENIED)
    snapshot = snapshot_reader()
    if not isinstance(snapshot, str):
        raise LocalWriteDeniedError(_DENIED)
    bytes_out = snapshot.encode("utf-8")
    if not 1 <= len(bytes_out) <= MAX_BOARD_BYTES:
        raise LocalWriteDeniedError(_DENIED)
    return hashlib.sha256(bytes_out).hexdigest()


def prepare_native_write_revisions(
    policy: OperatorProject,
    *,
    authorized: Callable[[], bool],
    cancelled: Callable[[], bool],
    get_board: Callable[[], object] | None = None,
) -> dict[str, str]:
    """Prepare bounded, path-free disk/live revisions for a future signed edit.

    The caller must already have checked the owner/client project grant on
    the authenticated Connector. A preparation is not permission to mutate.
    The signed v2 command must bind both returned digests; the native writer
    separately reopens/rechecks the disk file under its transaction lock.
    """
    if not callable(authorized) or not callable(cancelled):
        raise LocalWriteDeniedError(_DENIED)
    if get_board is None:
        from kicad_mcp.connection import get_board as get_current_board

        get_board = get_current_board
    try:
        if authorized() is not True or cancelled() is not False:
            raise LocalWriteDeniedError(_DENIED)
        board = get_board()
        _require_approved_live_board(board, policy)
        disk = read_windows_board_revision(policy)
        live = _live_board_sha256(board)
        current = get_board()
        _require_approved_live_board(current, policy)
        if (
            not hmac.compare_digest(disk, read_windows_board_revision(policy))
            or not hmac.compare_digest(live, _live_board_sha256(current))
            or authorized() is not True
            or cancelled() is not False
        ):
            raise LocalWriteDeniedError(_DENIED)
        return {"expectedBoardSha256": disk, "expectedLiveBoardSha256": live}
    except Exception as exc:
        raise LocalWriteDeniedError(_DENIED) from exc


def _native_move(
    service: PcbTransactionLifecycleService,
    policy: OperatorProject,
    command: dict[str, object],
) -> OfflineTrustedPcbIpcAdapter:
    # The command was parsed from the signed, version-separated contract.
    from kipy.geometry import Vector2

    reference = cast(str, command["reference"])
    x_mm = float(cast(float, command["xMm"]))
    y_mm = float(cast(float, command["yMm"]))
    rotation = cast(float | None, command["rotationDeg"])
    expected_rotation: list[tuple[RotationAttribute, float]] = []

    def stage(board: Board) -> object:
        footprint = _footprint(board, reference)
        footprint.position = Vector2.from_xy_mm(x_mm, y_mm)
        if rotation is None:
            attribute, degrees = get_current_footprint_rotation(footprint)
        else:
            attribute = apply_footprint_rotation(footprint, float(rotation))
            degrees = float(rotation)
        expected_rotation.append((attribute, degrees))
        return list(board.update_items([cast("BoardItem", footprint)]))

    def verify(board: Board, _result: object) -> bool:
        if len(expected_rotation) != 1:
            return False
        try:
            footprint = _footprint(board, reference)
            position = footprint.position
            if _coord_nm(position, "x") != mm_to_nm(x_mm) or _coord_nm(position, "y") != mm_to_nm(
                y_mm
            ):
                return False
            attribute, degrees = expected_rotation[0]
            verify_footprint_rotation(footprint, attribute, degrees)
            return True
        except Exception:
            return False

    return OfflineTrustedPcbIpcAdapter(
        service=service,
        policy=policy,
        expected_board_sha256=cast(str, command["expectedBoardSha256"]),
        expected_live_board_sha256=cast(str | None, command.get("expectedLiveBoardSha256")),
        command=stage,
        verifier=verify,
    )


def _saved_disk_move_matches(
    content: str,
    reference: str,
    command: dict[str, object],
) -> bool:
    """Check a unique persisted footprint, including requested rotation."""
    from kicad_mcp.tools.board_file import FLOAT_PATTERN, _parse_board_footprint_blocks

    entry = _parse_board_footprint_blocks(content).get(reference)
    if (
        len(re.findall(r'\(property\s+"Reference"\s+"' + re.escape(reference) + r'"', content)) != 1
        or not isinstance(entry, dict)
        or not isinstance(entry.get("x_mm"), (int, float))
        or not isinstance(entry.get("y_mm"), (int, float))
        or mm_to_nm(float(entry["x_mm"])) != mm_to_nm(float(cast(float, command["xMm"])))
        or mm_to_nm(float(entry["y_mm"])) != mm_to_nm(float(cast(float, command["yMm"])))
    ):
        return False
    rotation = command.get("rotationDeg")
    if rotation is None:
        return True
    block = entry.get("block")
    if not isinstance(block, str):
        return False
    at = re.search(
        rf"(?m)^\s*\(at\s+{FLOAT_PATTERN}\s+{FLOAT_PATTERN}(?:\s+({FLOAT_PATTERN}))?\)",
        block,
    )
    if at is None:
        return False
    actual = float(at.group(1) or "0")
    difference = (actual - float(cast(float, rotation)) + 180) % 360 - 180
    return abs(difference) <= 0.001


def _persist_native_move(
    service: PcbTransactionLifecycleService,
    policy: OperatorProject,
    command: dict[str, object],
) -> str:
    """Save only the already committed owner-bound live board, then read disk."""
    board = service.get_board()
    _require_approved_live_board(board, policy)
    reference = cast(str, command["reference"])
    x_nm = mm_to_nm(float(cast(float, command["xMm"])))
    y_nm = mm_to_nm(float(cast(float, command["yMm"])))

    def matches_target(current: object) -> bool:
        footprint = _footprint(current, reference)
        return (
            _coord_nm(footprint.position, "x") == x_nm
            and _coord_nm(footprint.position, "y") == y_nm
        )

    if not matches_target(board):
        raise LocalWriteDeniedError(_DENIED)
    save = getattr(board, "save", None)
    if not callable(save):
        raise LocalWriteDeniedError(_DENIED)
    # Reuse the canonical serial native IPC command queue for a real save.
    if service.run_mutation("pcb_save", save) is False:
        raise LocalWriteDeniedError(_DENIED)
    fresh_board = service.get_board()
    _require_approved_live_board(fresh_board, policy)
    if not matches_target(fresh_board):
        raise LocalWriteDeniedError(_DENIED)
    digest, content = read_windows_board_snapshot(policy)
    if hmac.compare_digest(digest, cast(str, command["expectedBoardSha256"])):
        raise LocalWriteDeniedError(_DENIED)

    # Verify the saved file rather than trusting KiCad's save acknowledgement.
    if not _saved_disk_move_matches(content, reference, command):
        raise LocalWriteDeniedError(_DENIED)
    return digest


def execute_verified_signed_pcb_move(
    proof: bytes,
    *,
    issuer_key: Ed25519PublicKey,
    verified: VerifiedLocalBinding,
    operator_project: OperatorProject,
    consume_once: Callable[[str, str], bool],
    authorized: Callable[[], bool],
    cancelled: Callable[[], bool],
    service: PcbTransactionLifecycleService | None = None,
    now_unix_ms: int | None = None,
    persist_to_disk: bool = False,
) -> dict[str, object]:
    """Execute exactly one authenticated native PCB move, never an arbitrary tool.

    Proof replay is consumed before any native action. Write authorization must
    remain current at both native preflight and precommit. No disk-save or
    manufacture status is implied by a successful in-memory KiCad transaction.
    """
    if not callable(authorized) or not callable(cancelled) or type(persist_to_disk) is not bool:
        raise LocalWriteDeniedError(_DENIED)
    now = time.time_ns() // 1_000_000 if now_unix_ms is None else now_unix_ms
    request = verify_offline_signed_write_proof(
        proof,
        trusted_issuer_key=issuer_key,
        verified=verified,
        operator_project=operator_project,
        now_unix_ms=now,
        consume_once=consume_once,
    )
    command = cast(dict[str, object], request["command"])
    if service is None:
        from kicad_mcp.pcb.live_edit_runtime import get_live_edit_service

        service = get_live_edit_service()
    # Resolve the actual native board and target before opening a transaction.
    # A missing or duplicated reference is an ordinary denial, never an
    # ambiguous native mutation that forces manual recovery.
    try:
        if authorized() is not True or cancelled() is not False:
            raise LocalWriteDeniedError(_DENIED)
        board = service.get_board()
        _require_approved_live_board(board, operator_project)
        _footprint(board, cast(str, command["reference"]))
    except Exception as exc:
        raise LocalWriteDeniedError(_DENIED) from exc
    adapter = _native_move(service, operator_project, command)
    disk_sha = run_offline_guarded_native_write(
        operator_project,
        cast(str, command["expectedBoardSha256"]),
        authorized=authorized,
        cancelled=cancelled,
        native=adapter,
        after_commit=(
            (lambda: _persist_native_move(service, operator_project, command))
            if persist_to_disk
            else None
        ),
    )
    return {
        "requestId": request["requestId"],
        "projectId": operator_project.project_id,
        "operation": "pcb_move_footprint",
        "nativeCommitted": True,
        "savedToDisk": disk_sha is not None,
        **({"diskBoardSha256": disk_sha} if disk_sha is not None else {}),
    }
