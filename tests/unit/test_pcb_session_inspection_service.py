from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace

import pytest

from kicad_mcp.pcb.session_inspection import PcbSessionInspectionService


class FakeConnectionError(Exception):
    pass


def _service(
    board: object,
    *,
    fallback: Callable[[BaseException], str | tuple[object, str, list[str]]] | None = None,
    limit: int = 100,
) -> PcbSessionInspectionService:
    return PcbSessionInspectionService(
        get_board=lambda: board,
        load_file_backed_board=fallback or (lambda _exc: "fallback"),
        format_selection_id=lambda item: str(getattr(item, "uid", "none")),
        get_max_text_response_chars=lambda: limit,
        connection_errors=(FakeConnectionError, OSError),
    )


def test_selection_lists_item_types_ids_and_empty_state() -> None:
    items = [SimpleNamespace(uid="a"), SimpleNamespace(uid="b")]
    board = SimpleNamespace(get_selection=lambda: items)

    assert _service(board).get_selection() == "\n".join(
        [
            "Selected items (2 total):",
            "1. SimpleNamespace id=a",
            "2. SimpleNamespace id=b",
        ]
    )

    def no_selection() -> list[object]:
        return []

    assert _service(SimpleNamespace(get_selection=no_selection)).get_selection() == (
        "No PCB items are currently selected."
    )


def test_selection_file_fallback_preserves_errors_and_diagnostics() -> None:
    def fail() -> object:
        raise FakeConnectionError("offline")

    failed_load = PcbSessionInspectionService(
        get_board=fail,
        load_file_backed_board=lambda _exc: "load failed",
        format_selection_id=lambda _item: "unused",
        get_max_text_response_chars=lambda: 100,
        connection_errors=(FakeConnectionError, OSError),
    )
    assert failed_load.get_selection() == "load failed"

    service = PcbSessionInspectionService(
        get_board=fail,
        load_file_backed_board=lambda _exc: (object(), "board", ["diag-a", "diag-b"]),
        format_selection_id=lambda _item: "unused",
        get_max_text_response_chars=lambda: 100,
        connection_errors=(FakeConnectionError, OSError),
    )
    assert service.get_selection() == "\n".join(
        [
            "No PCB items are selected in the file-backed fallback.",
            "diag-a",
            "diag-b",
        ]
    )


def test_board_string_preserves_live_fallback_and_truncation_behavior() -> None:
    assert _service(
        SimpleNamespace(get_as_string=lambda: "(kicad_pcb)"), limit=50
    ).get_board_as_string() == ("(kicad_pcb)")
    assert _service(
        SimpleNamespace(get_as_string=lambda: "abcdefgh"), limit=5
    ).get_board_as_string() == ("abcde\n... [truncated]")

    def fail() -> object:
        raise FakeConnectionError("offline")

    failed_load = PcbSessionInspectionService(
        get_board=fail,
        load_file_backed_board=lambda _exc: "load failed",
        format_selection_id=lambda _item: "unused",
        get_max_text_response_chars=lambda: 100,
        connection_errors=(FakeConnectionError, OSError),
    )
    assert failed_load.get_board_as_string() == "load failed"

    service = PcbSessionInspectionService(
        get_board=fail,
        load_file_backed_board=lambda _exc: (object(), "board-data", ["diag"]),
        format_selection_id=lambda _item: "unused",
        get_max_text_response_chars=lambda: 100,
        connection_errors=(FakeConnectionError, OSError),
    )
    assert service.get_board_as_string() == "board-data\ndiag"


def test_session_inspection_does_not_hide_unexpected_errors() -> None:
    def fail() -> object:
        raise RuntimeError("bug")

    service = PcbSessionInspectionService(
        get_board=fail,
        load_file_backed_board=lambda _exc: "unused",
        format_selection_id=lambda _item: "unused",
        get_max_text_response_chars=lambda: 100,
        connection_errors=(FakeConnectionError, OSError),
    )

    with pytest.raises(RuntimeError, match="bug"):
        service.get_selection()
    with pytest.raises(RuntimeError, match="bug"):
        service.get_board_as_string()
