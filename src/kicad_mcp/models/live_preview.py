"""Typed live-preview contracts for agent-facing schematic feedback."""

from __future__ import annotations

from pathlib import Path
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
    "changed_reloaded",
    "forced_reloaded",
    "changed_skipped",
    "error",
    "fallback",
]
LivePreviewOutcome = Literal[
    "skipped",
    "pending",
    "changed",
    "rendered",
    "reload_requested",
    "reloaded",
    "error",
    "fallback",
]
ArtifactKind = Literal["png", "svg", "json", "junit", "environment"]
RenderStatus = Literal["ok", "failed", "empty_sheet", "skipped"]

SCHEMATIC_GUI_RELOAD_BEST_EFFORT_WARNING = (
    "KiCad schematic GUI reload is best-effort only; treat rendered artifacts "
    "and the manifest as authoritative review evidence."
)
SCHEMATIC_GUI_RELOAD_UNCONFIRMED_WARNING = (
    "Schematic GUI disk reload was requested but not confirmed. KiCad 10 does "
    "not expose a confirmed silent schematic RevertDocument IPC path equivalent "
    "to PCB."
)
SCHEMATIC_GUI_RELOAD_UPSTREAM_BLOCKER_URL = "https://gitlab.com/kicad/code/kicad/-/work_items/24803"


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
    project_path: str | None = None
    project_ref: str | None = None
    watched_files: list[str] = Field(default_factory=list)
    changed_files: list[str] = Field(default_factory=list)
    debounce_ms: int = Field(default=750, ge=0, le=60_000)
    reload_attempted: bool = False
    reload_outcome: str = "skipped"
    reload_confirmed: bool = False
    reload_mode: Literal[
        "skipped",
        "best_effort_gui_request",
        "confirmed_gui_reload",
    ] = "skipped"
    upstream_blockers: list[str] = Field(default_factory=list)
    render_artifacts: list[LivePreviewArtifact] = Field(default_factory=list)
    unsafe_state: dict[str, Any] = Field(default_factory=dict)
    next_actions: list[str] = Field(default_factory=list)
    manifest_path: str | None = None
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
        reload_confirmed = bool(payload.get("reload_confirmed", False))
        if status == "pending_debounce":
            outcome: LivePreviewOutcome = "pending"
        elif render_status == "ok" or status.endswith("_rendered"):
            outcome = "rendered"
        elif status.endswith("_reloaded"):
            outcome = "reloaded" if reload_confirmed else "reload_requested"
        elif render_status == "failed" or status == "error":
            outcome = "error"
        elif status == "fallback":
            outcome = "fallback"
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
        reload_result = payload.get("reload_result")
        reload_attempted = bool(payload.get("reload_attempted") or reload_result)
        if reload_attempted and not reload_confirmed:
            # A successful IPC send means the GUI-facing request was attempted; it
            # does not prove that the open Eeschema document reloaded from disk.
            reload_outcome = "requested"
        elif reload_attempted and reload_confirmed:
            reload_outcome = "confirmed"
        else:
            reload_outcome = str(payload.get("reload_outcome") or "skipped")
        reload_mode = (
            "confirmed_gui_reload"
            if reload_confirmed
            else "best_effort_gui_request"
            if reload_attempted
            else "skipped"
        )
        upstream_blockers = [str(item) for item in payload.get("upstream_blockers", [])]
        if reload_attempted and not reload_confirmed:
            upstream_blockers.append(SCHEMATIC_GUI_RELOAD_UPSTREAM_BLOCKER_URL)
        render_artifacts: list[LivePreviewArtifact] = []
        if render.png_path:
            render_artifacts.append(
                LivePreviewArtifact(
                    kind="png",
                    path=render.png_path,
                    role="rendered-preview",
                    mime_type="image/png",
                )
            )
        if render.svg_path:
            render_artifacts.append(
                LivePreviewArtifact(
                    kind="svg",
                    path=render.svg_path,
                    role="source-render",
                    mime_type="image/svg+xml",
                )
            )
        warnings = [str(item) for item in payload.get("warnings", [])]
        if reload_attempted and not reload_confirmed:
            warnings.append(SCHEMATIC_GUI_RELOAD_BEST_EFFORT_WARNING)
            warnings.append(SCHEMATIC_GUI_RELOAD_UNCONFIRMED_WARNING)
        if reload_attempted and not payload.get("dirty_state_verified", False):
            warnings.append("GUI dirty state could not be verified before reload request.")
        warnings = list(dict.fromkeys(warnings))
        unsafe_state = dict(payload.get("unsafe_state") or {})
        dirty_state_verified = bool(payload.get("dirty_state_verified", False))
        unsafe_state.setdefault("dirty_state_verified", dirty_state_verified)
        unsafe_state.setdefault("unsafe", False)
        if outcome == "pending":
            next_actions = ["Call sch_live_preview again after the debounce window settles."]
        elif outcome == "rendered":
            next_actions = [
                "Inspect render_artifacts before continuing.",
                "Run ERC/DRC checks after schematic changes.",
            ]
        elif outcome == "reload_requested":
            next_actions = [
                "Inspect render_artifacts when available before continuing.",
                "Do not assume the KiCad GUI document reloaded from disk.",
                "Run ERC/DRC checks after schematic changes.",
            ]
        elif outcome == "reloaded":
            next_actions = ["Verify the GUI-visible sheet and run ERC/DRC checks."]
        elif outcome == "error":
            next_actions = ["Inspect warnings and renderer diagnostics before retrying."]
        else:
            next_actions = [
                "Continue only if the structured status matches the intended workflow state."
            ]
        debounce_ms = int(payload.get("debounce_ms", 750))
        debounce_state = str(payload.get("debounce_state", "settled"))
        if debounce_state not in {"idle", "observing", "waiting", "settled"}:
            debounce_state = "settled"
        debounce = LivePreviewDebounce(
            requested_ms=debounce_ms,
            state=debounce_state,
            pending_observed_at_ns=payload.get("pending_observed_at_ns"),
        )
        normalized = cls(
            status=status if status in get_args(LivePreviewStatus) else "changed",
            outcome=outcome,
            target=str(payload.get("target", "schematic")),
            target_path=str(payload.get("target_path", "")),
            project_path=payload.get("project_path"),
            project_ref=payload.get("project_ref"),
            watched_files=watch_files,
            changed_files=changed_files,
            debounce_ms=debounce_ms,
            reload_attempted=reload_attempted,
            reload_outcome=reload_outcome,
            reload_confirmed=reload_confirmed,
            reload_mode=reload_mode,
            upstream_blockers=upstream_blockers,
            render_artifacts=render_artifacts,
            unsafe_state=unsafe_state,
            next_actions=next_actions,
            warnings=warnings,
            watch=watch,
            signature=dict(payload.get("signature") or {}),
            debounce=debounce,
            render=render,
            safety=LivePreviewSafety(
                dirty_state_verified=dirty_state_verified,
                status=reload_mode if reload_attempted else "safe_artifact_preview",
                warnings=warnings,
            ),
            message=payload.get("message"),
        )
        return _persist_manifest_artifact(normalized) if render_artifacts else normalized

    def to_manifest(self) -> LivePreviewManifest:
        """Create a manifest from the normalized payload."""
        artifacts: list[LivePreviewArtifact] = []
        if self.render.png_path:
            artifacts.append(
                LivePreviewArtifact(
                    kind="png",
                    path=self.render.png_path,
                    role="rendered-preview",
                    mime_type="image/png",
                )
            )
        if self.render.svg_path:
            artifacts.append(
                LivePreviewArtifact(
                    kind="svg",
                    path=self.render.svg_path,
                    role="source-render",
                    mime_type="image/svg+xml",
                )
            )
        return LivePreviewManifest(
            session_id=self.session_id,
            target_path=self.target_path,
            watch=self.watch,
            debounce=self.debounce,
            render=self.render,
            artifacts=artifacts,
        )


