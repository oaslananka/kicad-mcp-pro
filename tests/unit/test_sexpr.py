from __future__ import annotations

from kicad_mcp.tools.schematic import (
    BBox,
    _apply_basic_auto_layout,
    _apply_netlist_auto_layout,
    _auto_layout_point,
    _average_position,
    _classify_symbol,
    _coord_value,
    _deduplicate_segments,
    _describe_net_endpoint,
    _detect_t_intersections,
    _endpoint_label,
    _endpoint_pin,
    _endpoint_power,
    _endpoint_reference,
    _endpoint_specs_for_routing,
    _ensure_netlist_terminals,
    _estimate_occupied_cells,
    _extract_buses,
    _extract_labels,
    _extract_uuid,
    _extract_wires,
    _functional_zone_origin,
    _get_symbol_bboxes,
    _has_point,
    _insert_junctions_for_batch,
    _is_power_net,
    _keepout_occupied_cells,
    _manhattan_segments,
    _net_endpoints,
    _net_name,
    _netlist_layout_point,
    _normalize_anchor_refs,
    _normalize_keepout_region,
    _normalize_net_endpoint,
    _normalize_schematic_wire_connectivity,
    _order_refs_by_connectivity,
    _parse_symbol_block,
    _point_near_existing,
    _refs_for_net,
    _remove_wire_blocks,
    _resolve_net_endpoint,
    _route_avoiding_obstacles,
    _route_crosses_obstacle,
    _segment_intersects_bbox,
    _set_point,
    _sheet_usable_cols,
    _sheet_usable_rows,
    _snap_notice,
    _snap_point,
    _wire_segments_from_content,
    _wire_signature,
)
from kicad_mcp.utils.sexpr import (
    _escape_sexpr_string,
    _extract_block,
    _sexpr_string,
    _unescape_sexpr_string,
)


def test_sexpr_escape_and_unescape_roundtrip() -> None:
    value = 'Line 1\nQuoted "value" and \\ slash'
    encoded = _sexpr_string(value)

    assert encoded == '"Line 1\\nQuoted \\"value\\" and \\\\ slash"'
    assert _unescape_sexpr_string(encoded[1:-1]) == value


def test_extract_block_ignores_parentheses_inside_strings() -> None:
    content = '(root (symbol "value(with parens)") (other "a \\"quoted\\" value"))'
    start = content.index("(symbol")

    block, length = _extract_block(content, start)

    assert block == '(symbol "value(with parens)")'
    assert length == len(block)


def test_extract_block_returns_empty_when_unbalanced() -> None:
    assert _extract_block('(symbol "unterminated"', 0) == ("", 0)


def test_escape_normalizes_carriage_returns() -> None:
    assert _escape_sexpr_string("line1\r\nline2\rline3") == "line1\\nline2\\nline3"


def test_detect_t_intersections_finds_endpoint_on_segment_midpoint() -> None:
    wires = [(0.0, 0.0, 20.0, 0.0), (10.0, -10.0, 10.0, 0.0)]

    assert _detect_t_intersections(wires) == [(10.0, 0.0)]


def test_insert_junctions_for_batch_avoids_duplicates() -> None:
    content = (
        "(kicad_sch\n"
        "\t(wire (pts (xy 0 0) (xy 20 0))\n"
        "\t\t(stroke (width 0) (type default))\n"
        '\t\t(uuid "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")\n'
        "\t)\n"
        "\t(sheet_instances)\n"
        "\t(junction (at 10 0)\n"
        "\t\t(diameter 0)\n"
        '\t\t(uuid "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")\n'
        "\t)\n"
        ")"
    )

    updated = _insert_junctions_for_batch(content, [(10.0, 0.0), (15.0, 0.0)])

    assert updated.count("(junction") == 2
    assert "(at 15 0)" in updated


def test_deduplicate_segments_removes_duplicates_and_merges_collinear_runs() -> None:
    segments = [
        (0.0, 0.0, 10.0, 0.0),
        (10.0, 0.0, 20.0, 0.0),
        (20.0, 0.0, 10.0, 0.0),
        (5.0, 5.0, 5.0, 10.0),
    ]

    assert _deduplicate_segments(segments) == [
        (0.0, 0.0, 20.0, 0.0),
        (5.0, 5.0, 5.0, 10.0),
    ]


