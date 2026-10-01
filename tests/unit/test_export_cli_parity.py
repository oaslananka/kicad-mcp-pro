"""Unit tests for export CLI parity tools (FAZ 2.5–2.6).
Tools: export_brep, export_gencad, export_glb, export_ipc_d356,
export_ply, export_ps, export_stl, export_u3d, export_vrml.
"""

from __future__ import annotations

import pytest

from kicad_mcp.server import create_server
from kicad_mcp.tools.export import (
    _format_file_list,
    _human_size,
)


def test_human_size_bytes() -> None:
    assert "B" in _human_size(500)
    assert "KB" in _human_size(2048)
    assert "MB" in _human_size(2_000_000)


def test_format_file_list_empty() -> None:
    result = _format_file_list([], "Test")
    assert "No files" in result


def test_format_file_list_with_files(tmp_path) -> None:  # type: ignore[no-untyped-def]
    f1 = tmp_path / "a.txt"
    f1.write_text("hello")
    result = _format_file_list([f1], "Files:")
    assert "a.txt" in result


@pytest.mark.parametrize("fmt", ["csv", "ascii"])
def test_export_pick_and_place_args(fmt: str) -> None:
    """export_pick_and_place should accept 'variant' param after FAZ 8.2."""
    server = create_server()
    for tool in server.list_tools():
        if tool.name == "export_pick_and_place":
            props = tool.input_schema.get("properties", {})
            assert "variant" in props
            break
    else:
        pytest.fail("export_pick_and_place tool not found")
