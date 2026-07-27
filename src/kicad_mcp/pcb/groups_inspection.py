"""FastMCP-free PCB group inspection behavior."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sized
from dataclasses import dataclass
from typing import cast

type GetBoard = Callable[[], object]
type ConnectionErrors = tuple[type[Exception], ...]


@dataclass(frozen=True)
class PcbGroupsInspectionService:
    """List logical board groups through injected live-board access."""

    get_board: GetBoard
    connection_errors: ConnectionErrors

    def get_groups(self) -> str:
        """Return board groups while preserving legacy formatting and errors."""
        try:
            board = self.get_board()
            get_groups = getattr(board, "get_groups", None)
            if not callable(get_groups):
                return (
                    "Group support requires KiCad 10.0.0 or later. "
                    "The current KiCad version does not support board groups."
                )
            groups = list(cast(Callable[[], Iterable[object]], get_groups)())
            if not groups:
                return "No groups are present on the active board."
            lines = [f"Groups ({len(groups)} total):", "- Source: live-gui"]
            for index, group in enumerate(groups, start=1):
                raw_name = getattr(group, "name", None)
                name = str(raw_name) if raw_name else f"Group {index}"
                items = cast(Sized, getattr(group, "items", ()))
                item_count = len(items)
                lines.append(f"{index}. {name} ({item_count} items)")
            return "\n".join(lines)
        except self.connection_errors as exc:
            return f"Failed to get groups: {exc}"
