from __future__ import annotations

import re
from types import SimpleNamespace

import pytest
from kipy.proto.board.board_types_pb2 import BoardLayer

from kicad_mcp.server import build_server
from tests.conftest import call_tool_payload, call_tool_text


def _field(value: str) -> SimpleNamespace:
    return SimpleNamespace(text=SimpleNamespace(value=value))


def _configure_emc_board(mock_board) -> None:
    usb_dp_main = SimpleNamespace(
        start=SimpleNamespace(x_nm=5_000_000, y_nm=10_000_000),
        end=SimpleNamespace(x_nm=15_000_000, y_nm=10_000_000),
        width=180_000,
        layer=BoardLayer.BL_F_Cu,
        net=SimpleNamespace(name="USB_DP"),
    )
    usb_dp_stub = SimpleNamespace(
        start=SimpleNamespace(x_nm=15_000_000, y_nm=10_000_000),
        end=SimpleNamespace(x_nm=15_400_000, y_nm=10_000_000),
        width=180_000,
        layer=BoardLayer.BL_F_Cu,
        net=SimpleNamespace(name="USB_DP"),
    )
    usb_dn = SimpleNamespace(
        start=SimpleNamespace(x_nm=5_000_000, y_nm=11_000_000),
        end=SimpleNamespace(x_nm=14_900_000, y_nm=11_000_000),
        width=182_000,
        layer=BoardLayer.BL_F_Cu,
        net=SimpleNamespace(name="USB_DN"),
    )
    hs_clk = SimpleNamespace(
        start=SimpleNamespace(x_nm=6_000_000, y_nm=15_000_000),
        end=SimpleNamespace(x_nm=20_000_000, y_nm=15_000_000),
        width=150_000,
        layer=BoardLayer.BL_F_Cu,
        net=SimpleNamespace(name="HS_CLK"),
    )
    gnd_zone_bottom = SimpleNamespace(
        name="GND_BOTTOM",
        net=SimpleNamespace(name="GND"),
        layers=[BoardLayer.BL_B_Cu],
        filled=True,
    )
    gnd_zone_inner = SimpleNamespace(
        name="GND_INNER",
        net=SimpleNamespace(name="GND"),
        layers=[BoardLayer.BL_In1_Cu],
        filled=True,
    )
    power_zone = SimpleNamespace(
        name="3V3_PLANE",
        net=SimpleNamespace(name="3V3"),
        layers=[BoardLayer.BL_In2_Cu],
        filled=True,
    )
    u1 = SimpleNamespace(
        reference_field=_field("U1"),
        value_field=_field("MCU"),
        position=SimpleNamespace(x_nm=10_000_000, y_nm=20_000_000),
    )
    c1 = SimpleNamespace(
        reference_field=_field("C1"),
        value_field=_field("100n"),
        position=SimpleNamespace(x_nm=11_000_000, y_nm=20_000_000),
    )
    gnd_vias = [
        SimpleNamespace(
            position=SimpleNamespace(x_nm=5_000_000, y_nm=5_000_000),
            net=SimpleNamespace(name="GND"),
        ),
        SimpleNamespace(
            position=SimpleNamespace(x_nm=10_000_000, y_nm=5_000_000),
            net=SimpleNamespace(name="GND"),
        ),
        SimpleNamespace(
            position=SimpleNamespace(x_nm=15_000_000, y_nm=5_000_000),
            net=SimpleNamespace(name="GND"),
        ),
        SimpleNamespace(
            position=SimpleNamespace(x_nm=20_000_000, y_nm=5_000_000),
            net=SimpleNamespace(name="GND"),
        ),
    ]
    edge_rect = SimpleNamespace(
        layer=BoardLayer.BL_Edge_Cuts,
        top_left=SimpleNamespace(x_nm=0, y_nm=0),
        bottom_right=SimpleNamespace(x_nm=40_000_000, y_nm=30_000_000),
    )

    mock_board.get_tracks.return_value = [usb_dp_main, usb_dp_stub, usb_dn, hs_clk]
    mock_board.get_zones.return_value = [gnd_zone_bottom, gnd_zone_inner, power_zone]
    mock_board.get_footprints.return_value = [u1, c1]
    mock_board.get_vias.return_value = gnd_vias
    mock_board.get_shapes.return_value = [edge_rect]


