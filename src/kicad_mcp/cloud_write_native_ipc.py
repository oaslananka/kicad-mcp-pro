"""Offline-only binding of reviewed PCB mutations to the canonical KiCad IPC lifecycle.

No Connector route or public write tool constructs this adapter. An authorized
native integration must provide a fixed, reviewed command and verifier, not
untrusted Cloud-supplied Python callables. A live in-memory snapshot must
match the on-disk signed SHA exactly; serialization differences fail closed.
"""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from kicad_mcp.cloud_readonly_boundary import OperatorProject
from kicad_mcp.cloud_write_board_revision import MAX_BOARD_BYTES
from kicad_mcp.cloud_write_contract import LocalWriteDeniedError
from kicad_mcp.pcb.transaction_lifecycle import PcbTransactionLifecycleService

if TYPE_CHECKING:
    from kipy.board import Board

_DENIED = "request denied"
_BEGIN = "Transaction group started. Use pcb_push_commit to apply or pcb_drop_commit to discard."
_PUSH = "Transaction group committed successfully."
_DROP = "Transaction group discarded successfully."


def _require_approved_live_board(board: object, policy: OperatorProject) -> tuple[str, str]:
    """Bind only the explicit operator project, never a Cloud-supplied path."""
    if (
        not isinstance(policy, OperatorProject)
        or not isinstance(policy.directory, Path)
        or not policy.directory.is_absolute()
        or not isinstance(policy.filename_stem, str)
    ):
        raise LocalWriteDeniedError(_DENIED)
    get_project = getattr(board, "get_project", None)
    if not callable(get_project):
        raise LocalWriteDeniedError(_DENIED)
    actual_path = getattr(get_project(), "path", None)
    actual_name = getattr(board, "name", None)
    approved = policy.directory / (policy.filename_stem + ".kicad_pro")
    if (
        not isinstance(actual_path, str)
        or not isinstance(actual_name, str)
        or not Path(actual_path).is_absolute()
        or ".." in Path(actual_path).parts
        or actual_path != str(approved)
        or actual_name != policy.filename_stem + ".kicad_pcb"
    ):
        raise LocalWriteDeniedError(_DENIED)
    return actual_path, actual_name


def _require_saved_live_snapshot(board: object, expected: str) -> None:
    """A dirty/normalized KiCad snapshot is never silently accepted."""
    if not isinstance(expected, str) or len(expected) != 64:
        raise LocalWriteDeniedError(_DENIED)
    get_snapshot = getattr(board, "get_as_string", None)
    if not callable(get_snapshot):
        raise LocalWriteDeniedError(_DENIED)
    snapshot = get_snapshot()
    if not isinstance(snapshot, str):
        raise LocalWriteDeniedError(_DENIED)
    contents = snapshot.encode("utf-8")
    if not 1 <= len(contents) <= MAX_BOARD_BYTES or not hmac.compare_digest(
        hashlib.sha256(contents).hexdigest(), expected
    ):
        raise LocalWriteDeniedError(_DENIED)


class OfflineTrustedPcbIpcAdapter:
    """Adapter for one owner-approved, pre-validated offline PCB operation.

    A successful native push is an in-memory KiCad undo unit, not a saved PCB
    file. The caller must separately enforce one-use signed grants, transport,
    and project/session revocation. No live entrypoint is enabled here.
    """

    def __init__(
        self,
        *,
        service: PcbTransactionLifecycleService,
        policy: OperatorProject,
        expected_board_sha256: str,
        command: Callable[[Board], object],
        verifier: Callable[[Board, object], bool],
    ) -> None:
        self._service = service
        self._policy = policy
        self._expected = expected_board_sha256
        self._command = command
        self._verifier = verifier
        self._started = False
        self._staged = False
        self._identity: tuple[str, str] | None = None

    def _current_board(self, *, compare_bytes: bool) -> None:
        """Reject a different project, board, or dirty/unsynced live snapshot."""
        try:
            board = self._service.get_board()
            identity = _require_approved_live_board(board, self._policy)
            if self._identity is not None and identity != self._identity:
                raise LocalWriteDeniedError(_DENIED)
            if compare_bytes:
                _require_saved_live_snapshot(board, self._expected)
            self._identity = identity
        except Exception as exc:
            raise LocalWriteDeniedError(_DENIED) from exc

    def begin(self) -> bool:
        if self._started or self._staged:
            return False
        try:
            self._current_board(compare_bytes=True)
        except LocalWriteDeniedError:
            # No native begin was attempted; an identity/snapshot mismatch
            # is a clean preflight denial, not an ambiguous IPC mutation.
            return False
        state = self._service.status_payload()
        if state.get("state") != "idle" or state.get("recovery_required") is not False:
            return False
        response = self._service.begin()
        self._started = response == _BEGIN
        if self._started and self._service.status_payload().get("state") != "active":
            # A claimed begin without a valid active transaction is ambiguous.
            raise RuntimeError("native transaction status is uncertain")
        return self._started

    def stage(self) -> None:
        if not self._started or self._staged:
            raise LocalWriteDeniedError(_DENIED)
        self._current_board(compare_bytes=True)
        self._service.execute_board_mutation(
            "pcb_move_footprint",
            self._command,
            verifier=self._verifier,
            participates_in_live_session=True,
        )
        self._staged = True

    def commit(self) -> bool:
        if not self._started or not self._staged:
            return False
        self._current_board(compare_bytes=False)
        response = self._service.push()
        evidence = self._service.last_evidence
        success = (
            response == _PUSH
            and evidence is not None
            and evidence.outcome == "committed"
            and len(evidence.mutations) == 1
            and evidence.mutations[0].final_state_verified is True
            and evidence.mutations[0].recovery_required is False
            and self._service.status_payload().get("state") == "idle"
        )
        if success:
            self._started = False
        return success

    def discard(self) -> bool:
        if not self._started:
            return False
        response = self._service.drop()
        evidence = self._service.last_evidence
        restored = (
            response == _DROP
            and evidence is not None
            and evidence.outcome == "dropped"
            and self._service.status_payload().get("state") == "idle"
        )
        if restored:
            self._started = False
        return restored
