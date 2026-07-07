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
            "debounce_ms": 125,
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
    assert payload.watched_files == [ROOT_SCH, CHILD_SCH]
    assert payload.changed_files == [CHILD_SCH]
    assert payload.debounce_ms == 125
    assert payload.reload_attempted is False
    assert payload.reload_outcome == "skipped"
    assert payload.unsafe_state["dirty_state_verified"] is False
    assert payload.next_actions == [
        "Inspect render_artifacts before continuing.",
        "Run ERC/DRC checks after schematic changes.",
    ]
    assert [(item.kind, item.role, item.path) for item in payload.render_artifacts] == [
        ("png", "rendered-preview", PNG_PATH),
        ("svg", "source-render", SVG_PATH),
    ]


def test_live_preview_payload_distinguishes_gui_reload() -> None:
    payload = LivePreviewPayload.from_legacy_payload(
        {
            "status": "changed_reloaded",
            "target": "root schematic",
            "target_path": ROOT_SCH,
            "watch_files": [ROOT_SCH],
            "changed_files": [ROOT_SCH],
            "reload_attempted": True,
            "reload_result": "The schematic was updated and KiCad was asked to reload it.",
            "dirty_state_verified": False,
        }
    )

    assert payload.outcome == "reloaded"
    assert payload.reload_attempted is True
    assert payload.reload_outcome == "ok"
    assert payload.unsafe_state == {"dirty_state_verified": False, "unsafe": False}
    assert "GUI dirty state could not be verified" in payload.warnings[0]
    assert payload.next_actions == ["Verify the GUI-visible sheet and run ERC/DRC checks."]


def test_live_preview_payload_surfaces_render_failure_as_error() -> None:
    payload = LivePreviewPayload.from_legacy_payload(
        {
            "status": "changed",
            "target": "root schematic",
            "target_path": ROOT_SCH,
            "watch_files": [ROOT_SCH],
            "changed_files": [ROOT_SCH],
            "render": {
                "status": "failed",
                "sheet_path": ROOT_SCH,
                "message": "renderer unavailable",
            },
        }
    )

    assert payload.outcome == "error"
    assert payload.render.status == "failed"
    assert payload.render.message == "renderer unavailable"
    assert payload.next_actions == ["Inspect warnings and renderer diagnostics before retrying."]


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
