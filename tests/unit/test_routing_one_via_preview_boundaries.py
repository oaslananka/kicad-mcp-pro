"""Read-only through-via preview: accept only an unchanged, unambiguous KiCad board.

The real native CLI and GUI acceptance is kept in opt-in integration tests.
These tests exercise the boundary with typed, inert in-memory pad geometry.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from kipy.geometry import Vector2
from kipy.proto.board.board_types_pb2 import BoardLayer

from kicad_mcp.routing.path_planner import CircleObstacle
from kicad_mcp.tools import routing_one_via as adapter


def _arrange(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[SimpleNamespace, SimpleNamespace, SimpleNamespace, dict[str, int]]:
    front = BoardLayer.BL_F_Cu
    back = BoardLayer.BL_B_Cu

    def pad(identity: str, net: str, x: float, layers: list[int]) -> SimpleNamespace:
        return SimpleNamespace(
            number="1",
            id=SimpleNamespace(value=identity),
            net=SimpleNamespace(name=net),
            padstack=SimpleNamespace(layers=layers),
            position=Vector2.from_xy_mm(x, 10),
        )

    source = pad("source-id", "MID", 10, [front])
    target = pad("target-id", "MID", 20, [back])
    board = SimpleNamespace(
        get_as_string=lambda: "(kicad_pcb fixed revision)",
        get_enabled_layers=lambda: [front, back],
    )
    calls = {"snapshots": 0, "planner": 0}
    monkeypatch.setattr(adapter, "get_board", lambda: board)
    monkeypatch.setattr(adapter, "board_pads", lambda _board: [])
    monkeypatch.setattr(adapter, "board_footprints", lambda _board: [])
    monkeypatch.setattr(
        adapter,
        "map_pads_to_footprints",
        lambda *_args: [
            SimpleNamespace(reference="R1", pad=source),
            SimpleNamespace(reference="R2", pad=target),
        ],
    )

    def snapshot(
        _board: object,
        layer: str,
        excluded: frozenset[str],
        *,
        expected_endpoint_count: int,
        require_outline: bool,
    ) -> tuple:
        calls["snapshots"] += 1
        assert layer in {"F_Cu", "B_Cu"}
        assert len(excluded) == expected_endpoint_count == 1
        assert require_outline is True
        return ()

    monkeypatch.setattr(adapter, "snapshot_route_obstacles", snapshot)
    return source, target, board, calls


def _preview(**kwargs: object) -> dict[str, object]:
    return json.loads(adapter._preview_one_via("R1", "1", "R2", "1", **kwargs))


def test_candidate_is_read_only_deterministic_and_fully_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _source, _target, _board, calls = _arrange(monkeypatch)
    before = _preview()
    after = _preview()
    assert before == after
    assert before["status"] == "candidate"
    assert before["candidateOnly"] is True
    assert before["noBoardMutation"] is True
    assert before["drcVerified"] is False
    assert len(before["candidateId"]) == 64
    assert before["net"] == "MID"
    assert [track["layer"] for track in before["segments"]] == ["F_Cu", "B_Cu"]
    assert before["throughVia"]["net_name"] == "MID"
    assert before["throughVia"]["diameter_mm"] == 0.8
    assert before["geometry"]["viaCount"] == 1
    assert "NOT certified" in before["warning"]
    assert calls["snapshots"] == 4


@pytest.mark.parametrize(
    ("fault", "reason"),
    [
        ("missing", "missing"),
        ("same_identity", "identities"),
        ("empty_identity", "identities"),
        ("missing_net", "named net"),
        ("mismatch_net", "named net"),
        ("disabled_layer", "enabled"),
        ("common_layer", "distinct"),
        ("wrong_target", "distinct"),
        ("bad_board", "snapshot"),
        ("new_revision", "revision changed"),
        ("non_finite", "non-finite"),
        ("too_thick", "diameter"),
        ("blocked_via", "collision-free"),
        ("unreadable", "unavailable"),
    ],
)
def test_preview_refuses_unsafe_inputs_and_incomplete_live_state(
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
    reason: str,
) -> None:
    source, target, board, calls = _arrange(monkeypatch)
    if fault == "missing":
        monkeypatch.setattr(adapter, "map_pads_to_footprints", lambda *_args: [])
    elif fault == "same_identity":
        target.id.value = source.id.value
    elif fault == "empty_identity":
        source.id.value = ""
    elif fault == "missing_net":
        source.net.name = ""
    elif fault == "mismatch_net":
        target.net.name = "OTHER"
    elif fault == "disabled_layer":
        board.get_enabled_layers = lambda: [BoardLayer.BL_F_Cu]
    elif fault == "common_layer":
        target.padstack.layers.append(BoardLayer.BL_F_Cu)
    elif fault == "wrong_target":
        target.padstack.layers = [BoardLayer.BL_F_Cu]
    elif fault == "bad_board":
        board.get_as_string = lambda: "(not_kicad_pcb)"
    elif fault == "new_revision":
        counter = iter(["(kicad_pcb first)", "(kicad_pcb second)"])
        board.get_as_string = lambda: next(counter)
    elif fault == "blocked_via":
        monkeypatch.setattr(
            adapter,
            "snapshot_route_obstacles",
            lambda _board, layer, *_args, **_kwargs: (
                (CircleObstacle(15, 10, 15),) if layer == "F_Cu" else ()
            ),
        )
    elif fault == "unreadable":
        monkeypatch.setattr(
            adapter,
            "get_board",
            lambda: (_ for _ in ()).throw(AttributeError("board unavailable")),
        )
    arguments = (
        {"width_mm": float("nan")}
        if fault == "non_finite"
        else {"width_mm": 1.0}
        if fault == "too_thick"
        else {}
    )
    result = _preview(**arguments)
    assert result["status"] == "refused"
    assert result["candidateOnly"] is True
    assert reason.lower() in result["reason"].lower()
    if fault in {
        "missing",
        "same_identity",
        "empty_identity",
        "missing_net",
        "mismatch_net",
        "disabled_layer",
        "common_layer",
        "wrong_target",
        "bad_board",
        "unreadable",
    }:
        assert calls["snapshots"] == 0


@pytest.mark.parametrize(
    ("start_layer", "end_layer", "reason"),
    [
        ("F_Cu", "In1_Cu", "outer layer"),
        ("F_Cu", "F_Cu", "outer layer"),
        ("In1_Cu", "B_Cu", "outer layer"),
    ],
)
def test_preview_refuses_inner_and_same_layer_transitions(
    monkeypatch: pytest.MonkeyPatch, start_layer: str, end_layer: str, reason: str
) -> None:
    _arrange(monkeypatch)
    result = _preview(start_layer=start_layer, end_layer=end_layer)
    assert result["status"] == "refused"
    assert reason in result["reason"]


def test_reverse_back_to_front_transition_is_supported_when_pads_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, target, _board, _calls = _arrange(monkeypatch)
    source.padstack.layers = [BoardLayer.BL_B_Cu]
    target.padstack.layers = [BoardLayer.BL_F_Cu]
    result = _preview(start_layer="B_Cu", end_layer="F_Cu")
    assert result["status"] == "candidate"
    assert [track["layer"] for track in result["segments"]] == ["B_Cu", "F_Cu"]
    assert result["throughVia"]["net_name"] == "MID"
