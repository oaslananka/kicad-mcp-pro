from __future__ import annotations

from types import SimpleNamespace

import pytest

from kicad_mcp.pcb.groups_inspection import PcbGroupsInspectionService


class FakeConnectionError(Exception):
    pass


def _service(board: object) -> PcbGroupsInspectionService:
    return PcbGroupsInspectionService(
        get_board=lambda: board,
        connection_errors=(FakeConnectionError, OSError),
    )


def test_groups_listing_preserves_names_fallbacks_and_item_counts() -> None:
    board = SimpleNamespace(
        get_groups=lambda: [
            SimpleNamespace(name="Power", items=[1, 2]),
            SimpleNamespace(name="", items=[1]),
            SimpleNamespace(items=[]),
        ]
    )

    assert _service(board).get_groups() == "\n".join(
        [
            "Groups (3 total):",
            "- Source: live-gui",
            "1. Power (2 items)",
            "2. Group 2 (1 items)",
            "3. Group 3 (0 items)",
        ]
    )


def test_groups_listing_preserves_empty_and_unsupported_messages() -> None:
    def no_groups() -> list[object]:
        return []

    assert _service(SimpleNamespace(get_groups=no_groups)).get_groups() == (
        "No groups are present on the active board."
    )
    assert _service(SimpleNamespace()).get_groups() == (
        "Group support requires KiCad 10.0.0 or later. "
        "The current KiCad version does not support board groups."
    )


def test_groups_connection_error_preserves_legacy_message() -> None:
    def fail() -> object:
        raise FakeConnectionError("offline")

    service = PcbGroupsInspectionService(
        get_board=fail,
        connection_errors=(FakeConnectionError, OSError),
    )

    assert service.get_groups() == "Failed to get groups: offline"


def test_unexpected_groups_errors_are_not_hidden() -> None:
    def fail() -> object:
        raise RuntimeError("bug")

    service = PcbGroupsInspectionService(
        get_board=fail,
        connection_errors=(FakeConnectionError, OSError),
    )

    with pytest.raises(RuntimeError, match="bug"):
        service.get_groups()
