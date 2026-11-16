"""User-facing USB P/N coupled preview: stable pad identity and read-only DRC gating.

No KiCad editor or user files are accessed. Geometry is planned by the real,
pure coupled-pair planner after an in-memory native endpoint mapping.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from kipy.geometry import Vector2

from kicad_mcp.routing.path_planner import CircleObstacle
from kicad_mcp.tools import routing_coupled_pair as adapter

_PADS = (
    ("J1", "USB_D_P", 0, 0),
    ("J2", "USB_D_P", 8, 0),
    ("J3", "USB_D_N", 0, 0.75),
    ("J4", "USB_D_N", 8, 0.75),
)


def _args() -> dict[str, object]:
    return {
        "p_ref1": "J1",
        "p_pad1": "1",
        "p_ref2": "J2",
        "p_pad2": "1",
        "n_ref1": "J3",
        "n_pad1": "1",
        "n_ref2": "J4",
        "n_pad2": "1",
        "layer": "F_Cu",
        "width_mm": 0.25,
        "gap_mm": 0.5,
        "clearance_mm": 0.2,
        "max_skew_mm": 0.1,
    }


def _arrange(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[list[SimpleNamespace], SimpleNamespace, dict[str, int]]:
    pads = [
        SimpleNamespace(
            number="1",
            id=SimpleNamespace(value=f"{ref}.1"),
            net=SimpleNamespace(name=net),
            position=Vector2.from_xy_mm(x, y),
        )
        for ref, net, x, y in _PADS
    ]
    board = SimpleNamespace(
        get_as_string=lambda: "(kicad_pcb immutable board)", get_tracks=lambda: []
    )
    stats = {"snapshots": 0}
    monkeypatch.setattr(adapter, "get_board", lambda: board)
    monkeypatch.setattr(adapter, "board_pads", lambda _board: [])
    monkeypatch.setattr(adapter, "board_footprints", lambda _board: [])
    monkeypatch.setattr(
        adapter,
        "map_pads_to_footprints",
        lambda *_args: [
            SimpleNamespace(reference=ref, pad=pad)
            for pad, (ref, *_rest) in zip(pads, _PADS, strict=False)
        ],
    )
    monkeypatch.setattr(
        adapter,
        "_validate_endpoint_layer",
        lambda _a, _b, layer: layer == "F_Cu",
    )

    def snapshot(
        _board: object,
        layer: str,
        excluded: frozenset[str],
        *,
        require_outline: bool,
        expected_endpoint_count: int,
        routing_net: str,
    ) -> tuple:
        stats["snapshots"] += 1
        assert layer == "F_Cu"
        assert require_outline
        assert expected_endpoint_count == len(excluded) == 2
        assert routing_net in {"USB_D_P", "USB_D_N"}
        return ()

    monkeypatch.setattr(adapter, "snapshot_route_obstacles", snapshot)
    return pads, board, stats


def _preview(**overrides: object) -> dict[str, object]:
    return json.loads(adapter._preview_coupled_pair(**(_args() | overrides)))


def test_native_pad_mapping_creates_one_deterministic_read_only_pair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pads, board, stats = _arrange(monkeypatch)
    expected_text = board.get_as_string()
    first = _preview()
    second = _preview()
    assert first == second
    assert first["status"] == "candidate"
    assert first["candidateOnly"] is True
    assert first["drcVerified"] is False
    assert first["noBoardMutation"] is True
    assert len(first["candidateId"]) == 64
    assert first["netPlus"] == "USB_D_P"
    assert first["netMinus"] == "USB_D_N"
    assert first["positiveSegmentCount"] >= 1
    assert first["negativeSegmentCount"] >= 1
    assert first["geometry"]["skewMm"] <= 0.1
    assert "NOT verified" in first["warning"]
    assert stats["snapshots"] == 4
    assert board.get_as_string() == expected_text
    assert len(pads) == 4


@pytest.mark.parametrize(
    ("minus_start", "minus_end", "reversed_order", "start_spacing", "end_spacing"),
    [
        ((0.0, 0.75), (8.0, -0.75), True, 0.75, 0.75),
        ((0.0, 2.9), (8.0, 0.5), False, 2.9, 0.5),
    ],
)
def test_realistic_misaligned_pair_reports_pad_geometry_without_board_write(
    monkeypatch: pytest.MonkeyPatch,
    minus_start: tuple[float, float],
    minus_end: tuple[float, float],
    reversed_order: bool,
    start_spacing: float,
    end_spacing: float,
) -> None:
    pads, board, stats = _arrange(monkeypatch)
    pads[2].position = Vector2.from_xy_mm(*minus_start)
    pads[3].position = Vector2.from_xy_mm(*minus_end)
    original = board.get_as_string()
    result = _preview()

    assert result["status"] == "refused"
    assert result["candidateOnly"] is True
    assert "candidateId" not in result
    assert result["padGeometry"] == {
        "startPadSeparationMm": start_spacing,
        "endPadSeparationMm": end_spacing,
        "requestedCenterSpacingMm": 0.75,
        "offsetChangeMm": 1.5 if reversed_order else 2.4,
        "padOrderReversed": reversed_order,
    }
    assert result["blockerType"] == ("pad_order_reversal" if reversed_order else "fanout_required")
    if reversed_order:
        assert "pad order is reversed" in result["nextAction"]
        assert "layer transition" in result["nextAction"]
    else:
        assert "native differential-pair fanout" in result["nextAction"]
        assert "not a polarity swap" in result["nextAction"]
    assert "No physical signoff" in result["nextAction"]
    assert ("pad order reverses" in result["reason"]) is reversed_order
    assert stats["snapshots"] == (0 if reversed_order else 2)
    assert board.get_as_string() == original


def test_usb_connector_near_aligned_pads_generate_bounded_fanout_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pads, board, stats = _arrange(monkeypatch)
    pads[0].position = Vector2.from_xy_mm(0, 0)
    pads[1].position = Vector2.from_xy_mm(8, 0.02)
    pads[2].position = Vector2.from_xy_mm(0, 0.85)
    pads[3].position = Vector2.from_xy_mm(8, 0.88)
    original = board.get_as_string()

    result = _preview(width_mm=0.3, gap_mm=0.25)
    assert result["status"] == "candidate"
    assert result["candidateOnly"] is True
    assert result["drcVerified"] is False
    assert result["noBoardMutation"] is True
    assert len(result["candidateId"]) == 64
    assert result["positiveSegmentCount"] == 5
    assert result["negativeSegmentCount"] == 5
    assert result["geometry"]["minCopperGapMm"] >= 0.25 - 1e-5
    assert result["geometry"]["skewMm"] <= 0.1
    assert result["geometryScope"] == "candidate-tracks-only"
    assert "existing copper" in result["warning"]
    assert "total net delay" in result["warning"]
    assert stats["snapshots"] == 2
    assert board.get_as_string() == original


@pytest.mark.parametrize(
    ("complete", "reason"),
    [(True, "already exists"), (False, "overlaps existing")],
)
def test_coupled_pair_refuses_existing_copper_without_duplicate_preview(
    monkeypatch: pytest.MonkeyPatch, complete: bool, reason: str
) -> None:
    _pads, board, stats = _arrange(monkeypatch)
    board.get_tracks = lambda: [object()]
    monkeypatch.setattr(
        adapter,
        "_already_present_track",
        lambda spec, _existing: complete or spec.net_name == "USB_D_P",
    )
    original = board.get_as_string()
    result = _preview()

    assert result["status"] == "refused"
    assert result["candidateOnly"] is True
    assert reason in result["reason"]
    assert "candidateId" not in result
    assert stats["snapshots"] == 2
    assert board.get_as_string() == original


@pytest.mark.parametrize(
    ("fault", "message"),
    [
        ("bad_snapshot", "serialization unavailable"),
        ("missing_pad", "were not found"),
        ("duplicate_identity", "unique"),
        ("blank_identity", "unique"),
        ("mismatched_positive_net", "each share"),
        ("mismatched_negative_net", "each share"),
        ("missing_negative_net", "each share"),
        ("same_net", "distinct named nets"),
        ("swapped_usb_polarity", "USB net polarity labels"),
        ("unsupported_copper", "share the requested"),
        ("foreign_obstacle", "obstacle"),
        ("revision_change", "changed"),
        ("native_board_error", "unavailable"),
    ],
)
def test_preview_refuses_ambiguous_or_mutated_pair(
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
    message: str,
) -> None:
    pads, board, stats = _arrange(monkeypatch)
    if fault == "bad_snapshot":
        board.get_as_string = lambda: "not_a_native_board"
    if fault == "missing_pad":
        pads.pop()
    if fault == "duplicate_identity":
        pads[3].id.value = pads[0].id.value
    if fault == "blank_identity":
        pads[0].id.value = ""
    if fault == "mismatched_positive_net":
        pads[1].net.name = "OTHER"
    if fault == "mismatched_negative_net":
        pads[3].net.name = "OTHER"
    if fault == "missing_negative_net":
        pads[2].net.name = ""
    if fault == "same_net":
        pads[2].net.name = pads[3].net.name = "USB_D_P"
    if fault == "swapped_usb_polarity":
        pads[0].net.name = pads[1].net.name = "USB_MCU_N"
        pads[2].net.name = pads[3].net.name = "USB_MCU_P"
    if fault == "unsupported_copper":
        monkeypatch.setattr(adapter, "_validate_endpoint_layer", lambda *_a: False)
    if fault == "foreign_obstacle":
        monkeypatch.setattr(
            adapter,
            "snapshot_route_obstacles",
            lambda *_a, **_kw: (CircleObstacle(4, 0.375, 8),),
        )
    if fault == "revision_change":
        versions = iter(["(kicad_pcb initial)", "(kicad_pcb modified)"])
        board.get_as_string = lambda: next(versions)
    if fault == "native_board_error":
        monkeypatch.setattr(
            adapter,
            "get_board",
            lambda: (_ for _ in ()).throw(AttributeError("native IPC unavailable")),
        )
    result = _preview()
    assert result["status"] == "refused"
    assert result["candidateOnly"] is True
    assert message in result["reason"]
    assert (
        stats["snapshots"] == (2 if fault == "revision_change" else 0)
        or fault == "foreign_obstacle"
    )


@pytest.mark.parametrize(
    ("name", "value", "reason"),
    [
        ("width_mm", float("nan"), "finite"),
        ("gap_mm", 0.0, "dimensions"),
        ("max_skew_mm", -0.1, "skew"),
        ("layer", "F_SilkS", "share the requested"),
    ],
)
def test_preview_refuses_unphysical_pair_rules(
    monkeypatch: pytest.MonkeyPatch, name: str, value: object, reason: str
) -> None:
    _arrange(monkeypatch)
    result = _preview(**{name: value})
    assert result["status"] == "refused"
    assert reason.lower() in result["reason"].lower()
