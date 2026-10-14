"""KiCad 10 deletion postcondition reports absence as an ApiError."""

from __future__ import annotations

import pytest
from kipy.errors import ApiError

from kicad_mcp.tools.pcb import _verify_deleted_items


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
