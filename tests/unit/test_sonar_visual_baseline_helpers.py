"""Visual-baseline extraction preserves rendering errors and metadata contracts."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from kicad_mcp.tools import visual_baseline


def test_capture_baseline_serializes_source_hash_and_render_options(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "sample.kicad_sch"
    source.write_text("(kicad_sch)", encoding="utf-8")
    baseline = tmp_path / "sample.png"
    meta = tmp_path / "sample.json"
    observed: dict[str, object] = {}

    def render(path: Path, png: Path, **kwargs: object):
        observed.update(path=path, png=png, **kwargs)
        return png, {"width_px": 42}

    monkeypatch.setattr(
        visual_baseline, "_resolve_schematic_target", lambda **_kw: SimpleNamespace(path=source)
    )
    monkeypatch.setattr(visual_baseline, "_baseline_png", lambda _stem: baseline)
    monkeypatch.setattr(visual_baseline, "_baseline_meta", lambda _stem: meta)
    monkeypatch.setattr(visual_baseline, "_render_schematic_png_artifact", render)
    result = json.loads(visual_baseline._capture_visual_baseline(None, None, 225, False))
    assert result["status"] == "captured"
    assert result["sheet"] == "sample"
    assert result["dpi"] == 225
    assert result["include_title_block"] is False
    assert result["source_sha256"] == visual_baseline._sheet_sha256(source)
    assert result["render"] == {"width_px": 42}
    assert observed == {
        "path": source,
        "png": baseline,
        "dpi": 225,
        "crop_to_content": True,
        "include_title_block": False,
    }
    assert json.loads(meta.read_text(encoding="utf-8"))["source_sha256"] == result["source_sha256"]


def test_capture_baseline_failures_do_not_write_metadata(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    meta = tmp_path / "sample.json"
    monkeypatch.setattr(visual_baseline, "_baseline_meta", lambda _stem: meta)
    assert (
        json.loads(visual_baseline._capture_visual_baseline(None, None, 1000, True))["status"]
        == "error"
    )

    def resolve_error(**_kwargs: object):
        raise ValueError("unknown sheet")

    monkeypatch.setattr(visual_baseline, "_resolve_schematic_target", resolve_error)
    assert (
        json.loads(visual_baseline._capture_visual_baseline(None, None, 200, True))["message"]
        == "unknown sheet"
    )

    monkeypatch.setattr(
        visual_baseline,
        "_resolve_schematic_target",
        lambda **_kw: SimpleNamespace(path=tmp_path / "sample.kicad_sch"),
    )
    monkeypatch.setattr(visual_baseline, "_baseline_png", lambda _stem: tmp_path / "sample.png")

    def render_error(*_args: object, **_kwargs: object):
        raise RuntimeError("render unavailable")

    monkeypatch.setattr(visual_baseline, "_render_schematic_png_artifact", render_error)
    result = json.loads(visual_baseline._capture_visual_baseline(None, None, 200, True))
    assert result["status"] == "error"
    assert result["message"] == "Baseline render failed: render unavailable"
    assert meta.exists() is False


def test_compare_baseline_pass_and_failure_modes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "sample.kicad_sch"
    baseline = tmp_path / "sample.png"
    current = tmp_path / "sample.current.png"
    diff = tmp_path / "sample.drift.png"
    monkeypatch.setattr(
        visual_baseline, "_resolve_schematic_target", lambda **_kw: SimpleNamespace(path=source)
    )
    monkeypatch.setattr(visual_baseline, "_baseline_png", lambda _stem: baseline)
    assert (
        json.loads(visual_baseline._compare_visual_baseline(None, None, 999, True, 2.0))["status"]
        == "error"
    )
    assert (
        json.loads(visual_baseline._compare_visual_baseline(None, None, 200, True, 2.0))["status"]
        == "no_baseline"
    )
    baseline.touch()
    monkeypatch.setattr(
        visual_baseline, "_read_visual_baseline_metadata", lambda _stem: {"dpi": 180}
    )
    observed: list[object] = []

    def compare(*args: object):
        observed.extend(args)
        return (
            current,
            diff,
            {"width_px": 10, "height_px": 10, "changed_pixels": 1, "changed_bbox_px": [1, 2, 3, 4]},
        )

    monkeypatch.setattr(visual_baseline, "_render_visual_baseline_comparison", compare)
    result = json.loads(visual_baseline._compare_visual_baseline(None, None, 200, True, 2.0))
    assert result["status"] == "PASS"
    assert result["drift_pct"] == 1.0
    assert result["changed_bbox_px"] == [1, 2, 3, 4]
    assert observed == [source, "sample", baseline, 180, True]

    def compare_error(*_args: object):
        raise RuntimeError("diff unavailable")

    monkeypatch.setattr(visual_baseline, "_render_visual_baseline_comparison", compare_error)
    failed = json.loads(visual_baseline._compare_visual_baseline(None, None, 200, True, 2.0))
    assert failed["message"] == "Baseline compare failed: diff unavailable"
