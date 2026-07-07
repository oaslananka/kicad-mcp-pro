from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from kicad_mcp.models.live_preview import LivePreviewDebounce, LivePreviewPayload

ROOT = "/workspace/project"
ROOT_SCH = f"{ROOT}/demo.kicad_sch"
CHILD_SCH = f"{ROOT}/sub.kicad_sch"
PNG_PATH = f"{ROOT}/live.png"
SVG_PATH = f"{ROOT}/live.svg"


def test_live_preview_payload_normalizes_current_tool_shape() -> None:
    payload = LivePreviewPayload.from_legacy_payload(
        {
            "status": "changed_rendered",
            "target": "root schematic",
            "target_path": ROOT_SCH,
            "watch_files": [ROOT_SCH, CHILD_SCH],
            "changed_files": [CHILD_SCH],
            "signature": {"files": []},
            "render": {
                "status": "ok",
                "sheet_path": CHILD_SCH,
                "png_path": PNG_PATH,
                "svg_path": SVG_PATH,
                "dpi": 200,
                "include_title_block": False,
                "width_px": 64,
                "height_px": 32,
            },
            "message": "Preview refreshed.",
        }
    )

    assert payload.schema_version == "live-preview.payload.v1"
    assert payload.tool == "sch_live_preview"
    assert payload.status == "changed_rendered"
    assert payload.outcome == "rendered"
    assert payload.watch.include_child_sheets is True
    assert payload.watch.changed_files == [CHILD_SCH]
    assert payload.render.png_path == PNG_PATH


def test_live_preview_manifest_indexes_visual_artifacts() -> None:
    payload = LivePreviewPayload.from_legacy_payload(
        {
            "status": "changed_rendered",
            "target": "root schematic",
            "target_path": ROOT_SCH,
            "watch_files": [ROOT_SCH],
            "changed_files": [ROOT_SCH],
            "render": {
                "status": "ok",
                "sheet_path": ROOT_SCH,
                "png_path": PNG_PATH,
                "svg_path": SVG_PATH,
            },
        }
    )

    manifest = payload.to_manifest()

    assert manifest.schema_version == "live-preview.manifest.v1"
    assert manifest.session_id == payload.session_id
    assert manifest.target_path == payload.target_path
    assert [(item.kind, item.role, item.path) for item in manifest.artifacts] == [
        ("png", "rendered-preview", PNG_PATH),
        ("svg", "source-render", SVG_PATH),
    ]
    json.loads(manifest.model_dump_json())


def test_live_preview_debounce_bounds_are_schema_validated() -> None:
    assert LivePreviewDebounce(requested_ms=0).requested_ms == 0
    assert LivePreviewDebounce(requested_ms=60_000).requested_ms == 60_000
    with pytest.raises(ValidationError):
        LivePreviewDebounce(requested_ms=-1)
    with pytest.raises(ValidationError):
        LivePreviewDebounce(requested_ms=60_001)
