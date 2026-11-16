"""Reuse already-present same-net copper instead of publishing duplicate traces."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from kipy.board_types import BoardLayer, Net, Track
from kipy.geometry import Vector2

from kicad_mcp.pcb.pad_mapping import MappedPad
from kicad_mcp.tools import routing_manual_tracks as adapter


def _track(
    a: tuple[float, float],
    b: tuple[float, float],
    *,
    net: str = "+5V",
    width: float = 0.5,
    layer: int = BoardLayer.BL_F_Cu,
) -> Track:
    item = Track()
    item.start = Vector2.from_xy_mm(*a)
    item.end = Vector2.from_xy_mm(*b)
    item.layer = layer
    item.width = round(width * 1_000_000)
    native_net = Net()
    native_net.name = net
    item.net = native_net
    return item


def _arrange(
    monkeypatch: pytest.MonkeyPatch,
    tracks: list[Track],
) -> None:
    def mapped(ref: str, number: str, pos: tuple[float, float], identity: str) -> MappedPad:
        return MappedPad(
            pad=SimpleNamespace(
                number=number,
                id=SimpleNamespace(value=identity),
                net=SimpleNamespace(name="+5V"),
                position=Vector2.from_xy_mm(*pos),
            ),
            pad_id=identity,
            reference=ref,
        )

    board = SimpleNamespace(
        get_as_string=lambda: "(kicad_pcb fixed-test)",
        get_tracks=lambda: tracks,
    )
    monkeypatch.setattr(adapter, "get_board", lambda: board)
    monkeypatch.setattr(adapter, "board_pads", lambda _board: [])
    monkeypatch.setattr(adapter, "board_footprints", lambda _board: [])
    monkeypatch.setattr(
        adapter,
        "map_pads_to_footprints",
        lambda *_args: [
            mapped("C1", "1", (1.0, 1.0), "pad-one"),
            mapped("U2", "1", (5.0, 2.0), "pad-two"),
        ],
    )
    monkeypatch.setattr(adapter, "_validate_endpoint_layer", lambda *_args: True)
    monkeypatch.setattr(adapter, "snapshot_route_obstacles", lambda *_args, **_kwargs: ())
    monkeypatch.setattr(
        adapter,
        "plan_hv45_path",
        lambda *_args, **_kwargs: ((1.0, 1.0), (2.0, 2.0), (5.0, 2.0)),
    )


def _preview() -> dict:
    return json.loads(adapter._preview_route_between_pads("C1", "1", "U2", "1", "F_Cu", 0.5, 0.2))


def test_reuses_identical_same_net_existing_segment_without_rewriting_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _arrange(monkeypatch, [_track((2.0, 2.0), (1.0, 1.0))])
    candidate = _preview()

    assert candidate["status"] == "candidate"
    assert candidate["reusedExistingSegments"] == 1
    assert candidate["path_mm"] == [[1.0, 1.0], [2.0, 2.0], [5.0, 2.0]]
    assert len(candidate["segments"]) == 1
    assert candidate["segments"][0]["x1_mm"] == 2.0
    assert candidate["segments"][0]["x2_mm"] == 5.0


@pytest.mark.parametrize(
    ("net", "width", "layer"),
    [
        ("GND", 0.5, BoardLayer.BL_F_Cu),
        ("+5V", 0.3, BoardLayer.BL_F_Cu),
        ("+5V", 0.5, BoardLayer.BL_B_Cu),
    ],
)
def test_does_not_reuse_other_net_narrower_or_other_layer_copper(
    monkeypatch: pytest.MonkeyPatch,
    net: str,
    width: float,
    layer: int,
) -> None:
    _arrange(monkeypatch, [_track((1.0, 1.0), (2.0, 2.0), net=net, width=width, layer=layer)])
    candidate = _preview()

    assert candidate["status"] == "candidate"
    assert candidate["reusedExistingSegments"] == 0
    assert len(candidate["segments"]) == 2


def test_entirely_existing_route_is_a_read_only_noop_not_an_applied_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _arrange(
        monkeypatch,
        [
            _track((1.0, 1.0), (2.0, 2.0)),
            _track((2.0, 2.0), (5.0, 2.0)),
        ],
    )
    result = _preview()

    assert result["status"] == "refused"
    assert result["candidateOnly"] is True
    assert "already" in result["reason"].lower()
    assert "candidateId" not in result
