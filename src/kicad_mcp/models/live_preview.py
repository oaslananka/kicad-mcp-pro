"""Typed live-preview contracts for agent-facing schematic feedback."""

from __future__ import annotations

from typing import Any, Literal, get_args
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

LivePreviewStatus = Literal[
    "initialized",
    "no_change",
    "pending_debounce",
    "changed",
    "changed_rendered",
    "forced_rendered",
    "changed_skipped",
]
LivePreviewOutcome = Literal["skipped", "pending", "changed", "rendered"]
ArtifactKind = Literal["png", "svg", "json", "junit", "environment"]
RenderStatus = Literal["ok", "failed", "empty_sheet", "skipped"]


class LivePreviewArtifact(BaseModel):
    """A generated evidence artifact associated with a preview session."""

    model_config = ConfigDict(frozen=True)

    kind: ArtifactKind
    path: str
    role: str = "evidence"
    mime_type: str | None = None
    size_bytes: int | None = None
    sha256: str | None = None


class LivePreviewWatch(BaseModel):
    """Files included in the live-preview watch signature."""

    model_config = ConfigDict(frozen=True)

    include_child_sheets: bool = True
    files: list[str] = Field(default_factory=list)
    changed_files: list[str] = Field(default_factory=list)


class LivePreviewDebounce(BaseModel):
    """Debounce timing state for a preview event."""

    model_config = ConfigDict(frozen=True)

    requested_ms: int = Field(default=750, ge=0, le=60_000)
    state: Literal["idle", "observing", "waiting", "settled"] = "idle"
    pending_observed_at_ns: int | None = None


class LivePreviewRender(BaseModel):
    """Rendered schematic evidence metadata."""

    model_config = ConfigDict(frozen=True)

    status: RenderStatus = "skipped"
    sheet_path: str | None = None
    png_path: str | None = None
    svg_path: str | None = None
    dpi: int | None = Field(default=None, ge=72, le=600)
    include_title_block: bool | None = None
    width_px: int | None = None
    height_px: int | None = None
    message: str | None = None


class LivePreviewSafety(BaseModel):
    """Safety state for live-preview automation."""

    model_config = ConfigDict(frozen=True)

    artifact_first: bool = True
    gui_refresh_requires_explicit_opt_in: bool = True
    dirty_state_verified: bool = False
    status: str = "safe_artifact_preview"
    warnings: list[str] = Field(default_factory=list)


class LivePreviewManifest(BaseModel):
    """Manifest written alongside live-preview visual evidence."""

    model_config = ConfigDict(frozen=True)

    schema_version: str = "live-preview.manifest.v1"
    session_id: str
    target_path: str
    watch: LivePreviewWatch
    debounce: LivePreviewDebounce = Field(default_factory=LivePreviewDebounce)
    render: LivePreviewRender = Field(default_factory=LivePreviewRender)
    artifacts: list[LivePreviewArtifact] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class LivePreviewPayload(BaseModel):
    """Stable agent-facing live-preview response contract."""

    model_config = ConfigDict(extra="allow")

    schema_version: str = "live-preview.payload.v1"
    tool: str = "sch_live_preview"
    session_id: str = Field(default_factory=lambda: str(uuid4()))
    status: LivePreviewStatus
    outcome: LivePreviewOutcome
    target: str
    target_path: str
    watch: LivePreviewWatch = Field(default_factory=LivePreviewWatch)
    signature: dict[str, Any] = Field(default_factory=dict)
    debounce: LivePreviewDebounce = Field(default_factory=LivePreviewDebounce)
    render: LivePreviewRender = Field(default_factory=LivePreviewRender)
    safety: LivePreviewSafety = Field(default_factory=LivePreviewSafety)
    manifest: LivePreviewManifest | None = None
    warnings: list[str] = Field(default_factory=list)
    message: str | None = None

    @classmethod
    def from_legacy_payload(cls, payload: dict[str, Any]) -> LivePreviewPayload:
        """Normalize the current tool payload shape into the versioned contract."""
        status = str(payload.get("status", "changed"))
        changed_files = [str(item) for item in payload.get("changed_files", [])]
        watch_files = [str(item) for item in payload.get("watch_files", [])]
        render_payload = payload.get("render") or {}
        render_status = str(render_payload.get("status", "skipped"))
        if status == "pending_debounce":
            outcome: LivePreviewOutcome = "pending"
        elif render_status == "ok" or status.endswith("_rendered"):
            outcome = "rendered"
        elif status in {"initialized", "no_change", "changed_skipped"}:
            outcome = "skipped"
        else:
            outcome = "changed"
        render = LivePreviewRender(
            status=render_status if render_status in get_args(RenderStatus) else "failed",
            sheet_path=render_payload.get("sheet_path"),
            png_path=render_payload.get("png_path"),
            svg_path=render_payload.get("svg_path"),
            dpi=render_payload.get("dpi"),
            include_title_block=render_payload.get("include_title_block"),
            width_px=render_payload.get("width_px"),
            height_px=render_payload.get("height_px"),
            message=render_payload.get("message"),
        )
        watch = LivePreviewWatch(
            include_child_sheets=bool(payload.get("include_child_sheets", True)),
            files=watch_files,
            changed_files=changed_files,
        )
        return cls(
            status=status if status in get_args(LivePreviewStatus) else "changed",
            outcome=outcome,
            target=str(payload.get("target", "schematic")),
            target_path=str(payload.get("target_path", "")),
            watch=watch,
            signature=dict(payload.get("signature") or {}),
            render=render,
            message=payload.get("message"),
        )

    def to_manifest(self) -> LivePreviewManifest:
        """Create a manifest from the normalized payload."""
        artifacts: list[LivePreviewArtifact] = []
        if self.render.png_path:
            artifacts.append(
                LivePreviewArtifact(kind="png", path=self.render.png_path, role="rendered-preview")
            )
        if self.render.svg_path:
            artifacts.append(
                LivePreviewArtifact(kind="svg", path=self.render.svg_path, role="source-render")
            )
        return LivePreviewManifest(
            session_id=self.session_id,
            target_path=self.target_path,
            watch=self.watch,
            debounce=self.debounce,
            render=self.render,
            artifacts=artifacts,
        )