@pytest.mark.anyio
async def test_emc_surface(sample_project, mock_board) -> None:
    _configure_emc_board(mock_board)
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})
    await call_tool_text(
        server,
        "project_set_design_intent",
        {"critical_nets": ["USB_DP", "USB_DN"]},
    )

    ground = await call_tool_text(
        server,
        "emc_check_ground_plane_voids",
        {"max_void_area_mm2": 25.0},
    )
    return_path = await call_tool_text(
        server,
        "emc_check_return_path_continuity",
        {"signal_net": "USB_DP", "reference_plane_layer": "B_Cu"},
    )
    critical_return_path = await call_tool_text(
        server,
        "emc_check_return_path_continuity",
        {"reference_plane_layer": "auto", "search_radius_mm": 2.0},
    )
    split_plane = await call_tool_text(
        server,
        "emc_check_split_plane_crossing",
        {"signal_nets": ["USB_DP", "USB_DN", "HS_CLK"]},
    )
    decoupling = await call_tool_text(
        server,
        "emc_check_decoupling_placement",
        {"max_distance_mm": 3.0},
    )
    stitching = await call_tool_text(
        server,
        "emc_check_via_stitching",
        {"max_gap_mm": 5.0, "ground_net": "GND"},
    )
    diff_pair = await call_tool_text(
        server,
        "emc_check_differential_pair_symmetry",
        {"net_p": "USB_DP", "net_n": "USB_DN", "max_skew_ps": 10.0},
    )
    routing = await call_tool_text(
        server,
        "emc_check_high_speed_routing_rules",
        {"net_class": "USB", "max_stub_length_mm": 1.0},
    )
    full = await call_tool_text(
        server,
        "emc_run_full_compliance",
        {"standard": "FCC"},
    )

    assert "Ground plane void review" in ground
    assert "(PASS)" in ground
    assert "Return path continuity" in return_path
    assert "Checked 2/2 net(s)" in critical_return_path
    assert "Split-plane crossing review" in split_plane
    assert "Decoupling placement review" in decoupling
    assert "Via stitching review" in stitching
    assert "Differential-pair symmetry" in diff_pair
    assert "High-speed routing rule review" in routing
    assert "EMC compliance sweep (FCC)" in full
    assert "Checks run: 10" in full


@pytest.mark.anyio
async def test_emc_split_ground_names_are_treated_as_ground(sample_project, mock_board) -> None:
    _configure_emc_board(mock_board)
    zones = mock_board.get_zones.return_value
    zones[0].net.name = "GND_DIG"
    zones[1].net.name = "GND_ANA"
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    ground = await call_tool_text(
        server,
        "emc_check_ground_plane_voids",
        {"max_void_area_mm2": 25.0},
    )
    return_path = await call_tool_text(
        server,
        "emc_check_return_path_continuity",
        {"signal_net": "USB_DP", "reference_plane_layer": "B_Cu"},
    )

    assert "(PASS)" in ground
    assert "No GND plane was found" not in return_path


def _filled_reference_zone(vertices, holes=()):
    from kipy.board_types import Zone

    zone = Zone()
    zone.proto.filled = True
    zone.proto.layers.append(BoardLayer.BL_B_Cu)
    zone.proto.copper_settings.net.name = "GND"
    fill = zone.proto.filled_polygons.add()
    fill.layer = BoardLayer.BL_B_Cu
    polygon = fill.shapes.polygons.add()
    for ring, points in [(polygon.outline, vertices), *[(polygon.holes.add(), h) for h in holes]]:
        ring.closed = True
        for x, y in points:
            point = ring.nodes.add().point
            point.x_nm = int(x * 1_000_000)
            point.y_nm = int(y * 1_000_000)
    return zone


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("vertices", "holes", "expected"),
    [
        ([(0, 0), (20, 0), (20, 20), (0, 20)], [], "unverified"),
        ([(30, 30), (40, 30), (40, 40), (30, 40)], [], "uncovered"),
        ([(0, 0), (20, 0), (20, 20), (0, 20)], [[(8, 9), (12, 9), (12, 12), (8, 12)]], "uncovered"),
    ],
)
async def test_return_path_reports_stored_geometry_without_physical_pass(
    sample_project, mock_board, vertices, holes, expected
) -> None:

    _configure_emc_board(mock_board)
    mock_board.get_zones.return_value = [_filled_reference_zone(vertices, holes)]
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})
    result = await call_tool_payload(
        server,
        "emc_check_return_path_continuity",
        {"signal_net": "USB_DP", "reference_plane_layer": "B_Cu"},
    )
    assert result["verdict"] == "WARN"
    assert "stored" in result["summary"].lower()
    assert expected in result["summary"].lower()
    match = re.search(r"(\d+)/(\d+) covered, (\d+) uncovered", result["summary"])
    assert match is not None
    covered, total, uncovered = map(int, match.groups())
    assert total > 0
    assert covered + uncovered == total
    if expected == "unverified":
        assert covered == total
    elif vertices[0] == (30, 30):
        assert covered == 0
    else:
        assert 0 < covered < total


