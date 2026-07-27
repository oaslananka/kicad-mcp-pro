from __future__ import annotations

from collections.abc import Iterable
from types import SimpleNamespace

from kicad_mcp.models.verdict import VerdictReport
from kicad_mcp.pcb.board_inspection import PcbBoardInspectionService


class FakeConnectionError(Exception):
    pass


def _paginate[T](items: Iterable[T], *, page: int, page_size: int) -> tuple[list[T], int, int]:
    collected = list(items)
    total = len(collected)
    page_count = max((total + page_size - 1) // page_size, 1) if total else 0
    start = (page - 1) * page_size
    return collected[start : start + page_size], total, page_count


def _limit[T](items: Iterable[T]) -> tuple[list[T], int]:
    collected = list(items)
    return collected[:2], len(collected)


def _report(
    *,
    text: str,
    source: str,
    tracks: int = 0,
    vias: int = 0,
    footprints: int = 0,
    zones: int = 0,
    nets: int = 0,
    shapes: int = 0,
) -> VerdictReport:
    return VerdictReport(
        text=text,
        summary=f"summary::{source}",
        metadata={
            "source": source,
            "tracks": tracks,
            "vias": vias,
            "footprints": footprints,
            "zones": zones,
            "nets": nets,
            "shapes": shapes,
        },
    )


def _tracks_fallback(
    ipc_error: BaseException,
    *,
    page: int,
    page_size: int,
    filter_layer: str,
    filter_net: str,
) -> str:
    return (
        f"tracks::{ipc_error}::{{'page': {page}, 'page_size': {page_size}, "
        f"'filter_layer': '{filter_layer}', 'filter_net': '{filter_net}'}}"
    )


def _footprints_fallback(
    ipc_error: BaseException,
    *,
    page: int,
    page_size: int,
    filter_layer: str,
) -> str:
    return (
        f"footprints::{ipc_error}::{{'page': {page}, 'page_size': {page_size}, "
        f"'filter_layer': '{filter_layer}'}}"
    )


def _empty() -> list[object]:
    return []


def _summary_nets(*, netclass_filter: object | None) -> list[object]:
    del netclass_filter
    return [1, 2, 3, 4]


def _service(board: object) -> PcbBoardInspectionService:
    return PcbBoardInspectionService(
        get_board=lambda: board,
        file_backed_board_summary=lambda exc: VerdictReport(text=f"summary::{exc}"),
        board_summary_report=_report,
        file_backed_tracks=_tracks_fallback,
        file_backed_vias=lambda exc: f"vias::{exc}",
        file_backed_footprints=_footprints_fallback,
        paginate=_paginate,
        limit_items=_limit,
        matches_layer_filter=lambda layer, wanted: not wanted or str(layer) == wanted,
        with_pcb_diagnostics=lambda message: f"diag::{message}",
        layer_name=lambda layer: {0: "F_Cu", 31: "B_Cu"}.get(layer, str(layer)),
        via_type_name=lambda value: {0: "THROUGH"}.get(value, str(value)),
        format_selection_id=lambda item: str(getattr(item, "uid", "")),
        coord_nm=lambda point, axis: int(getattr(point, axis)),
        nm_to_mm=lambda value: value / 1_000_000,
        connection_errors=(FakeConnectionError, OSError),
    )


def test_board_summary_preserves_live_counts_and_file_fallback() -> None:
    board = SimpleNamespace(
        get_tracks=lambda: [1, 2],
        get_footprints=lambda: [1],
        get_vias=lambda: [1, 2, 3],
        get_zones=lambda: [1],
        get_nets=_summary_nets,
        get_shapes=lambda: [1, 2],
    )
    report = _service(board).get_board_summary()
    assert report.text == "\n".join(
        [
            "Board summary:",
            "- Source: live-gui",
            "- Tracks: 2",
            "- Vias: 3",
            "- Footprints: 1",
            "- Zones: 1",
            "- Nets: 4",
            "- Shapes: 2",
        ]
    )
    assert report.metadata == {
        "source": "live-gui",
        "tracks": 2,
        "vias": 3,
        "footprints": 1,
        "zones": 1,
        "nets": 4,
        "shapes": 2,
    }

    def fail() -> object:
        raise FakeConnectionError("offline")

    service = _service(SimpleNamespace())
    object.__setattr__(service, "get_board", fail)
    assert service.get_board_summary().text == "summary::offline"


def test_tracks_preserve_filters_pagination_formatting_and_fallback() -> None:
    tracks = [
        SimpleNamespace(
            start=SimpleNamespace(x=1_000_000, y=2_000_000),
            end=SimpleNamespace(x=3_000_000, y=4_000_000),
            layer=0,
            width=250_000,
            net=SimpleNamespace(name="GND"),
            uid="track-1",
        ),
        SimpleNamespace(
            start=SimpleNamespace(x=5_000_000, y=6_000_000),
            end=SimpleNamespace(x=7_000_000, y=8_000_000),
            layer=31,
            width=300_000,
            net=SimpleNamespace(name="VCC"),
            uid="track-2",
        ),
    ]
    service = _service(SimpleNamespace(get_tracks=lambda: tracks))
    assert service.get_tracks(page=1, page_size=1, filter_layer="0", filter_net="gnd") == "\n".join(
        [
            "Tracks (1 total):",
            "- Source: live-gui",
            "- Page 1/1 | Showing 1",
            "1. (1.00, 2.00) -> (3.00, 4.00) mm layer=F_Cu width=0.250 mm net=GND id=track-1",
        ]
    )
    assert service.get_tracks(page=2, page_size=1) == "\n".join(
        [
            "Tracks (2 total):",
            "- Source: live-gui",
            "- Page 2/2 | Showing 1",
            "1. (5.00, 6.00) -> (7.00, 8.00) mm layer=B_Cu width=0.300 mm net=VCC id=track-2",
        ]
    )
    assert service.get_tracks(page=3, page_size=1) == (
        "Track page 3 is out of range. Available pages: 1-2."
    )
    assert service.get_tracks(filter_net="missing") == (
        "diag::No tracks match the supplied filters on the active board."
    )
    assert _service(SimpleNamespace(get_tracks=_empty)).get_tracks() == (
        "diag::No tracks are present on the active board."
    )

    def fail() -> object:
        raise FakeConnectionError("offline")

    fallback = _service(SimpleNamespace())
    object.__setattr__(fallback, "get_board", fail)
    assert fallback.get_tracks(page=2, page_size=5, filter_layer="F_Cu", filter_net="GND") == (
        "tracks::offline::{'page': 2, 'page_size': 5, 'filter_layer': 'F_Cu', 'filter_net': 'GND'}"
    )


def test_vias_preserve_limit_formatting_empty_and_fallback() -> None:
    vias = [
        SimpleNamespace(
            position=SimpleNamespace(x=1_500_000, y=-2_500_000),
            diameter=800_000,
            drill_diameter=400_000,
            net=SimpleNamespace(name="GND"),
            type=0,
        ),
        SimpleNamespace(
            position=SimpleNamespace(x=2_000_000, y=3_000_000),
            diameter=900_000,
            drill_diameter=450_000,
            net=SimpleNamespace(name=""),
            type=0,
        ),
        SimpleNamespace(
            position=SimpleNamespace(x=0, y=0),
            diameter=1_000_000,
            drill_diameter=500_000,
            net=SimpleNamespace(name="VCC"),
            type=0,
        ),
    ]
    assert _service(SimpleNamespace(get_vias=lambda: vias)).get_vias() == "\n".join(
        [
            "Vias (3 total):",
            "- Source: live-gui",
            "1. (1.50, -2.50) mm diameter=0.800 mm drill=0.400 mm net=GND type=THROUGH",
            "2. (2.00, 3.00) mm diameter=0.900 mm drill=0.450 mm net=(none) type=THROUGH",
        ]
    )
    assert _service(SimpleNamespace(get_vias=_empty)).get_vias() == (
        "diag::No vias are present on the active board."
    )

    def fail() -> object:
        raise FakeConnectionError("offline")

    fallback = _service(SimpleNamespace())
    object.__setattr__(fallback, "get_board", fail)
    assert fallback.get_vias() == "vias::offline"


def test_footprints_preserve_filter_pagination_formatting_and_fallback() -> None:
    footprints = [
        SimpleNamespace(
            reference_field=SimpleNamespace(text=SimpleNamespace(value="U1")),
            value_field=SimpleNamespace(text=SimpleNamespace(value="MCU")),
            position=SimpleNamespace(x=1_000_000, y=2_000_000),
            layer=0,
            uid="fp-1",
        ),
        SimpleNamespace(
            reference_field=SimpleNamespace(text=SimpleNamespace(value="R1")),
            value_field=SimpleNamespace(text=SimpleNamespace(value="10k")),
            position=SimpleNamespace(x=3_000_000, y=4_000_000),
            layer=31,
            uid="fp-2",
        ),
    ]
    service = _service(SimpleNamespace(get_footprints=lambda: footprints))
    assert service.get_footprints(page=1, page_size=1, filter_layer="31") == "\n".join(
        [
            "Footprints (1 total):",
            "- Source: live-gui",
            "- Page 1/1 | Showing 1",
            "- R1 (10k) @ (3.00, 4.00) mm layer=B_Cu id=fp-2",
        ]
    )
    assert service.get_footprints(page=3, page_size=1) == (
        "Footprint page 3 is out of range. Available pages: 1-2."
    )
    assert service.get_footprints(filter_layer="missing") == (
        "diag::No footprints match the supplied layer filter on the active board."
    )
    assert _service(SimpleNamespace(get_footprints=_empty)).get_footprints() == (
        "diag::No footprints are present on the active board."
    )

    def fail() -> object:
        raise FakeConnectionError("offline")

    fallback = _service(SimpleNamespace())
    object.__setattr__(fallback, "get_board", fail)
    assert fallback.get_footprints(page=2, page_size=10, filter_layer="B_Cu") == (
        "footprints::offline::{'page': 2, 'page_size': 10, 'filter_layer': 'B_Cu'}"
    )
