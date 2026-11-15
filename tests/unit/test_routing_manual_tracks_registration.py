from __future__ import annotations

import importlib
import importlib.util
import inspect
from types import ModuleType

import pytest
from mcp.server.mcpserver import MCPServer as FastMCP

from kicad_mcp.pcb.geometry import point_xy_mm
from kicad_mcp.routing.manual_tracks import TrackSpec
from kicad_mcp.tools.metadata import get_tool_metadata
from kicad_mcp.utils.layers import resolve_layer
from kicad_mcp.utils.units import mm_to_nm


def _adapter() -> ModuleType:
    spec = importlib.util.find_spec("kicad_mcp.tools.routing_manual_tracks")
    assert spec is not None
    return importlib.import_module("kicad_mcp.tools.routing_manual_tracks")


class FakeService:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def route_single(
        self,
        x1_mm: float,
        y1_mm: float,
        x2_mm: float,
        y2_mm: float,
        layer: str = "F_Cu",
        width_mm: float = 0.25,
        net_name: str = "",
    ) -> str:
        self.calls.append(("single", x1_mm, y1_mm, x2_mm, y2_mm, layer, width_mm, net_name))
        return "single-delegated"

    def route_pad_to_pad(
        self,
        ref1: str,
        pad1: str,
        ref2: str,
        pad2: str,
        layer: str = "F_Cu",
        width_mm: float = 0.25,
    ) -> str:
        self.calls.append(("pads", ref1, pad1, ref2, pad2, layer, width_mm))
        return "pads-delegated"


def test_adapter_maps_track_spec_to_kipy_track() -> None:
    adapter = _adapter()

    track = adapter._track_from_spec(TrackSpec(1.0, 2.0, 5.0, 8.0, "F_Cu", 0.3, "USB_D+"))

    assert point_xy_mm(track.start) == (1.0, 2.0)
    assert point_xy_mm(track.end) == (5.0, 8.0)
    assert track.layer == resolve_layer("F_Cu")
    assert track.width == mm_to_nm(0.3)
    assert track.net.name == "USB_D+"


def test_registration_preserves_order_signatures_metadata_and_delegation() -> None:
    adapter = _adapter()
    server = FastMCP("routing-manual-track-registration")
    service = FakeService()

    adapter.register(
        server,
        adapter.RoutingManualTrackDependencies(service=service),
    )

    tools = server._tool_manager.list_tools()
    assert [tool.name for tool in tools] == [
        "route_single_track",
        "route_from_pad_to_pad",
        "route_plan_between_pads",
    ]

    single, pads, preview = tools
    assert str(inspect.signature(single.fn)) == (
        "(x1_mm: 'float', y1_mm: 'float', x2_mm: 'float', y2_mm: 'float', "
        "layer: 'str' = 'F_Cu', width_mm: 'float' = 0.25, "
        "net_name: 'str' = '') -> 'str'"
    )
    assert str(inspect.signature(pads.fn)) == (
        "(ref1: 'str', pad1: 'str', ref2: 'str', pad2: 'str', "
        "layer: 'str' = 'F_Cu', width_mm: 'float' = 0.25) -> 'str'"
    )
    assert "Route a single straight track segment" in (single.fn.__doc__ or "")
    assert "same-net pads on an enabled copper layer" in (pads.fn.__doc__ or "")
    assert "same named net" in (pads.fn.__doc__ or "")
    assert "enabled" in (pads.fn.__doc__ or "")

    for tool_name in ("route_single_track", "route_from_pad_to_pad", "route_plan_between_pads"):
        metadata = get_tool_metadata(tool_name)
        assert metadata is not None
        assert metadata.headless_compatible is False
        assert metadata.requires_kicad_running is True

    assert single.fn(1.0, 2.0, 3.0, 4.0, "F_Cu", 0.3, "DATA") == "single-delegated"
    assert pads.fn("R1", "1", "U2", "3", "F_Cu", 0.25) == "pads-delegated"
    assert service.calls == [
        ("single", 1.0, 2.0, 3.0, 4.0, "F_Cu", 0.3, "DATA"),
        ("pads", "R1", "1", "U2", "3", "F_Cu", 0.25),
    ]


