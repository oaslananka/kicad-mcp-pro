from __future__ import annotations

from collections.abc import Callable
from inspect import signature

from kipy.board import Board

from kicad_mcp.pcb.transaction_lifecycle import PcbTransactionLifecycleService


class _Board:
    def __init__(self) -> None:
        self.commit = object()
        self.calls: list[tuple[object, ...]] = []
        self.name = "demo.kicad_pcb"
        self.contents = "(kicad_pcb)"

    def get_project(self) -> object:
        from types import SimpleNamespace

        return SimpleNamespace(path="/workspace/demo/demo.kicad_pro", name="demo")

    def get_as_string(self) -> str:
        return self.contents

    def begin_commit(self) -> object:
        self.calls.append(("begin",))
        return self.commit

    def push_commit(self, commit: object, message: str = "") -> None:
        self.calls.append(("push", commit, message))

    def drop_commit(self, commit: object) -> None:
        self.calls.append(("drop", commit))

    def revert(self) -> None:
        self.calls.append(("revert",))


def _run_direct[T](operation: str, command: Callable[[], T]) -> T:
    del operation
    return command()


def _service(board: _Board) -> PcbTransactionLifecycleService:
    return PcbTransactionLifecycleService(
        get_board=lambda: board,
        run_mutation=_run_direct,
        connection_errors=(OSError,),
    )


def test_pinned_kipy_commit_lifecycle_requires_commit_handle() -> None:
    assert list(signature(Board.begin_commit).parameters) == ["self"]
    assert list(signature(Board.push_commit).parameters)[:2] == ["self", "commit"]
    assert list(signature(Board.drop_commit).parameters) == ["self", "commit"]


def test_service_retains_exact_commit_handle_for_push() -> None:
    board = _Board()
    service = _service(board)

    assert service.begin().startswith("Transaction group started.")
    assert service.push() == "Transaction group committed successfully."

    assert board.calls == [
        ("begin",),
        ("push", board.commit, "KiCad MCP native live edit"),
    ]


def test_service_retains_exact_commit_handle_for_drop() -> None:
    board = _Board()
    service = _service(board)

    assert service.begin().startswith("Transaction group started.")
    assert service.drop() == "Transaction group discarded successfully."

    assert board.calls == [("begin",), ("drop", board.commit)]


def test_second_begin_is_rejected_while_commit_is_active() -> None:
    board = _Board()
    service = _service(board)

    assert service.begin().startswith("Transaction group started.")
    assert service.begin() == (
        "A transaction group is already active. Commit or discard it before starting another."
    )
    assert board.calls == [("begin",)]
