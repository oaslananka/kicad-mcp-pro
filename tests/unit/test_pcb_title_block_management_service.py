from __future__ import annotations

import json
from collections.abc import Callable
from types import SimpleNamespace

import pytest

from kicad_mcp.pcb.title_block_management import PcbTitleBlockService


class FakeConnectionError(Exception):
    pass


def _service(
    board: object,
    queue_calls: list[str],
) -> PcbTitleBlockService:
    def run_mutation[T](operation: str, command: Callable[[], T]) -> T:
        queue_calls.append(operation)
        return command()

    return PcbTitleBlockService(
        get_board=lambda: board,
        run_mutation=run_mutation,
        connection_errors=(FakeConnectionError, OSError),
    )


def test_title_block_update_preserves_field_order_queue_and_transaction_payload() -> None:
    queue_calls: list[str] = []
    applied: list[dict[str, str]] = []

    def apply_fields(**kwargs: str) -> None:
        applied.append(kwargs)

    board = SimpleNamespace(set_title_block_info=apply_fields)
    service = _service(board, queue_calls)

    result = service.set_title_block_info(
        title="Controller",
        revision="B",
        company="ACME",
        comment2="Reviewed",
    )

    summary, payload_text = result.split("\nTransaction:\n", maxsplit=1)
    payload = json.loads(payload_text)
    assert summary == "Title block updated: title, revision, company, comment2."
    assert queue_calls == ["pcb_set_title_block_info"]
    assert applied == [
        {
            "title": "Controller",
            "revision": "B",
            "company": "ACME",
            "comment2": "Reviewed",
        }
    ]
    assert payload["changed_objects"] == [
        "board.title_block.title",
        "board.title_block.revision",
        "board.title_block.company",
        "board.title_block.comment2",
    ]
    assert payload["verification"]["roundtrip"] == "live_gui_state"


def test_title_block_requires_at_least_one_field_without_queueing() -> None:
    queue_calls: list[str] = []

    def ignore_fields(**kwargs: str) -> None:
        del kwargs

    service = _service(SimpleNamespace(set_title_block_info=ignore_fields), queue_calls)

    assert service.set_title_block_info() == (
        "No title block fields specified. Provide at least one field to update."
    )
    assert queue_calls == []


def test_unsupported_title_block_preserves_legacy_message() -> None:
    service = _service(SimpleNamespace(), [])

    assert service.set_title_block_info(title="Demo") == (
        "Title block editing requires KiCad 10.0.1 or later. "
        "The current KiCad version does not support this operation."
    )


def test_title_block_connection_error_preserves_legacy_message() -> None:
    def fail() -> object:
        raise FakeConnectionError("offline")

    service = PcbTitleBlockService(
        get_board=fail,
        run_mutation=lambda operation, command: command(),
        connection_errors=(FakeConnectionError, OSError),
    )

    assert service.set_title_block_info(title="Demo") == ("Failed to set title block info: offline")


def test_unexpected_title_block_errors_are_not_hidden() -> None:
    def fail() -> object:
        raise RuntimeError("bug")

    service = PcbTitleBlockService(
        get_board=fail,
        run_mutation=lambda operation, command: command(),
        connection_errors=(FakeConnectionError, OSError),
    )

    with pytest.raises(RuntimeError, match="bug"):
        service.set_title_block_info(title="Demo")