def test_route_avoiding_obstacles_uses_z_route_when_l_shape_crosses_symbol() -> None:
    obstacle = BBox(x_min=5.0, y_min=-2.0, x_max=15.0, y_max=2.0)

    segments, warning = _route_avoiding_obstacles(
        (0.0, 0.0),
        (20.0, 0.0),
        [obstacle],
        snap_to_grid=False,
    )

    assert warning is None
    assert len(segments) >= 3
    assert any(segment[1] < -2.0 or segment[1] > 2.0 for segment in segments)
    assert not any(
        segment[1] == segment[3] == 0.0
        and max(min(segment[0], segment[2]), 5.0) <= min(max(segment[0], segment[2]), 15.0)
        for segment in segments
    )


def test_schematic_classification_and_grid_helpers_cover_edge_cases() -> None:
    assert _classify_symbol("TP1", "", "") == "testpoint"
    assert _classify_symbol("SW1", "", "") == "ui"
    assert _classify_symbol("BZ1", "", "") == "ui"
    assert _classify_symbol("F1", "", "") == "protection"
    assert _classify_symbol("FB1", "", "") == "filter"
    assert _classify_symbol("C1", "", "") == "passive_cap"
    assert _classify_symbol("R1", "", "") == "passive_res"
    assert _classify_symbol("Q1", "", "") == "transistor"
    assert _classify_symbol("D1", "USBLC6 ESD", "") == "protection"
    assert _classify_symbol("U1", "", "MCU_RaspberryPi:RP2040") == "mcu"
    assert _classify_symbol("U2", "", "Sensor:BME280") == "sensor"
    assert _classify_symbol("U3", "AMS1117", "") == "power_ic"
    assert _classify_symbol("U4", "", "Protection:USBLC6") == "protection"
    assert _classify_symbol("U5", "", "Logic:74HC00") == "ic"
    assert _classify_symbol("Y1", "", "") == "misc"

    occupied = _estimate_occupied_cells([{"x": 50.8, "y": 50.8}, {"x": None, "y": 100.0}])
    assert (0, 0) in occupied
    assert _sheet_usable_cols("UNKNOWN") >= 1
    assert _sheet_usable_rows("A4") >= 1
    assert tuple(round(value, 2) for value in _auto_layout_point(5)) == (76.2, 68.58)
    assert _netlist_layout_point(4) == (50.8, 86.36)
    assert _normalize_keepout_region((4.0, 3.0, 1.0, 2.0)) == (1.0, 2.0, 4.0, 3.0)
    blocked = _keepout_occupied_cells([(50.0, 50.0, 55.0, 55.0)], cell_w=25.4, cell_h=17.78)
    assert blocked
    assert _point_near_existing(51.0, 51.0, [{"reference": "U1", "x": 50.8, "y": 50.8}])
    assert _point_near_existing(90.0, 90.0, [{"reference": "U1", "x": 50.8, "y": 50.8}]) is None
    assert _normalize_anchor_refs([" U1 ", "U1", "", "C1"]) == ["U1", "C1"]
    assert _functional_zone_origin("connector", max_cols=4, max_rows=4, spacing_mm=30.0) == (0, 0)


