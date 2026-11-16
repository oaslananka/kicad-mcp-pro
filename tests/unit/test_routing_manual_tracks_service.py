from __future__ import annotations

from types import SimpleNamespace

import pytest
from kipy.board_types import Net
from kipy.geometry import Vector2

from kicad_mcp.pcb.pad_mapping import MappedPad
from kicad_mcp.routing.manual_tracks import RoutingManualTrackService, TrackSpec


def _pad(reference: str, number: str, x_mm: float, y_mm: float, net_name: str) -> MappedPad:
    net = Net()
    net.name = net_name
    return MappedPad(
        pad=SimpleNamespace(
            number=number,
            position=Vector2.from_xy_mm(x_mm, y_mm),
            net=net,
        ),
        pad_id=None,
        reference=reference,
    )


def _service(
    pads: list[MappedPad] | None = None,
    *,
    layer_validator=None,
) -> tuple[RoutingManualTrackService, list[tuple[str, list[TrackSpec]]]]:
    writes: list[tuple[str, list[TrackSpec]]] = []

    def write_tracks(operation: str, specs: list[TrackSpec]) -> None:
        writes.append((operation, specs))

    service = RoutingManualTrackService(
        list_pads=lambda: list(pads or []),
        write_tracks=write_tracks,
        validate_layer=layer_validator or (lambda _start, _end, _layer: True),
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
        _pad("U2", "3", 5.0, 8.0, "DATA"),
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

    service = RoutingManualTrackService(
        list_pads=lambda: pads,
        write_tracks=failed_write,
        validate_layer=lambda _start, _end, _layer: True,
    )
    with pytest.raises(RuntimeError, match="KiCad mutation was rejected"):
        service.route_single(1.0, 2.0, 5.0, 8.0)
    with pytest.raises(RuntimeError, match="KiCad mutation was rejected"):
        service.route_pad_to_pad("R1", "1", "U2", "3")


def test_pad_to_pad_resolves_live_kicad_kiid_parent_via_existing_mapping() -> None:
    """Actual KiCad 10 pad.parent is a KIID, not an embedded footprint."""
    from kicad_mcp.pcb.pad_mapping import map_pads_to_footprints

    def native_pad(ident: str, owner: str, pad_number: str, x: float) -> SimpleNamespace:
        net = Net()
        net.name = "MID"
        return SimpleNamespace(
            id=SimpleNamespace(value=ident),
            parent=SimpleNamespace(value=owner),
            number=pad_number,
            position=Vector2.from_xy_mm(x, 10.0),
            net=net,
        )

    first = native_pad("pad-a", "footprint-a", "2", 10.95)
    second = native_pad("pad-b", "footprint-b", "1", 19.05)

    def footprint(ident: str, reference: str, pad: SimpleNamespace) -> SimpleNamespace:
        return SimpleNamespace(
            id=SimpleNamespace(value=ident),
            reference_field=SimpleNamespace(text=SimpleNamespace(value=reference)),
            definition=SimpleNamespace(pads=[pad]),
        )

    mapped = map_pads_to_footprints(
        [first, second],
        [footprint("footprint-a", "R1", first), footprint("footprint-b", "R2", second)],
    )
    assert [item.reference for item in mapped] == ["R1", "R2"]
    service, writes = _service(mapped)

    result = service.route_pad_to_pad("R1", "2", "R2", "1")

    assert "Orthogonal single-segment track write submitted" in result
    assert "R1:2 -> R2:1" in result
    assert writes == [
        ("route_from_pad_to_pad", [TrackSpec(10.95, 10.0, 19.05, 10.0, "F_Cu", 0.25, "MID")])
    ]


@pytest.mark.parametrize(
    ("source_net", "target_net", "message"),
    [
        ("MID", "OTHER", "different nets"),
        ("", "MID", "named net"),
        ("MID", "", "named net"),
    ],
)
def test_pad_to_pad_rejects_cross_net_or_unassigned_pad_without_writing(
    source_net: str,
    target_net: str,
    message: str,
) -> None:
    service, writes = _service(
        [
            _pad("R1", "1", 1.0, 2.0, source_net),
            _pad("R2", "1", 5.0, 2.0, target_net),
        ]
    )

    result = service.route_pad_to_pad("R1", "1", "R2", "1")

    assert message in result
    assert writes == []


def test_pad_to_pad_rejects_overlapping_endpoints_without_writing() -> None:
    service, writes = _service([_pad("R1", "1", 1.0, 2.0, "MID"), _pad("R2", "2", 1.0, 2.0, "MID")])

    assert "overlap" in service.route_pad_to_pad("R1", "1", "R2", "2")
    assert writes == []


def test_pad_to_pad_vertical_route_uses_one_nonzero_segment() -> None:
    service, writes = _service([_pad("R1", "1", 1.0, 2.0, "MID"), _pad("R2", "2", 1.0, 8.0, "MID")])

    result = service.route_pad_to_pad("R1", "1", "R2", "2")

    assert "single-segment" in result
    assert writes == [
        ("route_from_pad_to_pad", [TrackSpec(1.0, 2.0, 1.0, 8.0, "F_Cu", 0.25, "MID")])
    ]


def test_pad_to_pad_unmapped_identity_fails_closed() -> None:
    service, writes = _service(
        [
            MappedPad(pad=_pad("R1", "1", 1.0, 2.0, "MID").pad, pad_id=None, reference=None),
            _pad("R2", "2", 5.0, 2.0, "MID"),
        ]
    )

    assert "not found" in service.route_pad_to_pad("R1", "1", "R2", "2")
    assert writes == []


def test_pad_to_pad_rejects_wrong_copper_layer_without_writing() -> None:
    service, writes = _service(
        [_pad("R1", "1", 1.0, 2.0, "MID"), _pad("R2", "1", 5.0, 2.0, "MID")],
        layer_validator=lambda _first, _second, layer: layer == "F_Cu",
    )

    result = service.route_pad_to_pad("R1", "1", "R2", "1", "B_Cu")

    assert "layer" in result.lower()
    assert "no track created" in result
    assert writes == []
