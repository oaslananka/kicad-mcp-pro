from __future__ import annotations

import pytest

from kicad_mcp.server import build_server


@pytest.mark.anyio
async def test_server_registers_tools_resources_and_prompts(sample_project, mock_board) -> None:
    server = build_server("minimal")
    tool_names = {tool.name for tool in await server.list_tools()}
    resource_uris = {str(resource.uri) for resource in await server.list_resources()}
    prompt_names = {prompt.name for prompt in await server.list_prompts()}

    assert "kicad_get_version" in tool_names
    assert "kicad_set_project" in tool_names
    assert "kicad://board/summary" in resource_uris
    assert "first_pcb" in prompt_names
