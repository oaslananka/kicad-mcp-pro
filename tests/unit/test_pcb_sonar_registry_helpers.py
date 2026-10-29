"""Protect registration contracts and PCB geometry helpers during refactors."""

from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace

import pytest
from kipy.geometry import Vector2

from kicad_mcp.models.pcb import AddTeardropsInput, SyncPcbFromSchematicInput
from kicad_mcp.tools import pcb


class _ToolCollector:
    def __init__(self) -> None:
        self.names: list[str] = []

    def tool(self):
        def record(fn):
            self.names.append(fn.__name__)
            return fn

        return record


@pytest.mark.parametrize(
    ("registry", "expected"),
    [
        (
            pcb._register_board_rules_tools,
            ["pcb_get_ratsnest", "pcb_get_design_rules", "pcb_set_design_rules"],
        ),
        (
            pcb._register_routing_authoring_tools,
            [
                "pcb_add_track",
                "pcb_add_track_segment",
                "pcb_route_trace",
                "pcb_add_tracks_bulk",
                "pcb_add_via",
                "pcb_add_blind_via",
                "pcb_add_microvia",
                "pcb_add_segment",
            ],
        ),
        (
            pcb._register_board_mutation_tools,
            [
                "pcb_delete_items",
                "pcb_delete_object",
                "pcb_save",
                "pcb_refill_zones",
                "pcb_highlight_net",
                "pcb_set_net_class",
                "pcb_place_component",
                "pcb_move_component",
                "pcb_move_footprint",
                "pcb_set_footprint_layer",
                "add_footprint_inner_layer_graphic",
            ],
        ),
        (
            pcb._register_zone_authoring_tools,
            ["pcb_align_footprints", "pcb_add_zone", "pcb_add_copper_zone", "pcb_set_keepout_zone"],
        ),
        (
            pcb._register_mechanical_and_block_tools,
            [
                "pcb_add_mounting_holes",
                "pcb_add_fiducial_marks",
                "pcb_block_list",
                "pcb_block_create_from_selection",
                "pcb_block_place",
            ],
        ),
    ],
)
def test_refactored_registry_preserves_order_and_names(
    registry: Callable[[object], None], expected: list[str]
) -> None:
    collector = _ToolCollector()
    registry(collector)
    assert expected == collector.names


def _pad(name: str, reference: str, x: float, y: float, netclass: str = "Power") -> SimpleNamespace:
    return SimpleNamespace(
        net=SimpleNamespace(name=name, netclass_name=netclass),
        position=Vector2.from_xy_mm(x, y),
        size=Vector2.from_xy_mm(1.0, 1.0),
        parent=SimpleNamespace(
            reference_field=SimpleNamespace(text=SimpleNamespace(value=reference))
        ),
        number="1",
    )


def test_creepage_chooses_closest_differently_named_net_and_skips_unnamed() -> None:
    pads = [
        _pad("", "NO_NET", 0, 0),
        _pad("GND", "J1", 0, 0),
        _pad("GND", "J2", 0.2, 0),
        _pad("VCC", "U1", 2, 0),
    ]
    result = pcb._closest_named_net_pad_pair(pads)
    assert result is not None
    assert ("J2.1", "GND", "U1.1", "VCC") == result[1:]
    assert result[0] == pytest.approx(0.8)
    assert None is pcb._closest_named_net_pad_pair([_pad("GND", "A", 0, 0), _pad("GND", "B", 1, 1)])
    assert None is pcb._closest_named_net_pad_pair([_pad("", "A", 0, 0)])


def test_creepage_candidate_rejects_same_or_unnamed_net_and_clamps_overlap() -> None:
    assert None is pcb._creepage_candidate_for_pad_pair(
        _pad("GND", "J1", 0, 0), "GND", 0.5, 0, 0, "J0", "1"
    )
    assert None is pcb._creepage_candidate_for_pad_pair(
        _pad("", "J1", 0, 0), "GND", 0.5, 0, 0, "J0", "1"
    )
    match = pcb._creepage_candidate_for_pad_pair(
        _pad("VCC", "J1", 0, 0), "GND", 0.5, 0, 0, "J0", "1"
    )
    assert match is not None
    assert 0 == match[0]


def test_schematic_sync_helpers_preserve_mismatches_and_positions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    components = [
        {"reference": "U1", "footprint": "Lib:New"},
        {"reference": "R1", "footprint": "Lib:Resistor"},
    ]
    existing = {
        "U1": {"name": "Old", "x_mm": 10.0, "y_mm": 15.0, "width_mm": 2.0, "height_mm": 3.0},
    }
    references, messages = pcb._pcb_sync_mismatched_assignments(components, existing)
    assert ["U1"] == references
    assert ["U1: board has Old, schematic expects New"] == messages
    payload = SyncPcbFromSchematicInput()
    observed: dict[str, object] = {}

    def positions(
        components_to_add: list[dict[str, object]],
        options: SyncPcbFromSchematicInput,
        occupied: list[dict[str, float]],
    ) -> dict[str, tuple[float, float]]:
        observed.update(components=components_to_add, options=options, occupied=occupied)
        return {"R1": (30.0, 40.0)}

    def additions(
        parts: list[dict[str, object]],
        resolved: dict[str, tuple[float, float]],
        net_map: dict[tuple[str, str], str],
    ) -> list[str]:
        observed.update(parts=parts, resolved=resolved, net_map=net_map)
        return ["footprint-R1"]

    monkeypatch.setattr(pcb, "_planned_board_positions", positions)
    monkeypatch.setattr(pcb, "_build_sync_additions", additions)
    assert ["footprint-R1"] == pcb._pcb_sync_additions_for_board(components, existing, payload, {})
    assert [components[1]] == observed["components"]
    assert [{"x_mm": 10.0, "y_mm": 15.0, "width_mm": 2.0, "height_mm": 3.0}] == observed["occupied"]
    assert {"R1": (30.0, 40.0)} == observed["resolved"]


