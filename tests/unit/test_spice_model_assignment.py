"""Unit tests for SPICE model assignment tools (FAZ 4).
Tools: sim_list_spice_libraries, sim_validate_spice_setup,
sim_assign_spice_model, sim_add_spice_library, sim_remove_spice_library.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kicad_mcp.server import create_server
from tests.conftest import call_tool_text


@pytest.mark.anyio
async def test_list_spice_libraries_default(tmp_path: Path) -> None:
    # Create a minimal project so tools requiring a project can run
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "demo.kicad_pro").write_text(
        '{"libraries":[{"name":"Default","type":"Spice","uri":"models/default.lib"}]}',
        encoding="utf-8",
    )
    (proj / "demo.kicad_pcb").write_text("", encoding="utf-8")
    (proj / "demo.kicad_sch").write_text("", encoding="utf-8")
    server = create_server()
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(proj)})
    result = await call_tool_text(server, "sim_list_spice_libraries", {})
    assert "SPICE libraries (1):" in result
    assert "Default: models/default.lib" in result


@pytest.mark.anyio
async def test_validate_spice_setup_without_project() -> None:
    server = create_server()
    result = await call_tool_text(server, "sim_validate_spice_setup", {})
    assert result is not None


@pytest.mark.anyio
async def test_assign_model_rejects_nonexistent_model() -> None:
    server = create_server()
    result = await call_tool_text(
        server,
        "sim_assign_spice_model",
        {"reference": "Q1", "model_path": "/nonexistent/model.lib", "model_name": "2N3904"},
    )
    assert "error" in result.lower() or "No project" in result or "not found" in result.lower()
