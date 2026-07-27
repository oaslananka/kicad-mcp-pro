"""FastMCP-free live and file-backed PCB session inspection."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Protocol, cast

type LoadedBoard = tuple[object, str, list[str]]
type GetBoard = Callable[[], object]
type LoadFileBackedBoard = Callable[[BaseException], LoadedBoard | str]
type FormatSelectionId = Callable[[object], str]
type GetMaxTextResponseChars = Callable[[], int]
type ConnectionErrors = tuple[type[Exception], ...]


class SessionBoard(Protocol):
    """Live board methods required by session inspection."""

    def get_selection(self) -> Iterable[object]: ...

    def get_as_string(self) -> str: ...


@dataclass(frozen=True)
class PcbSessionInspectionService:
    """Inspect active selection and bounded board text through injected dependencies."""

    get_board: GetBoard
    load_file_backed_board: LoadFileBackedBoard
    format_selection_id: FormatSelectionId
    get_max_text_response_chars: GetMaxTextResponseChars
    connection_errors: ConnectionErrors

    def get_selection(self) -> str:
        """List selected live-board items or describe the file-backed fallback."""
        try:
            board = cast(SessionBoard, self.get_board())
            items = list(board.get_selection())
        except self.connection_errors as exc:
            loaded = self.load_file_backed_board(exc)
            if isinstance(loaded, str):
                return loaded
            _, _, diagnostics = loaded
            return "\n".join(
                [
                    "No PCB items are selected in the file-backed fallback.",
                    *diagnostics,
                ]
            )
        if not items:
            return "No PCB items are currently selected."
        lines = [f"Selected items ({len(items)} total):"]
        for index, item in enumerate(items, start=1):
            lines.append(f"{index}. {type(item).__name__} id={self.format_selection_id(item)}")
        return "\n".join(lines)

    def get_board_as_string(self) -> str:
        """Return bounded live or file-backed board S-expression text."""
        diagnostics: list[str] | None = None
        try:
            board = cast(SessionBoard, self.get_board())
            data = board.get_as_string()
        except self.connection_errors as exc:
            loaded = self.load_file_backed_board(exc)
            if isinstance(loaded, str):
                return loaded
            _, data, diagnostics = loaded
        limit = self.get_max_text_response_chars()
        if len(data) > limit:
            data = f"{data[:limit]}\n... [truncated]"
        return "\n".join([data, *diagnostics]) if diagnostics is not None else data
