from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from kicad_mcp.schematic.rendering import SchematicRenderingService


@dataclass(frozen=True)
class FakeTarget:
    path: Path
    description: str = "root"


class RenderingHarness:
    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.schematic = tmp_path / "demo.kicad_sch"
        self.schematic.write_text("content", encoding="utf-8")
        self.target = FakeTarget(self.schematic)
        self.renderable = True
        self.visual_state: dict[str, Any] | None = None
        self.preview_state: dict[str, Any] | None = None
        self.signature: dict[str, Any] = {"files": [{"path": str(self.schematic), "sha256": "a"}]}
        self.changed_files: list[str] = [str(self.schematic)]
        self.render_error: Exception | None = None
        self.diff_error: Exception | None = None
        self.safe_output_error: ValueError | None = None
        self.now = 10_000_000_000
        self.reload_result = "reloaded"
        self.writes: list[tuple[str, dict[str, Any]]] = []
        self.render_calls: list[tuple[Path, Path, int, bool, bool]] = []
        self.diff_calls: list[tuple[Path, Path, Path]] = []

    def service(self) -> SchematicRenderingService:
        return SchematicRenderingService(
            resolve_target=lambda sheet, sheet_file: self.target,
            parse_schematic=lambda path: {"symbols": [1]} if self.renderable else {},
            has_renderable_content=lambda data: bool(data.get("symbols")),
            safe_output_path=self.safe_output_path,
            render_png_artifact=self.render_png_artifact,
            load_visual_diff=lambda path: self.visual_state,
            render_png_visual_diff=self.render_png_visual_diff,
            preview_files=lambda root, include_children: [root],
            preview_signature=lambda paths: self.signature,
            preview_state_filename=lambda path, include_children: "preview.json",
            preview_state_read=lambda filename: self.preview_state,
            preview_state_write=self.preview_state_write,
            preview_changed_files=lambda before, after: self.changed_files,
            preview_render_path=lambda target_path, watched_files, changed_files: target_path,
            preview_payload=self.preview_payload,
            reload_schematic=lambda: self.reload_result,
            now_ns=lambda: self.now,
        )

    def safe_output_path(self, raw_name: str | None, default_name: str) -> Path:
        if self.safe_output_error is not None:
            raise self.safe_output_error
        return self.tmp_path / (raw_name or default_name)

    def render_png_artifact(
        self,
        schematic: Path,
        output: Path,
        dpi: int,
        crop_to_content: bool,
        include_title_block: bool,
    ) -> tuple[Path, dict[str, object]]:
        self.render_calls.append((schematic, output, dpi, crop_to_content, include_title_block))
        if self.render_error is not None:
            raise self.render_error
        output.write_bytes(b"png")
        svg = output.with_suffix(".svg")
        svg.write_text("<svg/>", encoding="utf-8")
        return svg, {"width_px": 32, "height_px": 16, "cropped": crop_to_content}

    def render_png_visual_diff(self, before: Path, after: Path, output: Path) -> dict[str, object]:
        self.diff_calls.append((before, after, output))
        if self.diff_error is not None:
            raise self.diff_error
        output.write_bytes(b"diff")
        return {"changed_pixels": 3, "changed_bbox_px": [1, 2, 3, 4]}

    def preview_state_write(self, filename: str, state: dict[str, Any]) -> None:
        self.preview_state = dict(state)
        self.writes.append((filename, dict(state)))

    def preview_payload(
        self,
        *,
        status: str,
        target: FakeTarget,
        files: list[Path],
        signature: dict[str, Any],
        changed_files: list[str] | None = None,
        message: str | None = None,
        reload_result: str | None = None,
        render_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = {
            "status": status,
            "target": target.description,
            "target_path": str(target.path),
            "watch_files": [str(path) for path in files],
            "signature": signature,
            "changed_files": changed_files or [],
        }
        if message:
            payload["message"] = message
        if reload_result:
            payload["reload_result"] = reload_result
        if render_metadata:
            payload["render"] = render_metadata
        return payload


def _json(response_text: str | None) -> dict[str, Any]:
    assert response_text is not None
    return json.loads(response_text)


def test_render_png_validates_dpi_and_handles_empty_sheet(tmp_path: Path) -> None:
    harness = RenderingHarness(tmp_path)
    service = harness.service()

    invalid = service.render_png(dpi=71)
    assert invalid.text == "dpi must be between 72 and 600."
    assert invalid.metadata is None

    harness.renderable = False
    empty = service.render_png()
    assert (
        _json(empty.text)
        == empty.metadata
        == {
            "status": "empty_sheet",
            "sheet_path": str(harness.schematic),
            "message": "No schematic content was available to render.",
        }
    )


def test_render_png_preserves_output_errors_and_success_metadata(tmp_path: Path) -> None:
    harness = RenderingHarness(tmp_path)
    service = harness.service()

    harness.safe_output_error = ValueError("unsafe")
    assert service.render_png(output_file="bad.png").text == "Invalid output path: unsafe"

    harness.safe_output_error = None
    harness.render_error = RuntimeError("cli failed")
    assert service.render_png().text == "Schematic PNG render failed: cli failed"

    harness.render_error = None
    response = service.render_png(
        dpi=150,
        crop_to_content=False,
        include_title_block=False,
        output_file="render.png",
    )
    assert response.image_path == tmp_path / "render.png"
    assert response.metadata == {
        "status": "ok",
        "png_path": str(tmp_path / "render.png"),
        "svg_path": str(tmp_path / "render.svg"),
        "sheet_path": str(harness.schematic),
        "dpi": 150,
        "include_title_block": False,
        "width_px": 32,
        "height_px": 16,
        "cropped": False,
    }


def test_visual_diff_handles_missing_and_stale_snapshots(tmp_path: Path) -> None:
    harness = RenderingHarness(tmp_path)
    service = harness.service()

    missing = service.render_visual_diff()
    assert _json(missing.text)["status"] == "no_recorded_mutation"

    before = tmp_path / "before.kicad_sch"
    harness.visual_state = {"before_snapshot": str(before), "after_sha256": "x"}
    assert _json(service.render_visual_diff().text)["status"] == "missing_before_snapshot"

    before.write_text("before", encoding="utf-8")
    stale = _json(service.render_visual_diff().text)
    assert stale["status"] == "stale_mutation_snapshot"
    assert stale["current_sha256"] == hashlib.sha256(b"content").hexdigest()


def test_visual_diff_renders_exact_artifacts_and_metadata(tmp_path: Path) -> None:
    harness = RenderingHarness(tmp_path)
    before = tmp_path / "before.kicad_sch"
    before.write_text("before", encoding="utf-8")
    harness.visual_state = {
        "before_snapshot": str(before),
        "after_sha256": hashlib.sha256(b"content").hexdigest(),
        "changed_objects": [{"kind": "label"}],
        "changed_refs": ["R1"],
        "changed_nets": ["READY"],
    }
    service = harness.service()

    harness.safe_output_error = ValueError("unsafe")
    assert service.render_visual_diff().text == "Invalid output path: unsafe"

    harness.safe_output_error = None
    harness.render_error = RuntimeError("export failed")
    assert service.render_visual_diff().text == "Schematic visual diff failed: export failed"

    harness.render_error = None
    response = service.render_visual_diff(
        dpi=144, include_title_block=False, output_file="delta.png"
    )
    assert response.image_path == tmp_path / "delta.png"
    assert response.metadata is not None
    assert response.metadata["status"] == "ok"
    assert response.metadata["changed_pixels"] == 3
    assert response.metadata["changed_refs"] == ["R1"]
    assert response.metadata["changed_nets"] == ["READY"]
    assert response.metadata["before_render"]["cropped"] is False  # type: ignore[index]
    assert response.metadata["after_render"]["cropped"] is False  # type: ignore[index]


def test_live_preview_validates_arguments_and_initializes_state(tmp_path: Path) -> None:
    harness = RenderingHarness(tmp_path)
    service = harness.service()

    assert service.live_preview(debounce_ms=-1).text == ("debounce_ms must be between 0 and 60000.")
    assert service.live_preview(dpi=601).text == "dpi must be between 72 and 600."

    response = service.live_preview(render=False)
    payload = _json(response.text)
    assert payload["status"] == "initialized"
    assert harness.preview_state == {
        "last_signature": harness.signature,
        "pending_signature": None,
        "pending_observed_at_ns": None,
        "updated_at_ns": harness.now,
    }


def test_live_preview_handles_no_change_and_debounce(tmp_path: Path) -> None:
    harness = RenderingHarness(tmp_path)
    service = harness.service()

    harness.preview_state = {
        "last_signature": harness.signature,
        "pending_signature": {"files": []},
        "pending_observed_at_ns": 1,
    }
    no_change = _json(service.live_preview(render=False).text)
    assert no_change["status"] == "no_change"
    assert harness.preview_state["pending_signature"] is None

    old_signature = {"files": [{"path": str(harness.schematic), "sha256": "old"}]}
    harness.preview_state = {
        "last_signature": old_signature,
        "pending_signature": None,
        "pending_observed_at_ns": None,
    }
    pending = _json(service.live_preview(render=False, debounce_ms=1000).text)
    assert pending["status"] == "pending_debounce"
    assert harness.preview_state["pending_signature"] == harness.signature

    harness.preview_state = {
        "last_signature": old_signature,
        "pending_signature": harness.signature,
        "pending_observed_at_ns": harness.now - 500_000_000,
    }
    inside = _json(service.live_preview(render=False, debounce_ms=1000).text)
    assert inside["status"] == "pending_debounce"
    assert inside["message"] == "Change is still inside the debounce window."


def test_live_preview_refreshes_render_and_reload_state(tmp_path: Path) -> None:
    harness = RenderingHarness(tmp_path)
    old_signature = {"files": [{"path": str(harness.schematic), "sha256": "old"}]}
    harness.preview_state = {
        "last_signature": old_signature,
        "pending_signature": harness.signature,
        "pending_observed_at_ns": 0,
    }
    service = harness.service()

    response = service.live_preview(
        debounce_ms=0,
        render=True,
        reload=True,
        dpi=150,
        include_title_block=False,
        output_file="live.png",
    )
    assert response.image_path == tmp_path / "live.png"
    assert response.metadata is not None
    assert response.metadata["status"] == "changed_rendered"
    assert response.metadata["reload_result"] == "reloaded"
    assert response.metadata["render"]["status"] == "ok"  # type: ignore[index]
    assert harness.preview_state["last_signature"] == harness.signature
    assert harness.preview_state["last_render"]["status"] == "ok"


def test_live_preview_reports_failed_and_empty_render_without_image(tmp_path: Path) -> None:
    harness = RenderingHarness(tmp_path)
    harness.preview_state = {
        "last_signature": {"files": []},
        "pending_signature": harness.signature,
        "pending_observed_at_ns": 0,
    }
    harness.render_error = RuntimeError("renderer unavailable")
    failed = harness.service().live_preview(debounce_ms=0, render=True)
    assert failed.image_path is None
    assert _json(failed.text)["render"]["status"] == "failed"

    harness.preview_state = {
        "last_signature": {"files": []},
        "pending_signature": harness.signature,
        "pending_observed_at_ns": 0,
    }
    harness.render_error = None
    harness.renderable = False
    empty = harness.service().live_preview(debounce_ms=0, render=True)
    assert empty.image_path is None
    assert _json(empty.text)["render"]["status"] == "empty_sheet"


def test_live_preview_force_renders_on_first_call(tmp_path: Path) -> None:
    harness = RenderingHarness(tmp_path)
    response = harness.service().live_preview(force=True, render=True)

    assert response.image_path is not None
    assert response.metadata is not None
    assert response.metadata["status"] == "forced_rendered"


def test_visual_diff_validates_dpi(tmp_path: Path) -> None:
    response = RenderingHarness(tmp_path).service().render_visual_diff(dpi=601)

    assert response.text == "dpi must be between 72 and 600."
    assert response.metadata is None


def test_live_preview_reports_reload_only_status(tmp_path: Path) -> None:
    harness = RenderingHarness(tmp_path)
    harness.preview_state = {
        "last_signature": {"files": []},
        "pending_signature": harness.signature,
        "pending_observed_at_ns": 0,
    }

    response = harness.service().live_preview(
        debounce_ms=0,
        render=False,
        reload=True,
    )

    assert response.image_path is None
    assert response.metadata is not None
    assert response.metadata["status"] == "changed_reloaded"
    assert response.metadata["reload_result"] == "reloaded"