def test_default_adapter_maps_realistic_kicad_kiid_pad_owners(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """KiCad IPC pads expose owner KIIDs; shared mapping recovers footprint refs."""
    from types import SimpleNamespace

    from kipy.board_types import BoardLayer, Net
    from kipy.geometry import Vector2

    adapter = _adapter()

    def pad(owner: str, ident: str, number: str, x_mm: float) -> SimpleNamespace:
        net = Net()
        net.name = "MID"
        return SimpleNamespace(
            id=SimpleNamespace(value=ident),
            parent=SimpleNamespace(value=owner),
            number=number,
            net=net,
            padstack=SimpleNamespace(layers=[BoardLayer.BL_F_Cu]),
            position=Vector2.from_xy_mm(x_mm, 10),
        )

    p1 = pad("fp-1", "pad-1", "2", 10.95)
    p2 = pad("fp-2", "pad-2", "1", 19.05)

    def footprint(ref: str, part: SimpleNamespace) -> SimpleNamespace:
        return SimpleNamespace(
            reference_field=SimpleNamespace(text=SimpleNamespace(value=ref)),
            definition=SimpleNamespace(pads=[part]),
        )

    board = SimpleNamespace(
        get_pads=lambda: [p1, p2],
        get_footprints=lambda: [footprint("R1", p1), footprint("R2", p2)],
        get_enabled_layers=lambda: [BoardLayer.BL_F_Cu, BoardLayer.BL_B_Cu],
    )
    monkeypatch.setattr(adapter, "get_board", lambda: board)
    writes: list[tuple[str, list[TrackSpec]]] = []
    monkeypatch.setattr(
        adapter, "_write_tracks", lambda operation, specs: writes.append((operation, specs))
    )

    service = adapter._default_dependencies().service
    result = service.route_pad_to_pad("R1", "2", "R2", "1")

    assert "single-segment" in result
    assert writes == [
        ("route_from_pad_to_pad", [TrackSpec(10.95, 10, 19.05, 10, "F_Cu", 0.25, "MID")])
    ]


def test_layer_validator_preserves_through_hole_on_back_copper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from kipy.board_types import BoardLayer, Pad, PadType
    from kipy.proto.board.board_types_pb2 import PadStackType

    adapter = _adapter()
    board = SimpleNamespace(
        get_enabled_layers=lambda: [BoardLayer.BL_F_Cu, BoardLayer.BL_B_Cu],
    )
    monkeypatch.setattr(adapter, "get_board", lambda: board)

    through_hole = Pad()
    through_hole.pad_type = PadType.PT_PTH
    through_hole.padstack.type = PadStackType.PST_NORMAL
    through_hole.padstack.layers = [BoardLayer.BL_F_Cu, BoardLayer.BL_B_Cu]
    assert through_hole.padstack.copper_layer(BoardLayer.BL_B_Cu) is None

    assert adapter._validate_endpoint_layer(through_hole, through_hole, "B_Cu")
    assert adapter._validate_endpoint_layer(through_hole, through_hole, "F_Cu")

    front_only = Pad()
    front_only.pad_type = PadType.PT_SMD
    front_only.padstack.layers = [BoardLayer.BL_F_Cu, BoardLayer.BL_F_Mask]
    assert adapter._validate_endpoint_layer(front_only, through_hole, "F_Cu")
    assert not adapter._validate_endpoint_layer(front_only, through_hole, "B_Cu")
    assert not adapter._validate_endpoint_layer(front_only, through_hole, "F_SilkS")
    assert not adapter._validate_endpoint_layer(through_hole, through_hole, "In1_Cu")
    assert not adapter._validate_endpoint_layer(front_only, through_hole, "INVALID")
    assert not adapter._validate_endpoint_layer(SimpleNamespace(), through_hole, "F_Cu")


def test_layer_validator_rejects_disabled_board_copper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from kipy.board_types import BoardLayer, Pad

    adapter = _adapter()
    board = SimpleNamespace(get_enabled_layers=lambda: [BoardLayer.BL_F_Cu])
    monkeypatch.setattr(adapter, "get_board", lambda: board)
    p = Pad()
    p.padstack.layers = [BoardLayer.BL_F_Cu, BoardLayer.BL_B_Cu]
    assert not adapter._validate_endpoint_layer(p, p, "B_Cu")


def test_route_plan_preview_is_registered_as_readonly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kicad_mcp.tools.metadata import infer_tool_annotations

    adapter = _adapter()
    server = FastMCP("routing-preview-registration")
    adapter.register(server, adapter.RoutingManualTrackDependencies(service=FakeService()))

    previews = [
        tool for tool in server._tool_manager.list_tools() if tool.name == "route_plan_between_pads"
    ]
    assert len(previews) == 1
    preview = previews[0]
    assert "READ-ONLY" in (preview.fn.__doc__ or "")
    assert "boardRevision" in (preview.fn.__doc__ or "")
    assert "candidateId" in (preview.fn.__doc__ or "")
    assert infer_tool_annotations("route_plan_between_pads").read_only_hint is True

    monkeypatch.setattr(
        adapter, "_preview_route_between_pads", lambda *_args: '{"candidateOnly":true}'
    )
    assert "candidateOnly" in preview.fn("R1", "2", "R2", "1")


def test_route_plan_preview_never_inherits_write_tier() -> None:
    from kicad_mcp.capabilities import AccessTier, get
    from kicad_mcp.operating_modes import OperatingMode, tool_required_mode

    capability = get("route_plan_between_pads")
    assert capability is not None
    assert capability.tier is AccessTier.READ
    assert capability.writes_files is False
    assert capability.writes_kicad_gui_state is False
    assert tool_required_mode("route_plan_between_pads") is OperatingMode.READONLY


def test_route_plan_is_exposed_readonly_without_write_tools() -> None:
    from kicad_mcp.operating_modes import OperatingMode
    from kicad_mcp.server import build_server

    server = build_server("expert")
    server.operating_mode = OperatingMode.READONLY
    server.filter_runtime_tools = False
    names = {tool.name for tool in server.list_tools_sync()}

    assert "route_plan_between_pads" in names
    assert "route_from_pad_to_pad" not in names


def test_preview_issues_board_bound_candidate_revision(monkeypatch: pytest.MonkeyPatch) -> None:
    import hashlib
    import json
    from types import SimpleNamespace

    from kipy.geometry import Vector2

    from kicad_mcp.pcb.pad_mapping import MappedPad

    adapter = _adapter()
    net = SimpleNamespace(name="MID")

    def pad(number: str, x: float, identity: str) -> SimpleNamespace:
        return SimpleNamespace(
            number=number,
            net=net,
            id=SimpleNamespace(value=identity),
            position=Vector2.from_xy_mm(x, 10),
        )

    first = MappedPad(pad=pad("2", 10, "pad-1"), pad_id="pad-1", reference="R1")
    second = MappedPad(pad=pad("1", 20, "pad-2"), pad_id="pad-2", reference="R2")
    board = SimpleNamespace(get_as_string=lambda: "(kicad_pcb original)", marker="board")
    monkeypatch.setattr(adapter, "get_board", lambda: board)
    monkeypatch.setattr(adapter, "board_pads", lambda _board: [])
    monkeypatch.setattr(adapter, "board_footprints", lambda _board: [])
    monkeypatch.setattr(adapter, "map_pads_to_footprints", lambda *_args: [first, second])
    monkeypatch.setattr(adapter, "_validate_endpoint_layer", lambda *_args: True)
    monkeypatch.setattr(adapter, "snapshot_route_obstacles", lambda *_args, **_kwargs: ())
    monkeypatch.setattr(
        adapter,
        "plan_hv45_path",
        lambda *_args, **_kwargs: (
            (10.0, 10.0),
            (20.0, 10.0),
        ),
    )

    data = json.loads(adapter._preview_route_between_pads("R1", "2", "R2", "1"))
    assert data["status"] == "candidate"
    assert data["schemaVersion"] == "route-preview.v1"
    assert data["boardRevision"] == hashlib.sha256(b"(kicad_pcb original)").hexdigest()
    assert len(data["candidateId"]) == 64
    assert data["candidateOnly"] is True
    assert data["drcVerified"] is False
    assert (
        data["candidateId"]
        == json.loads(adapter._preview_route_between_pads("R1", "2", "R2", "1"))["candidateId"]
    )


def test_preview_rejects_board_revision_change_during_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import json
    from types import SimpleNamespace

    from kipy.geometry import Vector2

    from kicad_mcp.pcb.pad_mapping import MappedPad

    adapter = _adapter()
    reads = iter(("(kicad_pcb old)", "(kicad_pcb changed)"))
    board = SimpleNamespace(get_as_string=lambda: next(reads))
    net = SimpleNamespace(name="MID")

    def mapped(ref: str, number: str, x: float, identity: str) -> MappedPad:
        return MappedPad(
            pad=SimpleNamespace(
                number=number,
                id=SimpleNamespace(value=identity),
                net=net,
                position=Vector2.from_xy_mm(x, 10),
            ),
            pad_id=identity,
            reference=ref,
        )

    first = mapped("R1", "2", 10, "one")
    second = mapped("R2", "1", 20, "two")
    monkeypatch.setattr(adapter, "get_board", lambda: board)
    monkeypatch.setattr(adapter, "board_pads", lambda _board: [])
    monkeypatch.setattr(adapter, "board_footprints", lambda _board: [])
    monkeypatch.setattr(adapter, "map_pads_to_footprints", lambda *_args: [first, second])
    monkeypatch.setattr(adapter, "_validate_endpoint_layer", lambda *_args: True)
    monkeypatch.setattr(adapter, "snapshot_route_obstacles", lambda *_args, **_kwargs: ())
    monkeypatch.setattr(
        adapter,
        "plan_hv45_path",
        lambda *_args, **_kwargs: (
            (10.0, 10.0),
            (20.0, 10.0),
        ),
    )
    result = json.loads(adapter._preview_route_between_pads("R1", "2", "R2", "1"))
    assert result["status"] == "refused"
    assert "changed" in result["reason"]
    assert "segments" not in result


def _setup_preview_revision_test(
    monkeypatch: pytest.MonkeyPatch, snapshots: tuple[str, ...]
) -> ModuleType:
    from types import SimpleNamespace

    from kipy.geometry import Vector2

    from kicad_mcp.pcb.pad_mapping import MappedPad

    adapter = _adapter()
    seq = iter(snapshots)
    board = SimpleNamespace(get_as_string=lambda: next(seq))
    net = SimpleNamespace(name="MID")

    def mapped(ref: str, number: str, x: float, identity: str) -> MappedPad:
        return MappedPad(
            pad=SimpleNamespace(
                number=number,
                id=SimpleNamespace(value=identity),
                net=net,
                position=Vector2.from_xy_mm(x, 10),
            ),
            pad_id=identity,
            reference=ref,
        )

    monkeypatch.setattr(adapter, "get_board", lambda: board)
    monkeypatch.setattr(adapter, "board_pads", lambda _board: [])
    monkeypatch.setattr(adapter, "board_footprints", lambda _board: [])
    monkeypatch.setattr(
        adapter,
        "map_pads_to_footprints",
        lambda *_args: [mapped("R1", "2", 10, "one"), mapped("R2", "1", 20, "two")],
    )
    monkeypatch.setattr(adapter, "_validate_endpoint_layer", lambda *_args: True)
    monkeypatch.setattr(adapter, "snapshot_route_obstacles", lambda *_args, **_kwargs: ())
    monkeypatch.setattr(
        adapter,
        "plan_hv45_path",
        lambda *_args, **_kwargs: ((10.0, 10.0), (20.0, 10.0)),
    )
    return adapter


def test_preview_has_immutable_board_revision_and_candidate_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import hashlib
    import json

    board = "(kicad_pcb original)"
    adapter = _setup_preview_revision_test(monkeypatch, (board, board))
    result = json.loads(adapter._preview_route_between_pads("R1", "2", "R2", "1"))
    assert result["status"] == "candidate"
    assert result["schemaVersion"] == "route-preview.v1"
    assert result["boardRevision"] == hashlib.sha256(board.encode()).hexdigest()
    assert len(result["candidateId"]) == 64
    assert result["candidateOnly"] is True
    assert result["drcVerified"] is False


def test_preview_refuses_if_live_board_changed_while_planning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import json

    adapter = _setup_preview_revision_test(monkeypatch, ("(kicad_pcb before)", "(kicad_pcb after)"))
    result = json.loads(adapter._preview_route_between_pads("R1", "2", "R2", "1"))
    assert result["status"] == "refused"
    assert "changed" in result["reason"].lower()
    assert "segments" not in result
