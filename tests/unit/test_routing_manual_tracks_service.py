from __future__ import annotations

from types import SimpleNamespace
from typing import cast

import pytest
from kipy.board_types import Net
from kipy.geometry import Vector2

from kicad_mcp.models.common import _PadLike
from kicad_mcp.routing.manual_tracks import RoutingManualTrackService, TrackSpec


def _pad(reference: str, number: str, x_mm: float, y_mm: float, net_name: str) -> _PadLike:
    net = Net()
    net.name = net_name
    return cast(
        _PadLike,
        SimpleNamespace(
            parent=SimpleNamespace(
                reference_field=SimpleNamespace(
                    text=SimpleNamespace(value=reference),
                )
            ),
            number=number,
            position=Vector2.from_xy_mm(x_mm, y_mm),
            net=net,
        ),
    )


def _service(
    pads: list[_PadLike] | None = None,
) -> tuple[RoutingManualTrackService, list[tuple[str, list[TrackSpec]]]]:
    writes: list[tuple[str, list[TrackSpec]]] = []

    def write_tracks(operation: str, specs: list[TrackSpec]) -> None:
        writes.append((operation, specs))

    service = RoutingManualTrackService(
        list_pads=lambda: list(pads or []),
        write_tracks=write_tracks,
    )
    return service, writes


def test_route_single_preserves_track_spec_and_response() -> None:
    service, writes = _service()

    result = service.route_single(
        1.0,
        2.0,
        5.0,
        8.0,
        "F_Cu",
        0.3,
        "USB_D+",
    )

    assert result == (
        "Track segment write submitted. Board persistence and electrical connectivity "
        "UNVERIFIED; verify with DRC and project_quality_gate."
    )
    assert writes == [
        (
            "route_single_track",
            [
                TrackSpec(
                    x1_mm=1.0,
                    y1_mm=2.0,
                    x2_mm=5.0,
                    y2_mm=8.0,
                    layer="F_Cu",
                    width_mm=0.3,
                    net_name="USB_D+",
                )
            ],
        )
    ]


def test_route_single_preserves_empty_net_behavior() -> None:
    service, writes = _service()

    service.route_single(0.0, 0.0, 1.0, 1.0)

    assert writes[0][1][0].net_name == ""


def test_route_pad_to_pad_preserves_orthogonal_geometry_and_response() -> None:
    pads = [
        _pad("R1", "1", 1.0, 2.0, "DATA"),
        _pad("U2", "3", 5.0, 8.0, ""),
    ]
    service, writes = _service(pads)

    result = service.route_pad_to_pad("R1", "1", "U2", "3", "F_Cu", 0.25)

    assert result == (
        "Orthogonal two-segment track write submitted for R1:1 -> U2:3. "
        "Board persistence and electrical connectivity UNVERIFIED; "
        "verify with DRC and project_quality_gate."
    )
    assert writes == [
        (
            "route_from_pad_to_pad",
            [
                TrackSpec(1.0, 2.0, 5.0, 2.0, "F_Cu", 0.25, "DATA"),
                TrackSpec(5.0, 2.0, 5.0, 8.0, "F_Cu", 0.25, "DATA"),
            ],
        )
    ]


def test_route_pad_to_pad_preserves_missing_pad_message_without_write() -> None:
    service, writes = _service([_pad("R1", "1", 1.0, 2.0, "DATA")])

    result = service.route_pad_to_pad("R1", "1", "U2", "3")

    assert result == "One or both pads were not found on the active board."
    assert writes == []


def test_live_write_failure_does_not_claim_route_success() -> None:
    pads = [
        _pad("R1", "1", 1.0, 2.0, "DATA"),
        _pad("U2", "3", 5.0, 8.0, "DATA"),
    ]

    def failed_write(_operation: str, _specs: list[TrackSpec]) -> None:
        raise RuntimeError("KiCad mutation was rejected")

    service = RoutingManualTrackService(list_pads=lambda: pads, write_tracks=failed_write)
    with pytest.raises(RuntimeError, match="KiCad mutation was rejected"):
        service.route_single(1.0, 2.0, 5.0, 8.0)
    with pytest.raises(RuntimeError, match="KiCad mutation was rejected"):
        service.route_pad_to_pad("R1", "1", "U2", "3")
