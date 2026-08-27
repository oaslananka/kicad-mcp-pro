from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace

import pytest

from kicad_mcp.pcb.transaction_lifecycle import PcbTransactionLifecycleService


class FakeConnectionError(Exception):
    pass


def _run_direct[T](operation: str, command: Callable[[], T]) -> T:
    del operation
    return command()


def _service(board: object, calls: list[str]) -> PcbTransactionLifecycleService:
    def run_mutation[T](operation: str, command: Callable[[], T]) -> T:
        calls.append(operation)
        return command()

    return PcbTransactionLifecycleService(
        get_board=lambda: board,
        run_mutation=run_mutation,
        connection_errors=(FakeConnectionError, OSError),
    )


def test_transaction_operations_use_the_existing_queue_names() -> None:
    calls: list[str] = []
    effects: list[str] = []
    commit = object()

    def begin_commit() -> object:
        effects.append("begin")
        return commit

    board = SimpleNamespace(
        name="demo.kicad_pcb",
        get_project=lambda: SimpleNamespace(path="/workspace/demo/demo.kicad_pro", name="demo"),
        get_as_string=lambda: "(kicad_pcb)",
        begin_commit=begin_commit,
        push_commit=lambda received, _message="": effects.append(
            "push" if received is commit else "push-wrong-handle"
        ),
        drop_commit=lambda received: effects.append(
            "drop" if received is commit else "drop-wrong-handle"
        ),
        revert=lambda: effects.append("revert"),
    )
    service = _service(board, calls)

    assert service.begin() == (
        "Transaction group started. Use pcb_push_commit to apply or pcb_drop_commit to discard."
    )
    assert service.push() == "Transaction group committed successfully."
    assert service.begin() == (
        "Transaction group started. Use pcb_push_commit to apply or pcb_drop_commit to discard."
    )
    assert service.drop() == "Transaction group discarded successfully."
    assert service.revert() == (
        "Board reverted to last saved state. All unsaved changes have been discarded."
    )
    assert calls == [
        "pcb_begin_commit",
        "pcb_push_commit",
        "pcb_begin_commit",
        "pcb_drop_commit",
        "pcb_revert",
    ]
    assert effects == ["begin", "push", "begin", "drop", "revert"]


@pytest.mark.parametrize(
    ("method", "expected"),
    [
        (
            "begin",
            "Transaction grouping is not supported by the current KiCad IPC version. "
            "Mutations will be applied individually without atomic grouping.",
        ),
        ("push", "No active transaction group to commit."),
        ("drop", "No active transaction group to discard."),
        (
            "revert",
            "Revert is not supported by the current KiCad IPC version. "
            "Please save and reload the board manually.",
        ),
    ],
)
def test_unsupported_operations_preserve_legacy_messages(method: str, expected: str) -> None:
    service = _service(SimpleNamespace(), [])

    assert getattr(service, method)() == expected


@pytest.mark.parametrize(
    ("method", "expected"),
    [
        ("begin", "Failed to begin transaction: offline"),
        ("push", "Failed to commit transaction: offline"),
        ("drop", "Failed to discard transaction: offline"),
        ("revert", "Failed to revert board: offline"),
    ],
)
def test_connection_errors_preserve_legacy_messages(method: str, expected: str) -> None:
    def fail() -> object:
        raise FakeConnectionError("offline")

    service = PcbTransactionLifecycleService(
        get_board=fail,
        run_mutation=_run_direct,
        connection_errors=(FakeConnectionError, OSError),
    )

    assert getattr(service, method)() == expected


def test_unexpected_errors_are_not_hidden() -> None:
    def fail() -> object:
        raise RuntimeError("bug")

    service = PcbTransactionLifecycleService(
        get_board=fail,
        run_mutation=_run_direct,
        connection_errors=(FakeConnectionError, OSError),
    )

    with pytest.raises(RuntimeError, match="bug"):
        service.begin()
