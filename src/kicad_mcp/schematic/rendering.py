"""FastMCP-independent schematic rendering orchestration."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, cast


class SchematicTargetLike(Protocol):
    @property
    def path(self) -> Path: ...

    @property
    def description(self) -> str: ...


@dataclass(frozen=True)
class SchematicRenderingResponse:
    """Internal rendering result converted to MCP content by the thin adapter."""

    text: str | None = None
    metadata: dict[str, Any] | None = None
    image_path: Path | None = None


@dataclass(frozen=True)
class SchematicRenderingService:
    """Coordinate schematic preview, PNG render, and visual-diff behavior."""

    resolve_target: Callable[[str | None, str | None], SchematicTargetLike]
    parse_schematic: Callable[[Path], dict[str, Any]]
    has_renderable_content: Callable[[dict[str, Any]], bool]
    safe_output_path: Callable[[str | None, str], Path]
    render_png_artifact: Callable[[Path, Path, int, bool, bool], tuple[Path, dict[str, object]]]
    load_visual_diff: Callable[[Path], dict[str, Any] | None]
    render_png_visual_diff: Callable[[Path, Path, Path], dict[str, object]]
    preview_files: Callable[[Path, bool], list[Path]]
    preview_signature: Callable[[list[Path]], dict[str, Any]]
    preview_state_filename: Callable[[Path, bool], str]
    preview_state_read: Callable[[str], dict[str, Any] | None]
    preview_state_write: Callable[[str, dict[str, Any]], None]
    preview_changed_files: Callable[[dict[str, Any] | None, dict[str, Any]], list[str]]
    preview_render_path: Callable[[Path, list[Path], list[str]], Path]
    preview_payload: Callable[..., dict[str, Any]]
    reload_schematic: Callable[[], str]
    now_ns: Callable[[], int]

    @staticmethod
    def _text(message: str) -> SchematicRenderingResponse:
        return SchematicRenderingResponse(text=message)

    @staticmethod
    def _json(metadata: dict[str, Any]) -> SchematicRenderingResponse:
        return SchematicRenderingResponse(
            text=json.dumps(metadata, indent=2),
            metadata=metadata,
        )

    @staticmethod
    def _image(path: Path, metadata: dict[str, Any]) -> SchematicRenderingResponse:
        return SchematicRenderingResponse(metadata=metadata, image_path=path)

    def render_png(
        self,
        sheet: str | None = None,
        sheet_file: str | None = None,
        crop_to_content: bool = True,
        dpi: int = 200,
        include_title_block: bool = True,
        output_file: str | None = None,
    ) -> SchematicRenderingResponse:
        """Render a schematic sheet to a PNG response."""
        if dpi < 72 or dpi > 600:
            return self._text("dpi must be between 72 and 600.")

        target = self.resolve_target(sheet, sheet_file)
        data = self.parse_schematic(target.path)
        if not self.has_renderable_content(data):
            metadata: dict[str, Any] = {
                "status": "empty_sheet",
                "sheet_path": str(target.path),
                "message": "No schematic content was available to render.",
            }
            return self._json(metadata)

        try:
            png_file = self.safe_output_path(
                output_file,
                f"{target.path.stem}.png",
            )
        except ValueError as exc:
            return self._text(f"Invalid output path: {exc}")
        try:
            svg_file, image_metadata = self.render_png_artifact(
                target.path,
                png_file,
                dpi,
                crop_to_content,
                include_title_block,
            )
        except RuntimeError as exc:
            return self._text(f"Schematic PNG render failed: {exc}")
        metadata = {
            "status": "ok",
            "png_path": str(png_file),
            "svg_path": str(svg_file),
            "sheet_path": str(target.path),
            "dpi": dpi,
            "include_title_block": include_title_block,
            **image_metadata,
        }
        return self._image(png_file, metadata)

    def render_visual_diff(
        self,
        sheet: str | None = None,
        sheet_file: str | None = None,
        dpi: int = 200,
        include_title_block: bool = True,
        output_file: str | None = None,
    ) -> SchematicRenderingResponse:
        """Render the exact visual delta from the latest mutation snapshot."""
        if dpi < 72 or dpi > 600:
            return self._text("dpi must be between 72 and 600.")

        target = self.resolve_target(sheet, sheet_file)
        state = self.load_visual_diff(target.path)
        if state is None:
            metadata: dict[str, Any] = {
                "status": "no_recorded_mutation",
                "sheet_path": str(target.path),
                "message": "No mutation snapshot is available for this schematic.",
            }
            return self._json(metadata)

        before_snapshot = Path(str(state.get("before_snapshot", "")))
        if not before_snapshot.is_file():
            metadata = {
                "status": "missing_before_snapshot",
                "sheet_path": str(target.path),
                "before_snapshot": str(before_snapshot),
            }
            return self._json(metadata)

        current_content = target.path.read_text(encoding="utf-8")
        current_sha256 = hashlib.sha256(current_content.encode("utf-8")).hexdigest()
        if current_sha256 != state.get("after_sha256"):
            metadata = {
                "status": "stale_mutation_snapshot",
                "sheet_path": str(target.path),
                "recorded_after_sha256": state.get("after_sha256"),
                "current_sha256": current_sha256,
                "message": "The schematic changed outside the recorded mutation.",
            }
            return self._json(metadata)

        try:
            diff_file = self.safe_output_path(
                output_file,
                f"{target.path.stem}-visual-diff.png",
            )
        except ValueError as exc:
            return self._text(f"Invalid output path: {exc}")

        artifact_dir = diff_file.parent / "_visual-diff"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        before_png = artifact_dir / f"{diff_file.stem}-before.png"
        after_png = artifact_dir / f"{diff_file.stem}-after.png"
        try:
            before_svg, before_metadata = self.render_png_artifact(
                before_snapshot,
                before_png,
                dpi,
                False,
                include_title_block,
            )
            after_svg, after_metadata = self.render_png_artifact(
                target.path,
                after_png,
                dpi,
                False,
                include_title_block,
            )
            diff_metadata = self.render_png_visual_diff(
                before_png,
                after_png,
                diff_file,
            )
        except RuntimeError as exc:
            return self._text(f"Schematic visual diff failed: {exc}")

        metadata2: dict[str, Any] = {
            "status": "ok",
            "diff_path": str(diff_file),
            "before_png_path": str(before_png),
            "after_png_path": str(after_png),
            "before_svg_path": str(before_svg),
            "after_svg_path": str(after_svg),
            "sheet_path": str(target.path),
            "dpi": dpi,
            "include_title_block": include_title_block,
            "before_render": before_metadata,
            "after_render": after_metadata,
            "changed_objects": state.get("changed_objects", []),
            "changed_refs": state.get("changed_refs", []),
            "changed_nets": state.get("changed_nets", []),
            **diff_metadata,
        }
        return self._image(diff_file, metadata2)

    def live_preview(
        self,
        sheet: str | None = None,
        sheet_file: str | None = None,
        include_child_sheets: bool = True,
        debounce_ms: int = 750,
        render: bool = True,
        reload: bool = False,
        force: bool = False,
        crop_to_content: bool = True,
        dpi: int = 200,
        include_title_block: bool = True,
        output_file: str | None = None,
    ) -> SchematicRenderingResponse:
        """Poll and optionally refresh a safe live schematic preview."""
        if debounce_ms < 0 or debounce_ms > 60_000:
            return self._text("debounce_ms must be between 0 and 60000.")
        if dpi < 72 or dpi > 600:
            return self._text("dpi must be between 72 and 600.")

        target = self.resolve_target(sheet, sheet_file)
        files = self.preview_files(target.path, include_child_sheets)
        signature = self.preview_signature(files)
        state_name = self.preview_state_filename(target.path, include_child_sheets)
        existing_state = self.preview_state_read(state_name)
        now_ns = self.now_ns()
        debounce_ns = debounce_ms * 1_000_000

        state: dict[str, Any]
        if existing_state is None:
            state = {
                "last_signature": signature,
                "pending_signature": None,
                "pending_observed_at_ns": None,
                "updated_at_ns": now_ns,
            }
            self.preview_state_write(state_name, state)
            if not force:
                payload = self.preview_payload(
                    status="initialized",
                    target=target,
                    files=files,
                    signature=signature,
                    message=(
                        "Live preview baseline recorded. Call again after a schematic "
                        "change, or use force=True to render immediately."
                    ),
                )
                return self._json(payload)
        else:
            state = existing_state

        last_signature = cast(dict[str, Any] | None, state.get("last_signature"))
        pending_signature = cast(dict[str, Any] | None, state.get("pending_signature"))
        changed_files = self.preview_changed_files(last_signature, signature)

        if not force and signature == last_signature:
            state["pending_signature"] = None
            state["pending_observed_at_ns"] = None
            state["updated_at_ns"] = now_ns
            self.preview_state_write(state_name, state)
            payload = self.preview_payload(
                status="no_change",
                target=target,
                files=files,
                signature=signature,
                message="No schematic file changes detected since the last live-preview refresh.",
            )
            return self._json(payload)

        if not force:
            if pending_signature != signature:
                state["pending_signature"] = signature
                state["pending_observed_at_ns"] = now_ns
                state["updated_at_ns"] = now_ns
                self.preview_state_write(state_name, state)
                payload = self.preview_payload(
                    status="pending_debounce",
                    target=target,
                    files=files,
                    signature=signature,
                    changed_files=changed_files,
                    message="Change detected; waiting for debounce window before preview refresh.",
                )
                return self._json(payload)
            observed_at = int(state.get("pending_observed_at_ns") or now_ns)
            if now_ns - observed_at < debounce_ns:
                payload = self.preview_payload(
                    status="pending_debounce",
                    target=target,
                    files=files,
                    signature=signature,
                    changed_files=changed_files,
                    message="Change is still inside the debounce window.",
                )
                return self._json(payload)

        reload_result = self.reload_schematic() if reload else None
        render_metadata: dict[str, Any] | None = None
        output_path: Path | None = None
        if render:
            render_path = self.preview_render_path(
                target.path,
                files,
                changed_files,
            )
            data = self.parse_schematic(render_path)
            if self.has_renderable_content(data):
                try:
                    default_name = f"live-preview-{render_path.stem}.png"
                    output_path = self.safe_output_path(output_file, default_name)
                    svg_file, image_metadata = self.render_png_artifact(
                        render_path,
                        output_path,
                        dpi,
                        crop_to_content,
                        include_title_block,
                    )
                    render_metadata = {
                        "status": "ok",
                        "sheet_path": str(render_path),
                        "png_path": str(output_path),
                        "svg_path": str(svg_file),
                        "dpi": dpi,
                        "include_title_block": include_title_block,
                        **image_metadata,
                    }
                except (OSError, RuntimeError, ValueError) as exc:
                    render_metadata = {
                        "status": "failed",
                        "sheet_path": str(render_path),
                        "message": str(exc),
                    }
            else:
                render_metadata = {
                    "status": "empty_sheet",
                    "sheet_path": str(render_path),
                    "message": "No schematic content was available to render.",
                }

        state["last_signature"] = signature
        state["pending_signature"] = None
        state["pending_observed_at_ns"] = None
        state["last_changed_files"] = changed_files
        state["last_render"] = render_metadata
        state["last_reload_result"] = reload_result
        state["updated_at_ns"] = now_ns
        self.preview_state_write(state_name, state)

        status = "forced_rendered" if force else "changed"
        if render_metadata and render_metadata.get("status") == "ok":
            status = "forced_rendered" if force else "changed_rendered"
        elif reload_result:
            status = "forced_reloaded" if force else "changed_reloaded"
        payload = self.preview_payload(
            status=status,
            target=target,
            files=files,
            signature=signature,
            changed_files=changed_files,
            reload_result=reload_result,
            render_metadata=render_metadata,
            message=(
                "A best-effort KiCad GUI reload was requested by opt-in reload=True; "
                "schematic disk reload in the open GUI document is not confirmed."
                if reload
                else "Preview refreshed without forcing a KiCad GUI reload."
            ),
        )
        if (
            output_path is not None
            and output_path.exists()
            and render_metadata
            and render_metadata.get("status") == "ok"
        ):
            return self._image(output_path, payload)
        return self._json(payload)
