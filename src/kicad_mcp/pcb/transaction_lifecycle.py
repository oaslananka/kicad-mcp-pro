"""FastMCP-free native-live PCB transaction lifecycle behavior."""

from __future__ import annotations

import hashlib
import threading
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Protocol

from kipy.board import Board

from ..ipc.command_queue import AmbiguousMutationError
from .live_edit_evidence import LiveBoardIdentity, LiveEditEvidence, LiveMutationReceipt


class RunMutation(Protocol):
    """Serialize one live-board mutation through the canonical command queue."""

    def __call__[T](self, operation: str, command: Callable[[], T]) -> T: ...


type GetBoard = Callable[[], Board]
type ConnectionErrors = tuple[type[Exception], ...]
type PostconditionVerifier[T] = Callable[[Board, T], bool]


@dataclass(frozen=True, slots=True)
class _PendingVerification:
    mutation_id: str
    operation: str
    verify: Callable[[Board], bool]


def _default_connection_epoch() -> object:
    return 0


_AMBIGUOUS_TRANSACTION_MESSAGE = (
    "Transaction state is ambiguous after an IPC failure; reconcile the active KiCad board "
    "before starting, committing, or discarding another native-live transaction."
)


@dataclass
class PcbTransactionLifecycleService:
    """Own one board-bound native-live transaction and its verification evidence."""

    get_board: GetBoard
    run_mutation: RunMutation
    connection_errors: ConnectionErrors
    get_connection_epoch: Callable[[], object] = _default_connection_epoch
    _commit_handle: object | None = field(default=None, init=False, repr=False)
    _active_identity: LiveBoardIdentity | None = field(default=None, init=False, repr=False)
    _pre_state_digest: str | None = field(default=None, init=False, repr=False)
    _connection_epoch: object | None = field(default=None, init=False, repr=False)
    _transaction_supported: bool = field(default=False, init=False, repr=False)
    _receipts: list[LiveMutationReceipt] = field(default_factory=list, init=False, repr=False)
    _pending_verifications: list[_PendingVerification] = field(
        default_factory=list, init=False, repr=False
    )
    _recovery_required: bool = field(default=False, init=False, repr=False)
    _last_evidence: LiveEditEvidence | None = field(default=None, init=False, repr=False)
    _lock: threading.RLock = field(default_factory=threading.RLock, init=False, repr=False)

    @staticmethod
    def _identity_for(board: Board) -> LiveBoardIdentity:
        get_project = getattr(board, "get_project", None)
        if not callable(get_project):
            raise RuntimeError("Active KiCad board does not expose project identity.")
        project = get_project()
        project_path = str(getattr(project, "path", "")).strip()
        board_name = str(getattr(board, "name", "")).strip()
        if not project_path or not board_name:
            raise RuntimeError(
                "Active KiCad board identity is incomplete; live editing is unavailable."
            )
        normalized_path = str(Path(project_path).expanduser().resolve(strict=False))
        internal_key = f"{normalized_path}\0{board_name}"
        fingerprint = hashlib.sha256(internal_key.encode("utf-8")).hexdigest()
        return LiveBoardIdentity(
            board_name=board_name,
            internal_key=internal_key,
            fingerprint=fingerprint,
        )

    @staticmethod
    def _state_digest(board: Board) -> str:
        get_as_string = getattr(board, "get_as_string", None)
        if not callable(get_as_string):
            raise RuntimeError("Active KiCad board cannot provide a verification snapshot.")
        contents = get_as_string()
        if not isinstance(contents, str):
            raise RuntimeError("Active KiCad board returned an invalid verification snapshot.")
        return hashlib.sha256(contents.encode("utf-8")).hexdigest()

    def _state_name(self) -> str:
        if self._recovery_required:
            return "recovery_required"
        if self._commit_handle is not None:
            return "active"
        return "idle"

    def _assert_same_board(self, board: Board) -> LiveBoardIdentity:
        current = self._identity_for(board)
        if (
            self._active_identity is None
            or current.internal_key != self._active_identity.internal_key
        ):
            self._recovery_required = True
            raise RuntimeError(
                "The active board changed during the native-live transaction; recovery is required "
                "before another mutation can run."
            )
        return current

    def _terminal_evidence(self, outcome: str) -> LiveEditEvidence:
        identity = self._active_identity
        if identity is None:
            raise RuntimeError("Native-live evidence cannot be finalized without board identity.")
        return LiveEditEvidence(
            schema_version="pcb-live-edit-session.v1",
            board_fingerprint=identity.fingerprint,
            board_name=identity.board_name,
            outcome=outcome,  # type: ignore[arg-type]
            mutations=tuple(self._receipts),
        )

    def _clear_active(self) -> None:
        self._commit_handle = None
        self._active_identity = None
        self._pre_state_digest = None
        self._connection_epoch = None
        self._receipts.clear()
        self._pending_verifications.clear()
        self._recovery_required = False

    def _assert_connection_epoch(self) -> None:
        """Fail closed if the underlying IPC continuity changed mid-transaction."""
        expected = self._connection_epoch
        if expected is None:
            return
        if self.get_connection_epoch() != expected:
            self._mark_control_ambiguity()
            raise RuntimeError(
                "The KiCad IPC session changed during the native-live transaction; "
                "recovery is required before another mutation can run."
            )

    def _mark_control_ambiguity(self) -> None:
        """Fail closed when a transaction control response is lost."""
        self._commit_handle = None
        self._recovery_required = True
        if self._active_identity is not None:
            self._last_evidence = self._terminal_evidence("recovery_required")

    def _mark_receipts_recovered(self, succeeded: bool) -> None:
        self._receipts[:] = [
            replace(
                receipt,
                recovery_required=True,
                recovery_succeeded=succeeded,
                state_divergence_detected=(
                    False if succeeded else receipt.state_divergence_detected
                ),
                final_state_verified=succeeded,
            )
            for receipt in self._receipts
        ]

    def _drop_for_abort(self, board: Board) -> bool:
        """Drop the active commit on the verified board and prove pre-state equivalence."""
        if self._commit_handle is None or self._pre_state_digest is None:
            return False
        self._assert_connection_epoch()
        self._assert_same_board(board)
        command = getattr(board, "drop_commit", None)
        if not callable(command):
            return False
        commit_handle = self._commit_handle
        self.run_mutation("pcb_drop_commit", lambda: command(commit_handle))
        fresh_board = self.get_board()
        self._assert_connection_epoch()
        self._assert_same_board(fresh_board)
        restored = self._state_digest(fresh_board) == self._pre_state_digest
        self._commit_handle = None
        self._mark_receipts_recovered(restored)
        if restored:
            self._last_evidence = self._terminal_evidence("aborted")
            self._clear_active()
            return True
        self._recovery_required = True
        self._last_evidence = self._terminal_evidence("recovery_required")
        return False

    @property
    def last_evidence(self) -> LiveEditEvidence | None:
        """Return the most recent terminal native-live evidence, if any."""
        with self._lock:
            return self._last_evidence

    def status_payload(self) -> dict[str, object]:
        """Return bounded path-free native-live state for public reporting."""
        with self._lock:
            identity = self._active_identity
            last = self._last_evidence
            return {
                "schema_version": "pcb-live-edit-state.v1",
                "state": self._state_name(),
                "transaction_supported": self._transaction_supported,
                "board_fingerprint": (
                    identity.fingerprint
                    if identity is not None
                    else (last.board_fingerprint if last is not None else "")
                ),
                "board_name": (
                    identity.board_name
                    if identity is not None
                    else (last.board_name if last is not None else "")
                ),
                "mutation_count": len(self._receipts) if identity is not None else 0,
                "verified_mutation_count": sum(
                    receipt.final_state_verified for receipt in self._receipts
                ),
                "staged_mutation_count": sum(
                    receipt.execution_state == "completed" and not receipt.final_state_verified
                    for receipt in self._receipts
                ),
                "ambiguous_mutation_count": sum(
                    receipt.execution_state == "interrupted" for receipt in self._receipts
                ),
                "recovery_required": self._recovery_required,
                "last_outcome": last.outcome if last is not None else None,
            }

    def begin(self) -> str:
        """Begin one atomic transaction group when supported by KiCad."""
        with self._lock:
            if self._recovery_required:
                return _AMBIGUOUS_TRANSACTION_MESSAGE
            if self._commit_handle is not None:
                return (
                    "A transaction group is already active. Commit or discard it before starting "
                    "another."
                )
            try:
                board = self.get_board()
                command = getattr(board, "begin_commit", None)
                if not callable(command):
                    self._transaction_supported = False
                    return (
                        "Transaction grouping is not supported by the current KiCad IPC version. "
                        "Mutations will be applied individually without atomic grouping."
                    )
                identity = self._identity_for(board)
                pre_state_digest = self._state_digest(board)
                connection_epoch = self.get_connection_epoch()
                try:
                    commit_handle = self.run_mutation("pcb_begin_commit", command)
                except AmbiguousMutationError:
                    self._active_identity = identity
                    self._pre_state_digest = pre_state_digest
                    self._connection_epoch = connection_epoch
                    self._mark_control_ambiguity()
                    raise
                if commit_handle is None:
                    self._transaction_supported = False
                    return (
                        "Transaction grouping is not supported by the current KiCad IPC version. "
                        "Mutations will be applied individually without atomic grouping."
                    )
                self._commit_handle = commit_handle
                self._transaction_supported = True
                self._active_identity = identity
                self._pre_state_digest = pre_state_digest
                self._connection_epoch = connection_epoch
                self._receipts.clear()
                self._pending_verifications.clear()
                self._recovery_required = False
                return (
                    "Transaction group started. Use pcb_push_commit to apply or "
                    "pcb_drop_commit to discard."
                )
            except self.connection_errors as exc:
                return f"Failed to begin transaction: {exc}"

    def _mark_published_verification_failure(
        self,
        *,
        mutation_id: str | None = None,
        divergence: bool = False,
    ) -> None:
        """Mark a pushed transaction unsafe when its live re-read cannot be proven."""
        updated: list[LiveMutationReceipt] = []
        for receipt in self._receipts:
            selected = mutation_id is None or receipt.mutation_id == mutation_id
            updated.append(
                replace(
                    receipt,
                    recovery_required=True if selected else receipt.recovery_required,
                    recovery_succeeded=None if selected else receipt.recovery_succeeded,
                    state_divergence_detected=(
                        divergence if selected else receipt.state_divergence_detected
                    ),
                    final_state_verified=False if selected else receipt.final_state_verified,
                )
            )
        self._receipts[:] = updated
        self._commit_handle = None
        self._recovery_required = True
        self._last_evidence = self._terminal_evidence("recovery_required")

    def _verify_published_mutations(self, board: Board) -> None:
        """Verify all staged mutations against the live board after native commit publication."""
        for pending in self._pending_verifications:
            try:
                verified = pending.verify(board)
            except Exception as exc:
                self._mark_published_verification_failure(mutation_id=pending.mutation_id)
                raise RuntimeError(
                    f"Native-live commit was published as one KiCad undo step, but "
                    f"{pending.operation} live postcondition verification could not complete. "
                    "Use KiCad Undo once to restore the operation, then reset or reselect the "
                    "project before continuing."
                ) from exc
            if not verified:
                self._mark_published_verification_failure(
                    mutation_id=pending.mutation_id, divergence=True
                )
                raise RuntimeError(
                    f"Native-live commit was published as one KiCad undo step, but "
                    f"{pending.operation} live postcondition verification failed. "
                    "Use KiCad Undo once to restore the operation, then reset or reselect the "
                    "project before continuing."
                )
            self._receipts[:] = [
                replace(receipt, final_state_verified=True)
                if receipt.mutation_id == pending.mutation_id
                else receipt
                for receipt in self._receipts
            ]

    def push(self) -> str:
        """Publish one native undo unit, then re-read every staged mutation before success."""
        with self._lock:
            if self._recovery_required:
                return _AMBIGUOUS_TRANSACTION_MESSAGE
            try:
                if self._commit_handle is not None:
                    self._assert_connection_epoch()
                board = self.get_board()
                if self._commit_handle is None:
                    return "No active transaction group to commit."
                self._assert_connection_epoch()
                self._assert_same_board(board)
                if any(receipt.recovery_required for receipt in self._receipts):
                    raise RuntimeError(
                        "The native-live transaction has unsafe state and cannot be committed."
                    )
                command = getattr(board, "push_commit", None)
                if not callable(command):
                    return "No active transaction group to commit."
                commit_handle = self._commit_handle
                try:
                    self.run_mutation(
                        "pcb_push_commit",
                        lambda: command(commit_handle, "KiCad MCP native live edit"),
                    )
                except AmbiguousMutationError:
                    self._mark_control_ambiguity()
                    raise
                self._commit_handle = None
                try:
                    fresh_board = self.get_board()
                    self._assert_connection_epoch()
                    self._assert_same_board(fresh_board)
                except Exception as exc:
                    self._mark_published_verification_failure()
                    raise RuntimeError(
                        "Native-live commit was published as one KiCad undo step, but the live "
                        "board could not be re-read safely. Use KiCad Undo once to restore the "
                        "operation, then reset or reselect the project before continuing."
                    ) from exc
                self._verify_published_mutations(fresh_board)
                self._state_digest(fresh_board)
                self._last_evidence = self._terminal_evidence("committed")
                self._clear_active()
                return "Transaction group committed successfully."
            except self.connection_errors as exc:
                return f"Failed to commit transaction: {exc}"

    def drop(self) -> str:
        """Discard the active transaction and prove the pre-operation state was restored."""
        with self._lock:
            if self._recovery_required:
                return _AMBIGUOUS_TRANSACTION_MESSAGE
            try:
                if self._commit_handle is not None:
                    self._assert_connection_epoch()
                board = self.get_board()
                if self._commit_handle is None:
                    return "No active transaction group to discard."
                self._assert_connection_epoch()
                self._assert_same_board(board)
                if self._pre_state_digest is None:
                    raise RuntimeError("Transaction pre-operation state is unavailable.")
                command = getattr(board, "drop_commit", None)
                if not callable(command):
                    return "No active transaction group to discard."
                commit_handle = self._commit_handle
                try:
                    self.run_mutation("pcb_drop_commit", lambda: command(commit_handle))
                except AmbiguousMutationError:
                    self._mark_control_ambiguity()
                    raise
                fresh_board = self.get_board()
                self._assert_connection_epoch()
                self._assert_same_board(fresh_board)
                restored = self._state_digest(fresh_board) == self._pre_state_digest
                self._commit_handle = None
                self._mark_receipts_recovered(restored)
                if not restored:
                    self._recovery_required = True
                    self._last_evidence = self._terminal_evidence("recovery_required")
                    raise RuntimeError(
                        "Transaction discard could not prove restoration of the pre-operation "
                        "state; recovery is required."
                    )
                self._last_evidence = self._terminal_evidence("dropped")
                self._clear_active()
                return "Transaction group discarded successfully."
            except self.connection_errors as exc:
                return f"Failed to discard transaction: {exc}"

    def _abort_after_mutation_failure(
        self,
        *,
        board: Board,
        mutation_id: str,
        operation: str,
        execution_state: str,
    ) -> None:
        """Record a failed/interrupted mutation and attempt verified rollback."""
        self._receipts.append(
            LiveMutationReceipt(
                mutation_id=mutation_id,
                operation=operation,
                execution_state=execution_state,  # type: ignore[arg-type]
                recovery_required=True,
                recovery_succeeded=None,
                duplicate_application_detected=False,
                state_divergence_detected=False,
                corruption_detected=False,
                final_state_verified=False,
            )
        )
        try:
            self._drop_for_abort(board)
        except Exception:  # noqa: BLE001 - original mutation failure remains primary
            self._recovery_required = True
            self._last_evidence = self._terminal_evidence("recovery_required")

    def _verify_immediate_mutation[T](
        self,
        *,
        operation: str,
        result: T,
        verifier: PostconditionVerifier[T],
    ) -> T:
        """Verify a non-transactional mutation after KiCad has published it immediately."""
        fresh_board = self.get_board()
        try:
            verified = verifier(fresh_board, result)
        except Exception as exc:
            raise RuntimeError(
                f"{operation} completed but live postcondition verification could not complete."
            ) from exc
        if not verified:
            raise RuntimeError(f"{operation} completed but live postcondition verification failed.")
        return result

    def _stage_mutation_verification[T](
        self,
        *,
        mutation_id: str,
        operation: str,
        result: T,
        verifier: PostconditionVerifier[T],
    ) -> T:
        """Record a staged mutation whose live state is only readable after push_commit."""
        self._receipts.append(
            LiveMutationReceipt(
                mutation_id=mutation_id,
                operation=operation,
                execution_state="completed",
                recovery_required=False,
                recovery_succeeded=None,
                duplicate_application_detected=False,
                state_divergence_detected=False,
                corruption_detected=False,
                final_state_verified=False,
            )
        )
        self._pending_verifications.append(
            _PendingVerification(
                mutation_id=mutation_id,
                operation=operation,
                verify=lambda board: verifier(board, result),
            )
        )
        return result

    def _prepare_mutation[T](
        self,
        *,
        operation: str,
        verifier: PostconditionVerifier[T] | None,
        participates_in_live_session: bool,
    ) -> tuple[Board, bool]:
        """Validate active-session guards and return the current verified board."""
        if self._recovery_required:
            raise RuntimeError(
                "Native-live transaction recovery is required before another mutation can run."
            )
        active = self._commit_handle is not None
        if active and not participates_in_live_session:
            raise RuntimeError(
                f"{operation} does not participate in the active native-live transaction. "
                "Commit or discard the transaction before using this operation."
            )
        if active and verifier is None:
            raise RuntimeError(
                f"{operation} requires a postcondition verifier before it can participate in "
                "a native-live transaction."
            )
        if active:
            self._assert_connection_epoch()
        board = self.get_board()
        if active:
            self._assert_connection_epoch()
            self._assert_same_board(board)
        return board, active

    def execute_board_mutation[T](
        self,
        operation: str,
        command: Callable[[Board], T],
        *,
        verifier: PostconditionVerifier[T] | None,
        participates_in_live_session: bool,
    ) -> T:
        """Execute one serialized board mutation with active-session verification."""
        with self._lock:
            board, active = self._prepare_mutation(
                operation=operation,
                verifier=verifier,
                participates_in_live_session=participates_in_live_session,
            )

            mutation_id = f"live-mutation-{len(self._receipts) + 1}"
            try:
                result = self.run_mutation(operation, lambda: command(board))
            except AmbiguousMutationError:
                if active:
                    self._abort_after_mutation_failure(
                        board=board,
                        mutation_id=mutation_id,
                        operation=operation,
                        execution_state="interrupted",
                    )
                raise
            except Exception:
                if active:
                    self._abort_after_mutation_failure(
                        board=board,
                        mutation_id=mutation_id,
                        operation=operation,
                        execution_state="failed",
                    )
                raise

            if verifier is None:
                return result
            if active:
                return self._stage_mutation_verification(
                    mutation_id=mutation_id,
                    operation=operation,
                    result=result,
                    verifier=verifier,
                )
            return self._verify_immediate_mutation(
                operation=operation, result=result, verifier=verifier
            )

    def revert(self) -> str:
        """Revert the board to its last saved state when supported by KiCad."""
        with self._lock:
            if self._recovery_required:
                return _AMBIGUOUS_TRANSACTION_MESSAGE
            try:
                board = self.get_board()
                command = getattr(board, "revert", None)
                if not callable(command):
                    return (
                        "Revert is not supported by the current KiCad IPC version. "
                        "Please save and reload the board manually."
                    )
                self.run_mutation("pcb_revert", command)
                return (
                    "Board reverted to last saved state. All unsaved changes have been discarded."
                )
            except self.connection_errors as exc:
                return f"Failed to revert board: {exc}"