@pytest.mark.anyio
async def test_return_path_unfilled_zone_is_not_continuity(sample_project, mock_board) -> None:

    _configure_emc_board(mock_board)
    mock_board.get_zones.return_value[0].filled = False
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})
    result = await call_tool_payload(
        server,
        "emc_check_return_path_continuity",
        {"signal_net": "USB_DP", "reference_plane_layer": "B_Cu"},
    )
    assert result["verdict"] == "WARN"
    assert "unfilled" in result["summary"].lower()


@pytest.mark.anyio
async def test_return_path_reports_omitted_nets(sample_project, mock_board, monkeypatch) -> None:
    from kicad_mcp.tools import emc_compliance

    _configure_emc_board(mock_board)
    monkeypatch.setattr(emc_compliance, "_high_speed_nets", lambda: ["USB_DP", "USB_DN"])
    monkeypatch.setattr(
        emc_compliance, "get_config", lambda: SimpleNamespace(max_items_per_response=1)
    )
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})
    result = await call_tool_payload(
        server, "emc_check_return_path_continuity", {"reference_plane_layer": "B_Cu"}
    )
    assert result["verdict"] == "WARN"
    assert "1/2" in result["summary"]
    assert "1 omitted" in result["summary"]


@pytest.mark.anyio
@pytest.mark.parametrize("mode", ["missing", "same_layer", "fractured", "mixed", "invalid_radius"])
async def test_return_path_evidence_limits(sample_project, mock_board, mode) -> None:

    _configure_emc_board(mock_board)
    args = {"signal_net": "USB_DP", "reference_plane_layer": "B_Cu"}
    if mode == "missing":
        expected = "unavailable"
    elif mode == "same_layer":
        args["reference_plane_layer"] = "F_Cu"
        mock_board.get_zones.return_value[0].layers = [BoardLayer.BL_F_Cu]
        expected = "same layer"
    elif mode == "fractured":
        mock_board.get_zones.return_value = [
            _filled_reference_zone(
                [
                    (0, 0),
                    (8, 0),
                    (8, 9),
                    (8, 12),
                    (12, 12),
                    (12, 9),
                    (8, 9),
                    (8, 0),
                    (20, 0),
                    (20, 20),
                    (0, 20),
                ]
            )
        ]
        expected = "uncovered"
    elif mode == "mixed":
        mock_board.get_tracks.return_value[1].layer = BoardLayer.BL_B_Cu
        expected = "multiple signal layers"
    else:
        args["search_radius_mm"] = -1.0
        expected = "positive"
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})
    result = await call_tool_payload(server, "emc_check_return_path_continuity", args)
    assert result["verdict"] == "WARN"
    assert expected in result["summary"].lower()
    if mode == "fractured":
        assert re.search(r"[1-9]\d* uncovered", result["summary"])