def test_teardrop_zone_collection_preserves_limits_and_eligibility(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        pcb, "Zone", lambda: SimpleNamespace(name=None, layers=None, net=None, outline=None)
    )
    pad = _pad("GND", "J1", 0, 0)
    net = SimpleNamespace(name="GND", proto=object())
    track = SimpleNamespace(
        start=Vector2.from_xy_mm(0, 0),
        end=Vector2.from_xy_mm(2, 0),
        width=pcb.mm_to_nm(0.2),
        net=net,
        layer="F.Cu",
    )
    another = SimpleNamespace(
        start=Vector2.from_xy_mm(3, 0),
        end=Vector2.from_xy_mm(2, 0),
        width=pcb.mm_to_nm(0.2),
        net=net,
        layer="F.Cu",
    )
    other_net = SimpleNamespace(**{**vars(track), "net": SimpleNamespace(name="VCC")})
    settings = AddTeardropsInput(max_count=1)
    zones = pcb._collect_teardrop_zones([pad, pad], [other_net, another, track], settings)
    assert 1 == len(zones)
    assert "MCP_Teardrop_J1" == zones[0].name
    assert ["F.Cu"] == zones[0].layers
    assert net is zones[0].net
    assert zones[0].outline is not None
    assert [] == pcb._collect_teardrop_zones([pad], [other_net], settings)
    assert [] == pcb._collect_teardrop_zones(
        [pad], [track], AddTeardropsInput(net_classes=["Signal"])
    )


def test_teardrop_rejects_zero_length_or_unconnected_tracks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        pcb, "Zone", lambda: SimpleNamespace(name=None, layers=None, net=None, outline=None)
    )
    pad = _pad("GND", "J1", 0, 0)
    net = SimpleNamespace(name="GND", proto=object())
    track = SimpleNamespace(
        start=Vector2.from_xy_mm(0, 0),
        end=Vector2.from_xy_mm(0, 0),
        width=pcb.mm_to_nm(0.2),
        net=net,
        layer="F.Cu",
    )
    assert [] == pcb._collect_teardrop_zones([pad], [track], AddTeardropsInput())
    far = SimpleNamespace(
        start=Vector2.from_xy_mm(10, 10),
        end=Vector2.from_xy_mm(20, 20),
        width=pcb.mm_to_nm(0.2),
        net=net,
        layer="F.Cu",
    )
    assert [] == pcb._collect_teardrop_zones([pad], [far], AddTeardropsInput())


def test_file_backed_ratsnest_preserves_fail_closed_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reason = OSError("KiCad unavailable")
    monkeypatch.setattr(pcb, "_load_file_backed_board", lambda exc: "No board file")
    assert "No board file" == pcb._file_backed_ratsnest_report(reason)
    monkeypatch.setattr(
        pcb, "_load_file_backed_board", lambda exc: (object(), "(kicad_pcb)", ["file-backed"])
    )
    monkeypatch.setattr(pcb, "_board_file_nets", lambda content: [])
    assert (
        "The file-backed board has no nets to analyze.\nfile-backed"
        == pcb._file_backed_ratsnest_report(reason)
    )
    monkeypatch.setattr(pcb, "_board_file_nets", lambda content: ["GND"])
    text = pcb._file_backed_ratsnest_report(reason)
    assert "File-backed ratsnest extraction requires a DRC report" in text
    assert "run_drc()" in text and "file-backed" in text


def test_alignment_replacements_preserve_axis_and_rotation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kicad_mcp.models.pcb import AlignFootprintsInput

    placements: list[tuple[str, float, float, int]] = []

    def replace(block: str, *, x_mm: float, y_mm: float, rotation: int) -> str:
        placements.append((block, x_mm, y_mm, rotation))
        return f"placed:{block}"

    monkeypatch.setattr(pcb, "_replace_root_at", replace)
    existing = {
        "U1": {"x_mm": 10, "y_mm": 20, "rotation": 90, "block": "U1 block"},
        "U2": {"x_mm": 50, "y_mm": 60, "rotation": 180, "block": "U2 block"},
    }
    for axis, second in (
        ("x", ("U2 block", 12.5, 20.0, 180)),
        ("y", ("U2 block", 10.0, 22.5, 180)),
    ):
        placements.clear()
        result = pcb._aligned_footprint_replacements(
            existing,
            ["U1", "U2"],
            AlignFootprintsInput(refs=["U1", "U2"], axis=axis, spacing_mm=2.5),
        )
        assert {"U1": "placed:U1 block", "U2": "placed:U2 block"} == result
        assert [("U1 block", 10.0, 20.0, 90), second] == placements


def test_unique_copper_zone_points_drop_repeats_and_closing_point() -> None:
    from kicad_mcp.models.pcb import ZoneCornerInput

    def corner(x: float, y: float) -> ZoneCornerInput:
        return ZoneCornerInput(x_mm=x, y_mm=y)

    assert [(0.0, 0.0), (4.0, 0.0), (4.0, 3.0)] == pcb._unique_copper_zone_points(
        [corner(0, 0), corner(4, 0), corner(4, 3), corner(4, 0), corner(0, 0)]
    )
    assert [] == pcb._unique_copper_zone_points([])
    assert [(1.0, 1.0)] == pcb._unique_copper_zone_points([corner(1, 1), corner(1, 1)])
