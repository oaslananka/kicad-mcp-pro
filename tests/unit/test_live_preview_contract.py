from __future__ import annotations

import json
from pathlib import Path

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


def test_live_preview_payload_distinguishes_best_effort_gui_reload_request() -> None:
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

    assert payload.outcome == "reload_requested"
    assert payload.reload_attempted is True
    assert payload.reload_outcome == "requested"
    assert payload.reload_confirmed is False
    assert payload.reload_mode == "best_effort_gui_request"
    assert payload.upstream_blockers == ["https://gitlab.com/kicad/code/kicad/-/work_items/24803"]
    assert payload.unsafe_state == {"dirty_state_verified": False, "unsafe": False}
    assert any("best-effort only" in warning for warning in payload.warnings)
    assert any("not confirmed" in warning for warning in payload.warnings)
    assert any("GUI dirty state could not be verified" in warning for warning in payload.warnings)
    assert payload.safety.status == "best_effort_gui_request"
    assert payload.next_actions == [
        "Inspect render_artifacts when available before continuing.",
        "Do not assume the KiCad GUI document reloaded from disk.",
        "Run ERC/DRC checks after schematic changes.",
    ]


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


def test_live_preview_payload_persists_manifest_json_with_visual_artifacts(
    tmp_path: Path,
) -> None:
    root_sch = tmp_path / "demo.kicad_sch"
    child_sch = tmp_path / "sub.kicad_sch"
    png_path = tmp_path / "live.png"
    svg_path = tmp_path / "live.svg"

    payload = LivePreviewPayload.from_legacy_payload(
        {
            "status": "changed_rendered",
            "target": "root schematic",
            "target_path": str(root_sch),
            "watch_files": [str(root_sch), str(child_sch)],
            "changed_files": [str(child_sch)],
            "render": {
                "status": "ok",
                "sheet_path": str(child_sch),
                "png_path": str(png_path),
                "svg_path": str(svg_path),
            },
        }
    )

    assert payload.manifest_path == str(tmp_path / "live.manifest.json")
    assert payload.manifest is not None
    manifest_path = Path(payload.manifest_path)
    assert manifest_path.exists()
    persisted = json.loads(manifest_path.read_text())
    assert persisted["schema_version"] == "live-preview.manifest.v1"
    assert persisted["session_id"] == payload.session_id
    assert [item["kind"] for item in persisted["artifacts"]] == ["png", "svg", "json"]
    assert payload.render_artifacts[-1].kind == "json"
    assert payload.render_artifacts[-1].role == "session-manifest"


def test_live_preview_debounce_bounds_are_schema_validated() -> None:
    assert LivePreviewDebounce(requested_ms=0).requested_ms == 0
    assert LivePreviewDebounce(requested_ms=60_000).requested_ms == 60_000
    with pytest.raises(ValidationError):
        LivePreviewDebounce(requested_ms=-1)
    with pytest.raises(ValidationError):
        LivePreviewDebounce(requested_ms=60_001)
