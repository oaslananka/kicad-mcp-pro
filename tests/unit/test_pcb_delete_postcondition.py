"""KiCad 10 deletion postcondition reports absence as an ApiError."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from kipy.errors import ApiError

from kicad_mcp.tools.pcb import (
    _format_selection_id,
    _remove_existing_items_by_id,
    _verify_deleted_items,
)


class _LookupBoard:
    def __init__(
        self, *, found: list[object] | None = None, error: Exception | None = None
    ) -> None:
        self.found = [] if found is None else found
        self.error = error
        self.requested: list[object] | None = None

    def get_items_by_id(self, ids: list[object]) -> list[object]:
        self.requested = ids
        if self.error is not None:
            raise self.error
        return self.found


def test_missing_id_api_error_verifies_delete_on_kicad_10() -> None:
    ids = (object(), object())
    board = _LookupBoard(
        error=ApiError("KiCad returned error: none of the requested IDs were found or valid")
    )

    assert _verify_deleted_items(board, ids) is True  # type: ignore[arg-type]
    assert board.requested == list(ids)


@pytest.mark.parametrize("found,expected", [([], True), ([object()], False)])
def test_delete_verifier_still_checks_partial_lookup(found: list[object], expected: bool) -> None:
    assert _verify_deleted_items(_LookupBoard(found=found), (object(),)) is expected  # type: ignore[arg-type]


def test_unrelated_api_error_is_not_accepted_as_delete_success() -> None:
    board = _LookupBoard(error=ApiError("KiCad returned error: board was not available"))
    with pytest.raises(ApiError, match="board was not available"):
        _verify_deleted_items(board, (object(),))  # type: ignore[arg-type]


def test_partial_match_to_known_error_does_not_mask_unrelated_api_error() -> None:
    board = _LookupBoard(
        error=ApiError(
            "KiCad returned error: none of the requested IDs were found or valid; access denied"
        )
    )
    with pytest.raises(ApiError, match="access denied"):
        _verify_deleted_items(board, (object(),))  # type: ignore[arg-type]


def test_no_lookup_method_does_not_claim_verified_deletion() -> None:
    assert _verify_deleted_items(object(), (object(),)) is False  # type: ignore[arg-type]


class _DeletingBoard(_LookupBoard):
    def __init__(
        self, *, found: list[object] | None = None, error: Exception | None = None
    ) -> None:
        super().__init__(found=found, error=error)
        self.deleted: list[object] | None = None

    def remove_items_by_id(self, ids: list[object]) -> None:
        self.deleted = ids


def _item(value: str) -> object:
    return SimpleNamespace(id=SimpleNamespace(value=value))


def test_selection_id_is_full_and_can_be_reused() -> None:
    full_id = "3757d6f2-1111-2222-3333-444444444444"
    assert _format_selection_id(_item(full_id)) == full_id
    assert _format_selection_id(object()) == ""


def test_delete_preflight_rejects_unknown_ids_without_mutating_board() -> None:
    board = _DeletingBoard(found=[_item("existing")])
    ids = (SimpleNamespace(value="existing"), SimpleNamespace(value="unknown"))
    with pytest.raises(ValueError, match="unknown"):
        _remove_existing_items_by_id(board, ids)  # type: ignore[arg-type]
    assert board.deleted is None


def test_delete_preflight_rejects_nonexistent_ids_in_kicad_10() -> None:
    board = _DeletingBoard(
        error=ApiError("KiCad returned error: none of the requested IDs were found or valid")
    )
    with pytest.raises(ValueError, match="No matching"):
        _remove_existing_items_by_id(board, (SimpleNamespace(value="missing"),))  # type: ignore[arg-type]
    assert board.deleted is None


def test_delete_preflight_removes_only_identified_items() -> None:
    board = _DeletingBoard(found=[_item("existing")])
    ids = (SimpleNamespace(value="existing"),)
    assert _remove_existing_items_by_id(board, ids) == ids  # type: ignore[arg-type]
    assert board.deleted == list(ids)