def test_schematic_netlist_helpers_layout_missing_terminals() -> None:
    assert _coord_value({"x_mm": "12.7"}, "x") == 12.7
    item: dict[str, object] = {}
    assert not _has_point(item)
    _set_point(item, 12.71, 15.24)
    assert item["x_mm"] == 12.7
    assert _has_point(item)
    assert _net_name({"label": "VIN"}) == "VIN"
    assert _is_power_net("+3V3")
    assert _normalize_net_endpoint("U1.2") == {"reference": "U1", "pin": "2"}
    assert _normalize_net_endpoint("GND") == {"power": "GND"}
    assert _normalize_net_endpoint("SENSE") == {"label": "SENSE"}
    assert _normalize_net_endpoint(123) == {}

    net = {"name": "MID", "connections": ["U1.1", {"ref": "R1", "pin_name": "2"}]}
    endpoints = _net_endpoints(net)
    assert _endpoint_reference(endpoints[0]) == "U1"
    assert _endpoint_pin(endpoints[1]) == "2"
    assert _endpoint_power({"type": "power", "name": "+5V"}) == "+5V"
    assert _endpoint_label({"type": "label", "name": "OUT"}) == "OUT"
    assert _refs_for_net(net, {"U1", "R1", "C1"}) == ["U1", "R1"]
    assert _order_refs_by_connectivity(
        ["U1", "R1", "C1"],
        [
            {"name": "N1", "endpoints": ["U1.1", "R1.1"]},
            {"name": "N2", "endpoints": ["R1.2", "C1.1"]},
        ],
    ) == ["U1", "R1", "C1"]
    assert _average_position(["U1", "U9"], {"U1": (10.0, 20.0)}) == (10.0, 20.0)
    assert _average_position(["U9"], {"U1": (10.0, 20.0)}) is None

    powers: list[dict[str, object]] = []
    labels: list[dict[str, object]] = []
    nets = [{"name": "+3V3", "endpoints": ["U1.1"]}, {"name": "OUT", "endpoints": ["U1.2"]}]
    _ensure_netlist_terminals(powers, labels, nets)
    assert powers == [{"name": "+3V3"}]
    assert labels == [{"name": "OUT"}]

    symbols, laid_powers, laid_labels, netlist_paper = _apply_netlist_auto_layout(
        [{"reference": "U1"}, {"reference": "R1"}],
        [{"name": "GND"}],
        [{"name": "OUT"}],
        [{"name": "GND", "endpoints": ["U1.1", "R1.1"]}, {"name": "OUT", "endpoints": ["R1.2"]}],
    )
    assert all(_has_point(symbol) for symbol in symbols)
    assert laid_powers[0]["name"] == "GND"
    assert _has_point(laid_powers[0])
    assert laid_labels[0]["name"] == "OUT"
    assert _has_point(laid_labels[0])
    assert netlist_paper == "A4"  # a 2-symbol circuit fits the default sheet
    basic_symbols, basic_powers, basic_labels, basic_paper = _apply_basic_auto_layout(
        [{"reference": "R1"}],
        [{"name": "GND"}, {"name": "+5V"}],
        [{"name": "OUT"}],
    )
    assert all(_has_point(entry) for entry in [*basic_symbols, *basic_powers, *basic_labels])
    assert basic_paper == "A4"


def test_schematic_file_parsers_and_wire_normalization() -> None:
    content = (
        "(kicad_sch\n"
        '\t(uuid "11111111-1111-1111-1111-111111111111")\n'
        '\t(symbol (lib_id "Device:R") (at 50.8 50.8 0) (unit 1)\n'
        '\t\t(property "Reference" "R1" (at 0 0 0))\n'
        '\t\t(property "Value" "10k" (at 0 0 0))\n'
        '\t\t(property "Footprint" "Resistor_SMD:R_0805" (at 0 0 0))\n'
        "\t)\n"
        '\t(label "OUT" (at 60.96 50.8 0))\n'
        "\t(bus (pts (xy 0 0) (xy 10 0)))\n"
        '\t(wire (pts (xy 0 0) (xy 20 0)) (uuid "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"))\n'
        '\t(wire (pts (xy 0 0) (xy 20 0)) (uuid "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"))\n'
        '\t(wire (pts (xy 10 -5) (xy 10 0)) (uuid "cccccccc-cccc-cccc-cccc-cccccccccccc"))\n'
        "\t(sheet_instances)\n"
        ")"
    )

    assert _extract_uuid(content) == "11111111-1111-1111-1111-111111111111"
    assert _parse_symbol_block(content)["reference"] == "R1"  # type: ignore[index]
    assert _extract_buses(content) == [{"x1": 0.0, "y1": 0.0, "x2": 10.0, "y2": 0.0}]
    assert len(_extract_labels(content)) == 1
    assert len(_extract_wires(content)) == 3
    assert _wire_segments_from_content(content)[0] == (0.0, 0.0, 20.0, 0.0)
    assert len(_get_symbol_bboxes(content)) == 1
    assert "(wire" not in _remove_wire_blocks(content)
    normalized = _normalize_schematic_wire_connectivity(content)
    assert normalized.count("(wire") == 2
    assert "(junction (at 10 0)" in normalized
    assert _wire_signature(10.0, 0.0, 0.0, 0.0) == ((0.0, 0.0), (10.0, 0.0))


