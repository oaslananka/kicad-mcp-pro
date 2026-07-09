"""Unit tests for schematic visual baseline regression (Visual Excellence Loop, Phase D).

The pixel-comparison logic is tested with Pillow-generated PNGs so it runs without
kicad-cli or a live KiCad; the render-backed tool paths are exercised only for
their non-rendering branches (bad dpi, missing baseline).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from kicad_mcp.tools.schematic import _render_png_visual_diff
from kicad_mcp.tools.visual_baseline import _drift_from_diff

pytest.importorskip("PIL")


def _solid_png(path: Path, color: tuple[int, int, int], size: tuple[int, int] = (40, 40)) -> Path:
    from PIL import Image

    Image.new("RGB", size, color).save(path)
    return path


def test_drift_from_diff_ratio() -> None:
    assert _drift_from_diff({"width_px": 10, "height_px": 10, "changed_pixels": 50}) == (
        50.0,
        50,
        100,
    )
    assert _drift_from_diff({"width_px": 10, "height_px": 10, "changed_pixels": 0}) == (0.0, 0, 100)
    # Degenerate/empty metadata never divides by zero.
    assert _drift_from_diff({}) == (0.0, 0, 0)


def test_identical_renders_have_zero_drift(tmp_path: Path) -> None:
    base = _solid_png(tmp_path / "base.png", (255, 255, 255))
    same = _solid_png(tmp_path / "same.png", (255, 255, 255))
    diff_meta = _render_png_visual_diff(base, same, tmp_path / "diff.png")
    drift_pct, changed, total = _drift_from_diff(diff_meta)
    assert drift_pct == 0.0
    assert changed == 0
    assert total == 40 * 40


def test_changed_render_reports_drift(tmp_path: Path) -> None:
    from PIL import Image

    base = _solid_png(tmp_path / "base.png", (255, 255, 255))
    changed_img = Image.new("RGB", (40, 40), (255, 255, 255))
    # Paint a 10x40 black stripe → 25% of the pixels differ.
    for x in range(10):
        for y in range(40):
            changed_img.putpixel((x, y), (0, 0, 0))
    changed_path = tmp_path / "changed.png"
    changed_img.save(changed_path)

    diff_meta = _render_png_visual_diff(base, changed_path, tmp_path / "diff.png")
    drift_pct, changed_pixels, total = _drift_from_diff(diff_meta)
    assert drift_pct == pytest.approx(25.0, abs=0.1)
    assert changed_pixels == 400
    assert (tmp_path / "diff.png").is_file()


@pytest.mark.anyio
@pytest.mark.mcp_mode("write")
async def test_compare_reports_no_baseline(sample_project: Path) -> None:
    from kicad_mcp.server import build_server
    from tests.conftest import call_tool_text

    server = build_server("schematic")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})
    raw = await call_tool_text(server, "sch_visual_baseline_compare", {})
    payload = json.loads(raw)
    assert payload["status"] == "no_baseline"


@pytest.mark.anyio
@pytest.mark.mcp_mode("write")
async def test_baseline_tools_reject_bad_dpi(sample_project: Path) -> None:
    from kicad_mcp.server import build_server
    from tests.conftest import call_tool_text

    server = build_server("schematic")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})
    for tool in ("sch_visual_baseline_set", "sch_visual_baseline_compare"):
        raw = await call_tool_text(server, tool, {"dpi": 9999})
        payload = json.loads(raw)
        assert payload["status"] == "error"
        assert "dpi" in payload["message"]