def _manifest_artifact_path(payload: LivePreviewPayload) -> Path | None:
    if payload.render.png_path:
        png_path = Path(payload.render.png_path)
        return png_path.with_name(f"{png_path.stem}.manifest.json")
    if payload.render.svg_path:
        svg_path = Path(payload.render.svg_path)
        return svg_path.with_name(f"{svg_path.stem}.manifest.json")
    if payload.target_path:
        target_path = Path(payload.target_path)
        return target_path.with_name(f"{target_path.stem}.live-preview.manifest.json")
    return None


def _persist_manifest_artifact(payload: LivePreviewPayload) -> LivePreviewPayload:
    manifest_path = _manifest_artifact_path(payload)
    if manifest_path is None:
        return payload
    manifest_artifact = LivePreviewArtifact(
        kind="json",
        path=str(manifest_path),
        role="session-manifest",
        mime_type="application/json",
    )
    manifest = payload.to_manifest()
    manifest = manifest.model_copy(update={"artifacts": [*manifest.artifacts, manifest_artifact]})
    update: dict[str, Any] = {
        "manifest": manifest,
        "manifest_path": str(manifest_path),
    }
    if not manifest_path.parent.exists():
        return payload.model_copy(update=update)
    try:
        manifest_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    except OSError as exc:
        update["warnings"] = [*payload.warnings, f"Unable to write live-preview manifest: {exc}"]
        return payload.model_copy(update=update)
    update["render_artifacts"] = [*payload.render_artifacts, manifest_artifact]
    return payload.model_copy(update=update)
