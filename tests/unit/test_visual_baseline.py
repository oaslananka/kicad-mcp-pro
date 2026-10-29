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


def test_baseline_metadata_falls_back_safely(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from kicad_mcp.tools import visual_baseline

    meta = tmp_path / "sample.json"
    monkeypatch.setattr(visual_baseline, "_baseline_meta", lambda _stem: meta)
    assert visual_baseline._read_visual_baseline_metadata("sample") == {}

    meta.write_text("{invalid-json", encoding="utf-8")
    assert visual_baseline._read_visual_baseline_metadata("sample") == {}

    meta.write_text('{"dpi": 240, "sheet": "sample"}', encoding="utf-8")
    assert visual_baseline._read_visual_baseline_metadata("sample") == {
        "dpi": 240,
        "sheet": "sample",
    }


def test_render_comparison_passes_baseline_options(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from kicad_mcp.tools import visual_baseline

    source = tmp_path / "sample.kicad_sch"
    baseline = tmp_path / "sample.png"
    captured: dict[str, object] = {}

    def fake_render(path: Path, output: Path, **kwargs: object) -> tuple[Path, dict]:
        captured.update({"path": path, "output": output, **kwargs})
        return output, {}

    def fake_diff(base: Path, current: Path, diff: Path) -> dict[str, int]:
        assert (base, current, diff) == (
            baseline,
            tmp_path / "sample.current.png",
            tmp_path / "sample.drift.png",
        )
        return {"width_px": 20, "height_px": 20, "changed_pixels": 4}

    monkeypatch.setattr(visual_baseline, "_baseline_dir", lambda: tmp_path)
    monkeypatch.setattr(visual_baseline, "_render_schematic_png_artifact", fake_render)
    monkeypatch.setattr(visual_baseline, "_render_png_visual_diff", fake_diff)
    current, diff, evidence = visual_baseline._render_visual_baseline_comparison(
        source, "sample", baseline, 180, False
    )
    assert current == tmp_path / "sample.current.png"
    assert diff == tmp_path / "sample.drift.png"
    assert evidence["changed_pixels"] == 4
    assert captured == {
        "path": source,
        "output": current,
        "dpi": 180,
        "crop_to_content": True,
        "include_title_block": False,
    }


def test_compare_existing_baseline_obeys_stored_dpi(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from types import SimpleNamespace

    from kicad_mcp.tools import visual_baseline

    class Collector:
        tools: dict[str, object]

        def __init__(self) -> None:
            self.tools = {}

        def tool(self):
            def record(fn):
                self.tools[fn.__name__] = fn
                return fn

            return record

    target = tmp_path / "sample.kicad_sch"
    baseline = tmp_path / "sample.png"
    baseline.touch()
    current = tmp_path / "sample.current.png"
    diff = tmp_path / "sample.drift.png"
    seen: list[tuple] = []

    monkeypatch.setattr(
        visual_baseline, "_resolve_schematic_target", lambda **_kwargs: SimpleNamespace(path=target)
    )
    monkeypatch.setattr(visual_baseline, "_baseline_png", lambda _stem: baseline)
    monkeypatch.setattr(
        visual_baseline, "_read_visual_baseline_metadata", lambda _stem: {"dpi": 180}
    )

    def fake_comparison(*args: object) -> tuple[Path, Path, dict[str, int]]:
        seen.append(args)
        return current, diff, {"width_px": 10, "height_px": 10, "changed_pixels": 5}

    monkeypatch.setattr(visual_baseline, "_render_visual_baseline_comparison", fake_comparison)
    collector = Collector()
    visual_baseline.register(collector)  # type: ignore[arg-type]
    compare = collector.tools["sch_visual_baseline_compare"]
    result = json.loads(compare(dpi=200, threshold_pct=2.0))  # type: ignore[operator]
    assert seen == [(target, "sample", baseline, 180, True)]
    assert result["status"] == "DRIFT"
    assert result["drift_pct"] == 5.0
