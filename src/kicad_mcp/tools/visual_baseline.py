"""Schematic visual baseline regression (Visual Excellence Loop, Phase D).

A cosmetic fix on one sheet, or an unrelated edit, can quietly change how another
sheet renders. These tools capture an approved render of a sheet as a *baseline*
and later compare the current render against it, so unintended visual drift is
caught the same way a snapshot test catches unintended output changes.

The comparison is Pillow-only (pixel difference over the two renders) — no new
heavy dependency. Rendering reuses the existing headless ``kicad-cli`` +
SVG-to-PNG path, so a baseline set/compare needs ``kicad-cli`` and the render
extras just like ``sch_render_png``.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from ..config import get_config
from .metadata import headless_compatible
from .schematic import (
    _render_png_visual_diff,
    _render_schematic_png_artifact,
    _resolve_schematic_target,
)

BASELINE_DIRNAME = ".kicad-mcp"
BASELINE_SUBDIR = "visual_baselines"
DEFAULT_DRIFT_THRESHOLD_PCT = 2.0


def _baseline_dir() -> Path:
    cfg = get_config()
    if cfg.project_dir is None:
        raise ValueError("No active project is configured.")
    target = cfg.project_dir / BASELINE_DIRNAME / BASELINE_SUBDIR
    target.mkdir(parents=True, exist_ok=True)
    return target


def _baseline_png(stem: str) -> Path:
    return _baseline_dir() / f"{stem}.png"


def _baseline_meta(stem: str) -> Path:
    return _baseline_dir() / f"{stem}.json"


def _sheet_sha256(sch_file: Path) -> str:
    return hashlib.sha256(sch_file.read_bytes()).hexdigest()


def _drift_from_diff(diff_meta: dict[str, Any]) -> tuple[float, int, int]:
    """Return ``(drift_pct, changed_pixels, total_pixels)`` from a diff result."""
    width = int(diff_meta.get("width_px", 0) or 0)
    height = int(diff_meta.get("height_px", 0) or 0)
    changed = int(diff_meta.get("changed_pixels", 0) or 0)
    total = width * height
    drift_pct = (changed / total * 100.0) if total > 0 else 0.0
    return round(drift_pct, 3), changed, total


def register(mcp: FastMCP) -> None:
    """Register schematic visual-baseline tools."""

    @mcp.tool()
    @headless_compatible
    def sch_visual_baseline_set(
        sheet: str | None = None,
        sheet_file: str | None = None,
        dpi: int = 200,
        include_title_block: bool = True,
    ) -> str:
        """Capture the current render of a schematic sheet as its visual baseline.

        Renders the sheet headlessly and stores the PNG plus metadata (dpi, source
        hash) under ``.kicad-mcp/visual_baselines/``. Call this once a sheet looks
        right; ``sch_visual_baseline_compare`` then flags any later visual drift.
        """
        if dpi < 72 or dpi > 600:
            return json.dumps({"status": "error", "message": "dpi must be between 72 and 600."})

        try:
            target = _resolve_schematic_target(sheet=sheet, sheet_file=sheet_file)
        except ValueError as exc:
            return json.dumps({"status": "error", "message": str(exc)})

        stem = target.path.stem
        png_path = _baseline_png(stem)
        try:
            _, image_metadata = _render_schematic_png_artifact(
                target.path,
                png_path,
                dpi=dpi,
                crop_to_content=True,
                include_title_block=include_title_block,
            )
        except RuntimeError as exc:
            return json.dumps({"status": "error", "message": f"Baseline render failed: {exc}"})

        metadata: dict[str, Any] = {
            "sheet": stem,
            "sheet_path": str(target.path),
            "dpi": dpi,
            "include_title_block": include_title_block,
            "source_sha256": _sheet_sha256(target.path),
            "render": image_metadata,
        }
        _baseline_meta(stem).write_text(json.dumps(metadata, indent=2), encoding="utf-8")

        return json.dumps(
            {
                "status": "captured",
                "baseline_png": str(png_path),
                "baseline_meta": str(_baseline_meta(stem)),
                **metadata,
            },
            indent=2,
        )

    @mcp.tool()
    @headless_compatible
    def sch_visual_baseline_compare(
        sheet: str | None = None,
        sheet_file: str | None = None,
        dpi: int = 200,
        include_title_block: bool = True,
        threshold_pct: float = DEFAULT_DRIFT_THRESHOLD_PCT,
    ) -> str:
        """Compare a sheet's current render against its stored visual baseline.

        Renders the sheet, diffs it pixel-wise against the baseline, and reports the
        drift percentage, the changed bounding box, and a highlighted diff image.
        Status is ``PASS`` when drift is within ``threshold_pct``, else ``DRIFT``.
        Reports ``no_baseline`` if the sheet was never captured.
        """
        if dpi < 72 or dpi > 600:
            return json.dumps({"status": "error", "message": "dpi must be between 72 and 600."})

        try:
            target = _resolve_schematic_target(sheet=sheet, sheet_file=sheet_file)
        except ValueError as exc:
            return json.dumps({"status": "error", "message": str(exc)})

        stem = target.path.stem
        baseline_png = _baseline_png(stem)
        if not baseline_png.is_file():
            return json.dumps(
                {
                    "status": "no_baseline",
                    "sheet": stem,
                    "message": (
                        f"No visual baseline for '{stem}'. Run sch_visual_baseline_set first."
                    ),
                }
            )

        baseline_meta: dict[str, Any] = {}
        meta_path = _baseline_meta(stem)
        if meta_path.is_file():
            try:
                baseline_meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                baseline_meta = {}
        # Render at the baseline's dpi when known, so pixel counts are comparable.
        render_dpi = int(baseline_meta.get("dpi", dpi) or dpi)

        current_png = _baseline_dir() / f"{stem}.current.png"
        diff_png = _baseline_dir() / f"{stem}.drift.png"
        try:
            _, _ = _render_schematic_png_artifact(
                target.path,
                current_png,
                dpi=render_dpi,
                crop_to_content=True,
                include_title_block=include_title_block,
            )
            diff_meta = _render_png_visual_diff(baseline_png, current_png, diff_png)
        except RuntimeError as exc:
            return json.dumps({"status": "error", "message": f"Baseline compare failed: {exc}"})

        drift_pct, changed_pixels, total_pixels = _drift_from_diff(diff_meta)
        status = "PASS" if drift_pct <= threshold_pct else "DRIFT"
        return json.dumps(
            {
                "status": status,
                "sheet": stem,
                "drift_pct": drift_pct,
                "threshold_pct": threshold_pct,
                "changed_pixels": changed_pixels,
                "total_pixels": total_pixels,
                "changed_bbox_px": diff_meta.get("changed_bbox_px"),
                "baseline_png": str(baseline_png),
                "current_png": str(current_png),
                "diff_png": str(diff_png),
            },
            indent=2,
        )


__all__ = ["register"]
