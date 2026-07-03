from __future__ import annotations

import json

import pytest

from kicad_mcp.server import build_server
from tests.conftest import call_tool_text

pytestmark = pytest.mark.mcp_mode("experimental")


@pytest.mark.anyio
async def test_sch_set_hop_over_updates_project_file(sample_project) -> None:
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    result = await call_tool_text(server, "sch_set_hop_over", {"enabled": False})

    payload = json.loads((sample_project / "demo.kicad_pro").read_text(encoding="utf-8"))
    assert "disabled" in result
    assert payload["schematic"]["hop_over_display"] is False


@pytest.mark.anyio
async def test_route_tune_time_domain_uses_stackup_when_available(
    sample_project,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})
    await call_tool_text(
        server,
        "pcb_set_stackup",
        {
            "layers": [
                {"name": "F.Cu", "type": "signal", "thickness_mm": 0.035, "material": "Copper"},
                {
                    "name": "Dielectric1",
                    "type": "dielectric",
                    "thickness_mm": 0.18,
                    "material": "FR4",
                    "epsilon_r": 4.2,
                },
                {"name": "B.Cu", "type": "signal", "thickness_mm": 0.035, "material": "Copper"},
            ]
        },
    )
    await call_tool_text(
        server,
        "route_create_tuning_profile",
        {
            "name": "usb",
            "layer": "F.Cu",
            "trace_impedance_ohm": 90.0,
            "propagation_speed_factor": 0.5,
        },
    )
    monkeypatch.setattr(
        "kicad_mcp.tools.routing._current_track_length_for_pattern_mm",
        lambda _pattern: 12.5,
    )

    result = await call_tool_text(
        server,
        "route_tune_time_domain",
        {
            "net_or_group": "USB_D+",
            "target_delay_ps": 120.0,
            "tolerance_ps": 8.0,
            "layer": "F.Cu",
        },
    )

    assert "Effective dielectric constant" in result
    assert "Computed target length" in result
    assert "Required extension" in result


@pytest.mark.anyio
async def test_drc_rule_tools_round_trip_through_parsed_dru(sample_project) -> None:
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    created = await call_tool_text(
        server,
        "drc_rule_create",
        {
            "name": "Tight Clearance",
            "constraint_type": "clearance",
            "min_value": "0.15mm",
            "condition": "A.NetClass == 'HS'",
            "severity": "warning",
        },
    )
    listing = json.loads(await call_tool_text(server, "drc_list_rules", {}))
    disabled = await call_tool_text(
        server,
        "drc_rule_enable",
        {"rule_name": "Tight Clearance", "enabled": False},
    )
    relisted = json.loads(await call_tool_text(server, "drc_list_rules", {}))
    dru_text = (sample_project / "demo.kicad_dru").read_text(encoding="utf-8")
    deleted = await call_tool_text(
        server,
        "drc_rule_delete",
        {"rule_name": "Tight Clearance"},
    )

    rules = {item["name"]: item for item in listing["rules"] if item.get("source") != "built-in"}
    relisted_rules = {
        item["name"]: item for item in relisted["rules"] if item.get("source") != "built-in"
    }

    assert "Tight Clearance" in created
    assert rules["Tight Clearance"]["constraints"] == ["clearance"]
    assert "disabled" in disabled
    assert relisted_rules["Tight Clearance"]["enabled"] is False
    assert "(severity ignore)" in dru_text
    assert "Deleted custom DRC rule" in deleted


@pytest.mark.anyio
async def test_drc_check_rule_conflicts_flags_contradictory_minimums(sample_project) -> None:
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    for name, minimum in (("hs_a", "0.2mm"), ("hs_b", "0.3mm")):
        await call_tool_text(
            server,
            "drc_rule_create",
            {
                "name": name,
                "constraint_type": "clearance",
                "min_value": minimum,
                "condition": "A.NetClass == 'HS'",
            },
        )

    report = json.loads(await call_tool_text(server, "drc_check_rule_conflicts", {}))

    assert report["conflict_count"] >= 1
    contradictions = [c for c in report["conflicts"] if c["kind"] == "contradictory_constraint"]
    assert contradictions, report
    assert set(contradictions[0]["rules"]) == {"hs_a", "hs_b"}
    assert "Tight Clearance" not in (sample_project / "demo.kicad_dru").read_text(encoding="utf-8")


@pytest.mark.anyio
async def test_pcb_add_barcode_accepts_code128_and_inner_layer_graphics_require_4_layers(
    sample_project,
) -> None:
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})
    await call_tool_text(
        server,
        "pcb_set_stackup",
        {
            "layers": [
                {"name": "F.Cu", "type": "signal", "thickness_mm": 0.035, "material": "Copper"},
                {
                    "name": "Dielectric1",
                    "type": "dielectric",
                    "thickness_mm": 0.2,
                    "material": "FR4",
                    "epsilon_r": 4.2,
                },
                {"name": "B.Cu", "type": "signal", "thickness_mm": 0.035, "material": "Copper"},
            ]
        },
    )

    barcode = await call_tool_text(
        server,
        "pcb_add_barcode",
        {
            "content": "SN-001",
            "x_mm": 10.0,
            "y_mm": 12.0,
            "barcode_type": "code128",
        },
    )
    inner_layer = await call_tool_text(
        server,
        "add_footprint_inner_layer_graphic",
        {
            "reference": "U1",
            "layer": "In1.Cu",
            "shape_type": "text",
            "text": "INNER",
        },
    )

    pcb_text = (sample_project / "demo.kicad_pcb").read_text(encoding="utf-8")
    assert "Barcode added" in barcode
    assert "(barcode" in pcb_text
    assert '(text "SN-001")' in pcb_text
    assert '(type "code128")' in pcb_text
    assert "at least four copper layers" in inner_layer


@pytest.mark.anyio
async def test_pcb_add_bitmap_board_art_imports_logo_pixels(sample_project) -> None:
    from PIL import Image

    image_path = sample_project / "logo.png"
    image = Image.new("L", (4, 4), 255)
    for pixel in [(0, 0), (1, 1), (2, 2), (3, 3)]:
        image.putpixel(pixel, 0)
    image.save(image_path)

    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})
    result = await call_tool_text(
        server,
        "pcb_add_bitmap_board_art",
        {
            "source_image": str(image_path),
            "x_mm": 12.0,
            "y_mm": 14.0,
            "width_mm": 4.0,
            "layer": "F.SilkS",
            "threshold": 128,
            "max_pixels": 16,
        },
    )

    pcb_text = (sample_project / "demo.kicad_pcb").read_text(encoding="utf-8")
    assert "Bitmap board art imported" in result
    assert "as 4 shape(s)" in result
    assert "(gr_rect" in pcb_text
    assert '(layer "F.SilkS")' in pcb_text