def test_schematic_routing_endpoint_helpers_cover_fallbacks() -> None:
    assert _snap_point(1.1, 2.2, enabled=False) == (1.1, 2.2)
    assert _snap_notice((1.0, 2.0), (1.0, 2.0)) == ""
    assert _manhattan_segments((0.0, 0.0), (0.0, 0.0), False) == []
    assert _manhattan_segments((0.0, 0.0), (10.0, 0.0), False) == [(0.0, 0.0, 10.0, 0.0)]

    bbox = BBox(2.0, -1.0, 8.0, 1.0)
    assert _segment_intersects_bbox((0.0, 0.0, 10.0, 0.0), bbox)
    assert _route_crosses_obstacle([(0.0, 0.0, 10.0, 0.0)], [bbox])
    direct, warning = _route_avoiding_obstacles((0.0, 0.0), (0.0, 10.0), [], False)
    assert warning is None
    assert direct == [(0.0, 0.0, 0.0, 10.0)]

    symbol_points = {"U1": {"1": (1.0, 1.0), "vcc": (2.0, 2.0)}}
    aliases = {"U1": {"VCC": (2.0, 2.0), "vcc": (2.0, 2.0)}}
    centers = {"U1": (5.0, 5.0)}
    powers = {"GND": (0.0, 10.0)}
    labels = {"OUT": (20.0, 10.0)}
    assert _resolve_net_endpoint(
        {"reference": "U1", "pin": "1"},
        "N1",
        symbol_points,
        aliases,
        centers,
        powers,
        labels,
    ) == (
        (1.0, 1.0),
        None,
        "pin_number",
    )
    assert (
        _resolve_net_endpoint(
            {"reference": "U1", "pin": "VCC"},
            "N1",
            symbol_points,
            aliases,
            centers,
            powers,
            labels,
        )[2]
        == "pin_alias"
    )
    assert (
        _resolve_net_endpoint(
            {"reference": "U9"},
            "N1",
            symbol_points,
            aliases,
            centers,
            powers,
            labels,
        )[2]
        == "missing_reference"
    )
    assert (
        _resolve_net_endpoint(
            {"power": "GND"},
            "GND",
            symbol_points,
            aliases,
            centers,
            powers,
            labels,
        )[2]
        == "power"
    )
    assert (
        _resolve_net_endpoint(
            {"label": "OUT"},
            "OUT",
            symbol_points,
            aliases,
            centers,
            powers,
            labels,
        )[2]
        == "label"
    )
    assert (
        _resolve_net_endpoint(
            {},
            "+3V3",
            symbol_points,
            aliases,
            centers,
            powers,
            labels,
        )[2]
        == "missing_power"
    )
    assert _endpoint_specs_for_routing({"name": "OUT", "endpoints": []}, powers, labels) == [
        {"label": "OUT"}
    ]
    assert _describe_net_endpoint({"reference": "U1", "pin": "1"}) == "U1.1"
    assert _describe_net_endpoint({"power": "GND"}) == "power:GND"
    assert _describe_net_endpoint({"label": "OUT"}) == "label:OUT"
    assert _describe_net_endpoint({}) == "<unresolved-endpoint>"


def test_terminal_stub_length_scales_with_net_name() -> None:
    from kicad_mcp.tools.schematic import SCHEMATIC_GRID_MM, _terminal_stub_length

    # Short names keep the historical 5.08 mm stub; long names are pushed out so
    # the global-label text clears the symbol body, snapped to the configured
    # schematic grid. The default grid is 50 mil, but deployments may override it.
    assert _terminal_stub_length("GND") == 5.08
    assert _terminal_stub_length("3V3") == 5.08
    long_stub = _terminal_stub_length("VBUS_5V")
    assert long_stub > 5.08
    assert abs(long_stub / SCHEMATIC_GRID_MM - round(long_stub / SCHEMATIC_GRID_MM)) < 1e-6


def test_pin_alias_resolves_diff_pair_and_duplicate_contacts() -> None:
    from kicad_mcp.tools.schematic import _pin_alias_positions

    # A connector-like block: D+ appears on two contacts (same signal), D- once.
    # Differential +/- names must stay distinct; the duplicated D+ must not drop.
    block = (
        '(symbol "X_1_1"'
        ' (pin passive line (at 0 5.08 0) (length 2.54) (name "D+") (number "1"))'
        ' (pin passive line (at 0 -5.08 0) (length 2.54) (name "D-") (number "2"))'
        ' (pin passive line (at 0 7.62 0) (length 2.54) (name "D+") (number "3")))'
    )
    aliases = _pin_alias_positions(block, 0.0, 0.0, 0)
    assert "D+" in aliases and "D-" in aliases
    assert aliases["D+"] != aliases["D-"]
    # The normalized "d" (D+ vs D- collision) is ambiguous and must be dropped.
    assert "d" not in aliases
    # Pin numbers still resolve.
    assert aliases["1"] == aliases["D+"]  # keep-first contact for D+
