from __future__ import annotations

import json
from pathlib import Path

import pytest
from mcp.types import ImageContent

from kicad_mcp.server import build_server
from tests.conftest import call_tool_content, call_tool_text, tool_text


@pytest.mark.anyio
async def test_schematic_live_preview_reports_failed_render_without_image(
    sample_project,
    mock_kicad,
    monkeypatch,
) -> None:
    server = build_server("schematic")

    await call_tool_text(
        server,
        "sch_live_preview",
        {"include_child_sheets": False, "render": False},
    )
    await call_tool_text(
        server,
        "sch_add_label",
        {"name": "FAIL_PREVIEW", "x_mm": 12.7, "y_mm": 12.7},
    )
    await call_tool_text(
        server,
        "sch_live_preview",
        {"include_child_sheets": False, "render": False, "debounce_ms": 1000},
    )

    def fake_export(sch_file: Path, out_dir: Path, *, include_title_block: bool):
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"{sch_file.stem}.svg").write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="32" height="16" />',
            encoding="utf-8",
        )
        return 0, "", ""

    def fake_render(svg_file: Path, output_file: Path, *, dpi: int, crop_to_content: bool):
        raise RuntimeError("renderer unavailable")

    monkeypatch.setattr(
        "kicad_mcp.tools.schematic._export_schematic_svg_for_render",
        fake_export,
    )
    monkeypatch.setattr("kicad_mcp.tools.schematic._render_svg_to_png", fake_render)

    content = await call_tool_content(
        server,
        "sch_live_preview",
        {
            "include_child_sheets": False,
            "debounce_ms": 0,
            "render": True,
            "output_file": "live-preview-failed.png",
        },
    )
    payload = json.loads(tool_text(content))

    assert payload["status"] == "changed"
    assert payload["outcome"] == "error"
    assert payload["render"]["status"] == "failed"
    assert payload["render"]["message"] == "renderer unavailable"
    assert payload["next_actions"] == ["Inspect warnings and renderer diagnostics before retrying."]
    assert not any(isinstance(item, ImageContent) for item in content)