@pytest.mark.anyio
async def test_full_emc_sweep_does_not_claim_plane_coverage(sample_project, mock_board) -> None:
    _configure_emc_board(mock_board)
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})
    result = await call_tool_payload(server, "emc_run_full_compliance", {})
    checks = {item["check"]: item for item in result["evidence"]}
    assert checks["return_path_continuity"]["verdict"] == "WARN"
    assert checks["reference_plane_coverage"]["verdict"] == "WARN"
    assert "unverified" in checks["reference_plane_coverage"]["detail"].lower()


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        ("open", "open filled contour"),
        ("degenerate", "invalid filled contour"),
        ("unsupported", "unsupported stored filled polygon"),
        ("curve", "curved signal geometry unsupported"),
        ("long", "sample budget exceeded"),
        ("work", "work budget exceeded"),
        ("missing_net", "No routed tracks"),
        ("missing_plane", "No GND plane"),
    ],
)
async def test_return_path_refuses_unverifiable_evidence(
    sample_project, mock_board, monkeypatch, mode, expected
) -> None:
    from kicad_mcp.pcb import return_path_evidence

    _configure_emc_board(mock_board)
    zone = _filled_reference_zone([(0, 0), (20, 0), (20, 20), (0, 20)])
    mock_board.get_zones.return_value = [zone]
    args = {"signal_net": "USB_DP", "reference_plane_layer": "B_Cu"}
    if mode == "open":
        zone.proto.filled_polygons[0].shapes.polygons[0].outline.closed = False
    elif mode == "degenerate":
        zone.proto.filled_polygons[0].shapes.polygons[0].outline.ClearField("nodes")
    elif mode == "unsupported":
        mock_board.get_zones.return_value = [
            SimpleNamespace(
                net=SimpleNamespace(name="GND"),
                layers=[BoardLayer.BL_B_Cu],
                filled=True,
                filled_polygons={BoardLayer.BL_B_Cu: [object()]},
            )
        ]
    elif mode == "curve":
        mock_board.get_tracks.return_value[0].mid = SimpleNamespace(
            x_nm=10_000_000, y_nm=10_000_000
        )
    elif mode == "long":
        mock_board.get_tracks.return_value[0].end.x_nm = 1_000_000_000
    elif mode == "work":
        monkeypatch.setattr(return_path_evidence, "_MAX_EDGE_CHECKS", 10)
    elif mode == "missing_net":
        args["signal_net"] = "USB_MISSING"
    else:
        args["reference_plane_layer"] = "In2_Cu"
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})
    result = await call_tool_payload(server, "emc_check_return_path_continuity", args)
    assert result["verdict"] == "WARN"
    assert expected in result["summary"]


def test_stored_fill_without_filled_zones() -> None:
    from kicad_mcp.pcb.return_path_evidence import describe_stored_plane

    result = describe_stored_plane([], [SimpleNamespace(filled=False)], BoardLayer.BL_B_Cu)
    assert "unfilled" in result


@pytest.mark.parametrize("mode", ["outer_edge", "hole_edge", "fractured_edge"])
def test_stored_fill_boundary_is_not_counted_as_confirmed_interior(mode) -> None:
    from kicad_mcp.pcb.return_path_evidence import describe_stored_plane

    vertices = [(0, 0), (10, 0), (10, 10), (0, 10)]
    holes = []
    if mode == "outer_edge":
        x, y = 2, 0
    elif mode == "hole_edge":
        holes = [[(4, 4), (4, 6), (6, 6), (6, 4)]]
        x, y = 6, 5
    else:
        vertices = [
            (0, 0),
            (4, 0),
            (4, 4),
            (4, 6),
            (6, 6),
            (6, 4),
            (4, 4),
            (4, 0),
            (10, 0),
            (10, 10),
            (0, 10),
        ]
        x, y = 6, 5
    start = SimpleNamespace(x_nm=x * 1_000_000, y_nm=y * 1_000_000)
    end = SimpleNamespace(x_nm=x * 1_000_000, y_nm=(y + 0.1) * 1_000_000)
    if mode == "outer_edge":
        end = SimpleNamespace(x_nm=(x + 0.1) * 1_000_000, y_nm=y * 1_000_000)
    result = describe_stored_plane(
        [SimpleNamespace(start=start, end=end)],
        [_filled_reference_zone(vertices, holes)],
        BoardLayer.BL_B_Cu,
    )
    assert re.search(r"0/\d+ covered", result), result
    assert "boundary" in result.lower()
