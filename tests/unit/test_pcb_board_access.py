from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace

import pytest

from kicad_mcp.pcb.board_access import (
    BoardAccessError,
    board_footprints,
    board_nets,
    board_nets_filtered,
    board_pads,
    board_shapes,
    board_tracks,
    board_vias,
    board_zones,
)

type CollectionReader = Callable[[object], list[object]]


@pytest.mark.parametrize(
    ("reader", "operation", "method_name"),
    [
        (board_tracks, "tracks", "get_tracks"),
        (board_vias, "vias", "get_vias"),
        (board_footprints, "footprints", "get_footprints"),
        (board_pads, "pads", "get_pads"),
        (board_zones, "zones", "get_zones"),
        (board_shapes, "shapes", "get_shapes"),
        (board_nets, "nets", "get_nets"),
    ],
)
def test_board_collection_readers_distinguish_empty_data_from_access_failure(
    reader: CollectionReader,
    operation: str,
    method_name: str,
) -> None:
    empty_board = SimpleNamespace(**{method_name: lambda: []})
    assert reader(empty_board) == []

    def fail() -> list[object]:
        raise OSError("ipc unavailable")

    unavailable_board = SimpleNamespace(**{method_name: fail})
    with pytest.raises(
        BoardAccessError,
        match=rf"Could not read board {operation} via {method_name}: ipc unavailable",
    ) as exc_info:
        reader(unavailable_board)

    assert exc_info.value.operation == operation
    assert exc_info.value.method_name == method_name
    assert isinstance(exc_info.value.__cause__, OSError)
    assert exc_info.value.to_payload()["code"] == "KICAD_BOARD_ACCESS_UNAVAILABLE"


def test_board_collection_reader_reports_missing_method_with_original_cause() -> None:
    with pytest.raises(
        BoardAccessError,
        match="Could not read board vias via get_vias",
    ) as exc_info:
        board_vias(SimpleNamespace())

    assert isinstance(exc_info.value.__cause__, AttributeError)


def test_board_collection_reader_rejects_non_iterable_results() -> None:
    board = SimpleNamespace(get_tracks=lambda: None)

    with pytest.raises(
        BoardAccessError,
        match="Could not read board tracks via get_tracks",
    ) as exc_info:
        board_tracks(board)

    assert isinstance(exc_info.value.__cause__, TypeError)


def test_filtered_net_reader_preserves_explicit_netclass_filter() -> None:
    seen: list[object | None] = []

    def get_nets(*, netclass_filter: object | None) -> tuple[str, ...]:
        seen.append(netclass_filter)
        return ("GND",)

    board = SimpleNamespace(get_nets=get_nets)

    assert board_nets_filtered(board, netclass_filter=None) == ["GND"]
    assert seen == [None]


def test_architecture_checker_tracks_canonical_board_access_module() -> None:
    from scripts import check_architecture_boundaries as boundaries

    assert "kicad_mcp.pcb.board_access" in boundaries.DOMAIN_MODULES
    assert "kicad_mcp.pcb.board_access" in boundaries.PURE_HELPERS
