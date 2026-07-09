from __future__ import annotations

import pytest

from kicad_mcp.server import build_server
from tests.conftest import get_prompt_text


@pytest.mark.anyio
async def test_workflow_prompts_expose_v3_canonical_sequences() -> None:
    server = build_server("full")

    first = await get_prompt_text(server, "first_pcb", {"component_count": "5"})
    schematic = await get_prompt_text(server, "schematic_to_pcb", {})
    professional = await get_prompt_text(
        server,
        "professional_circuit_design",
        {"circuit_description": "USB sensor", "target_fab": "pcbway_standard"},
    )
    post_route = await get_prompt_text(server, "post_placement_routing", {})
    manufacturing = await get_prompt_text(server, "manufacturing_export", {})
    review = await get_prompt_text(server, "design_review_loop", {})
    visual = await get_prompt_text(server, "visual_excellence_loop", {})
    blocking = await get_prompt_text(server, "fix_blocking_issues", {})
    release = await get_prompt_text(server, "manufacturing_release_checklist", {})
    high_speed = await get_prompt_text(server, "high_speed_review_loop", {})
    bringup = await get_prompt_text(server, "new_board_bringup", {})
    dfm = await get_prompt_text(server, "dfm_polish_loop", {})
    regression = await get_prompt_text(server, "regression_sweep", {})

    assert "approximately 5 components" in first
    assert "route_autoroute_freerouting" in schematic
    assert "USB sensor" in professional
    assert "pcbway_standard" in professional
    assert "post-placement routing loop" in post_route
    assert "export_manufacturing_package" in manufacturing
    assert "kicad://project/fix_queue" in review
    assert "sch_cosmetic_score" in visual
    assert "connectivity_preserved" in visual
    assert "project_get_next_action" in blocking
    assert "Treat manufacturing release as a gated handoff" in release
    assert "critical nets" in high_speed
    assert "Bring up a new board" in bringup
    assert "manufacturer profile" in dfm
    assert "regression sweep" in regression
