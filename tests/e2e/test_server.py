from __future__ import annotations

import pytest

from kicad_mcp.server import build_server


@pytest.mark.anyio
async def test_server_registers_tools_resources_and_prompts(sample_project, mock_board) -> None:
    server = build_server("minimal")
    tool_names = {tool.name for tool in await server.list_tools()}
    resource_uris = {str(resource.uri) for resource in await server.list_resources()}
    prompt_names = {prompt.name for prompt in await server.list_prompts()}
    resource_templates = {
        template.uri_template for template in await server.list_resource_templates()
    }

    assert "kicad_get_version" in tool_names
    assert "kicad_set_project" in tool_names
    assert "export_odb" in tool_names
    assert "kicad://board/summary" in resource_uris
    assert "kicad://project/quality_gate" in resource_uris
    assert "kicad://project/fix_queue" in resource_uris
    assert "kicad://project/spec" in resource_uris
    assert "kicad://project/manifest" in resource_uris
    assert "kicad://project/gate_history" in resource_uris
    assert "kicad://project/design_intent" in resource_uris
    assert "kicad://project/next_action" in resource_uris
    assert "kicad://schematic/connectivity" in resource_uris
    assert "kicad://board/placement_quality" in resource_uris
    assert "kicad://board/layer_coverage" in resource_uris
    assert "kicad://analysis/materials" in resource_uris
    assert "kicad://analysis/defaults" in resource_uris
    assert "kicad://analysis/stackup" in resource_uris
    assert "kicad://gate/{gate_name}" in resource_templates
    assert "first_pcb" in prompt_names
    assert "design_review_loop" in prompt_names
    assert "fix_blocking_issues" in prompt_names
    assert "manufacturing_release_checklist" in prompt_names
    assert "high_speed_review_loop" in prompt_names
    assert "new_board_bringup" in prompt_names
    assert "dfm_polish_loop" in prompt_names
    assert "regression_sweep" in prompt_names
