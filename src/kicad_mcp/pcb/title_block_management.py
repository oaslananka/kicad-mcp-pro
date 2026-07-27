"""FastMCP-free PCB title-block mutation behavior."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from ..models.tool_result import MutatingToolResult, TransactionVerification


class RunMutation(Protocol):
    """Serialize one live-board mutation through the existing command queue."""

    def __call__[T](self, operation: str, command: Callable[[], T]) -> T: ...


type GetBoard = Callable[[], object]
type ConnectionErrors = tuple[type[Exception], ...]


@dataclass(frozen=True)
class PcbTitleBlockService:
    """Update board title-block fields through injected live-board dependencies."""

    get_board: GetBoard
    run_mutation: RunMutation
    connection_errors: ConnectionErrors

    def set_title_block_info(
        self,
        title: str | None = None,
        date: str | None = None,
        revision: str | None = None,
        company: str | None = None,
        comment1: str | None = None,
        comment2: str | None = None,
        comment3: str | None = None,
        comment4: str | None = None,
    ) -> str:
        """Update non-null title-block fields while preserving legacy result text."""
        try:
            board = self.get_board()
            set_title_block_info = getattr(board, "set_title_block_info", None)
            if not callable(set_title_block_info):
                return (
                    "Title block editing requires KiCad 10.0.1 or later. "
                    "The current KiCad version does not support this operation."
                )

            ordered_values = (
                ("title", title),
                ("date", date),
                ("revision", revision),
                ("company", company),
                ("comment1", comment1),
                ("comment2", comment2),
                ("comment3", comment3),
                ("comment4", comment4),
            )
            fields = {name: value for name, value in ordered_values if value is not None}
            if not fields:
                return "No title block fields specified. Provide at least one field to update."

            self.run_mutation(
                "pcb_set_title_block_info",
                lambda: set_title_block_info(**fields),
            )
            updated_fields = ", ".join(fields)
            transaction = MutatingToolResult(
                changed_objects=[f"board.title_block.{field}" for field in fields],
                verification=TransactionVerification(roundtrip="live_gui_state"),
            )
            return transaction.to_compat_text(f"Title block updated: {updated_fields}.")
        except self.connection_errors as exc:
            return f"Failed to set title block info: {exc}"
