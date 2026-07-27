"""FastMCP-free PCB transaction and revert lifecycle behavior."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol


class RunMutation(Protocol):
    """Serialize one live-board mutation through the existing command queue."""

    def __call__[T](self, operation: str, command: Callable[[], T]) -> T: ...


type GetBoard = Callable[[], object]
type ConnectionErrors = tuple[type[Exception], ...]


@dataclass(frozen=True)
class PcbTransactionLifecycleService:
    """Manage transaction grouping and board revert through injected dependencies."""

    get_board: GetBoard
    run_mutation: RunMutation
    connection_errors: ConnectionErrors

    def _run(
        self,
        *,
        method_name: str,
        operation: str,
        unsupported: str,
        success: str,
        failure_prefix: str,
    ) -> str:
        try:
            board = self.get_board()
            command = getattr(board, method_name, None)
            if not callable(command):
                return unsupported
            self.run_mutation(operation, command)
            return success
        except self.connection_errors as exc:
            return f"{failure_prefix}: {exc}"

    def begin(self) -> str:
        """Begin one atomic transaction group when supported by KiCad."""
        return self._run(
            method_name="begin_commit",
            operation="pcb_begin_commit",
            unsupported=(
                "Transaction grouping is not supported by the current KiCad IPC version. "
                "Mutations will be applied individually without atomic grouping."
            ),
            success=(
                "Transaction group started. Use pcb_push_commit to apply or "
                "pcb_drop_commit to discard."
            ),
            failure_prefix="Failed to begin transaction",
        )

    def push(self) -> str:
        """Commit the active transaction group."""
        return self._run(
            method_name="push_commit",
            operation="pcb_push_commit",
            unsupported="No active transaction group to commit.",
            success="Transaction group committed successfully.",
            failure_prefix="Failed to commit transaction",
        )

    def drop(self) -> str:
        """Discard the active transaction group."""
        return self._run(
            method_name="drop_commit",
            operation="pcb_drop_commit",
            unsupported="No active transaction group to discard.",
            success="Transaction group discarded successfully.",
            failure_prefix="Failed to discard transaction",
        )

    def revert(self) -> str:
        """Revert the board to its last saved state when supported by KiCad."""
        return self._run(
            method_name="revert",
            operation="pcb_revert",
            unsupported=(
                "Revert is not supported by the current KiCad IPC version. "
                "Please save and reload the board manually."
            ),
            success=(
                "Board reverted to last saved state. All unsaved changes have been discarded."
            ),
            failure_prefix="Failed to revert board",
        )
