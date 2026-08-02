"""Typed access contract for live KiCad board collections.

Collection readers in this module preserve a successful empty result while
normalizing unavailable or unreadable board API calls into one internal error.
Callers decide whether to report the error, propagate it, or use an explicit
file-backed fallback.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Protocol, cast

from ..errors import BoardAccessError as BoardAccessError


class TracksBoard(Protocol):
    def get_tracks(self) -> Iterable[object]: ...


class ViasBoard(Protocol):
    def get_vias(self) -> Iterable[object]: ...


class FootprintsBoard(Protocol):
    def get_footprints(self) -> Iterable[object]: ...


class PadsBoard(Protocol):
    def get_pads(self) -> Iterable[object]: ...


class ZonesBoard(Protocol):
    def get_zones(self) -> Iterable[object]: ...


class ShapesBoard(Protocol):
    def get_shapes(self) -> Iterable[object]: ...


class NetsBoard(Protocol):
    def get_nets(self) -> Iterable[object]: ...


class FilteredNetsBoard(Protocol):
    def get_nets(self, *, netclass_filter: object | None) -> Iterable[object]: ...


def _read_collection(
    operation: str,
    method_name: str,
    accessor: Callable[[], Iterable[object]],
) -> list[object]:
    try:
        return list(accessor())
    except Exception as exc:
        raise BoardAccessError(operation, method_name, exc) from exc


def board_tracks(board: object) -> list[object]:
    return _read_collection(
        "tracks",
        "get_tracks",
        lambda: cast(TracksBoard, board).get_tracks(),
    )


def board_vias(board: object) -> list[object]:
    return _read_collection(
        "vias",
        "get_vias",
        lambda: cast(ViasBoard, board).get_vias(),
    )


def board_footprints(board: object) -> list[object]:
    return _read_collection(
        "footprints",
        "get_footprints",
        lambda: cast(FootprintsBoard, board).get_footprints(),
    )


def board_pads(board: object) -> list[object]:
    return _read_collection(
        "pads",
        "get_pads",
        lambda: cast(PadsBoard, board).get_pads(),
    )


def board_zones(board: object) -> list[object]:
    return _read_collection(
        "zones",
        "get_zones",
        lambda: cast(ZonesBoard, board).get_zones(),
    )


def board_shapes(board: object) -> list[object]:
    return _read_collection(
        "shapes",
        "get_shapes",
        lambda: cast(ShapesBoard, board).get_shapes(),
    )


def board_nets(board: object) -> list[object]:
    return _read_collection(
        "nets",
        "get_nets",
        lambda: cast(NetsBoard, board).get_nets(),
    )


def board_nets_filtered(board: object, *, netclass_filter: object | None) -> list[object]:
    return _read_collection(
        "nets",
        "get_nets",
        lambda: cast(FilteredNetsBoard, board).get_nets(netclass_filter=netclass_filter),
    )
