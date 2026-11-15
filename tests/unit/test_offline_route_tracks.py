"""Disposable PCB routing should use validated S-expressions, never the deprecated SWIG API."""

from __future__ import annotations

from pathlib import Path

import pytest
from sexpdata import loads

from kicad_mcp.routing.manual_tracks import TrackSpec, ViaSpec

_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "benchmark_projects"
    / "fail_dirty_transfer_wrong_pad_nets"
    / "demo.kicad_pcb"
)


def _tracks() -> list[TrackSpec]:
    return [
        TrackSpec(10.95, 10, 15, 10, "F_Cu", 0.25, "MID"),
        TrackSpec(15, 10, 19.05, 10, "B_Cu", 0.25, "MID"),
    ]


def _children(node: list[object], keyword: str) -> list[list[object]]:
    return [
        item for item in node[1:] if isinstance(item, list) and item and str(item[0]) == keyword
    ]


def test_render_disposable_candidate_preserves_input_and_adds_one_via() -> None:
    from kicad_mcp.pcb.offline_route_tracks import render_candidate_board

    original = _FIXTURE.read_text(encoding="utf-8")
    candidate = render_candidate_board(original, _tracks(), ViaSpec(15, 10, 0.8, 0.4, "MID"))
    assert original == _FIXTURE.read_text(encoding="utf-8")
    parsed = loads(candidate)
    assert str(parsed[0]) == "kicad_pcb"
    segments = _children(parsed, "segment")
    vias = _children(parsed, "via")
    assert len(segments) == 2
    assert len(vias) == 1
    assert [_children(segment, "layer")[0][1] for segment in segments] == ["F.Cu", "B.Cu"]
    assert [_children(segment, "net")[0][1] for segment in segments] == ["MID", "MID"]
    assert _children(vias[0], "net")[0][1] == "MID"
    assert _children(vias[0], "size")[0][1] == 0.8
    assert _children(vias[0], "drill")[0][1] == 0.4
    assert _children(vias[0], "layers")[0][1:] == ["F.Cu", "B.Cu"]
    assert _children(vias[0], "uuid")


def test_renderer_refuses_net_not_on_original_board() -> None:
    from kicad_mcp.pcb.offline_route_tracks import render_candidate_board

    original = _FIXTURE.read_text(encoding="utf-8")
    _checked_args = (original, [TrackSpec(1, 1, 5, 5, "F_Cu", 0.25, "INJECTED_NET")])
    with pytest.raises(ValueError, match="net"):
        render_candidate_board(*_checked_args)


def test_renderer_refuses_malformed_board_and_nonfinite_geometry() -> None:
    from kicad_mcp.pcb.offline_route_tracks import render_candidate_board

    original = _FIXTURE.read_text(encoding="utf-8")
    _checked_args = ("(kicad_pcb not-closed", _tracks())
    with pytest.raises(ValueError, match="board"):
        render_candidate_board(*_checked_args)
    _checked_args = (original, [TrackSpec(float("nan"), 1, 5, 5, "F_Cu", 0.25, "MID")])
    with pytest.raises(ValueError, match="geometry"):
        render_candidate_board(*_checked_args)


def test_renderer_refuses_unsupported_layer_not_quoted_into_board() -> None:
    from kicad_mcp.pcb.offline_route_tracks import render_candidate_board

    original = _FIXTURE.read_text(encoding="utf-8")
    _checked_args = (original, [TrackSpec(1, 1, 5, 5, 'F_Cu) (net "BAD")', 0.25, "MID")])
    with pytest.raises(ValueError, match="layer"):
        render_candidate_board(*_checked_args)


def test_candidate_rejects_unicode_digit_layer() -> None:
    from kicad_mcp.pcb.offline_route_tracks import render_candidate_board

    original = _FIXTURE.read_text(encoding="utf-8")
    with pytest.raises(ValueError, match="copper layer"):
        render_candidate_board(original, [TrackSpec(1, 1, 5, 5, "In2?_Cu", 0.25, "MID")])
