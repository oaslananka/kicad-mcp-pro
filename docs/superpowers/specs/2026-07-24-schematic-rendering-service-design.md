# Schematic Rendering Service Design

## Context

Issue #434 is incrementally reducing `src/kicad_mcp/tools/schematic.py` into a small FastMCP composition root. The remaining `sch_live_preview`, `sch_render_png`, and `sch_render_visual_diff` registrations still contain validation, preview-state orchestration, render selection, mutation-snapshot verification, artifact path handling, and response construction inside the registry function.

This tranche extracts those three rendering capabilities while preserving the existing rendering helpers and compatibility seams.

## Goals

- Make live-preview, PNG rendering, and visual-diff orchestration directly unit-testable without constructing FastMCP.
- Preserve exact public names, signatures, descriptions, schemas, annotations, image/text response behavior, metadata, validation messages, state transitions, debounce behavior, file selection, and error handling.
- Keep the new adapter `register()` function at or below 300 lines.
- Keep the service independent of FastMCP and `kicad_mcp.tools.schematic`.
- Preserve existing integration-test monkeypatch seams for schematic SVG export and SVG-to-PNG conversion.

## Non-goals

- No renderer, CairoSVG, Pillow, KiCad CLI, or image-diff algorithm changes.
- No live-preview contract or state-file format changes.
- No new output formats, arguments, or runtime dependencies.
- No mutation snapshot or schematic target resolution changes.

## Architecture

### Before

```text
FastMCP register()
  ├─ sch_live_preview
  │   ├─ validate and resolve target
  │   ├─ read/write debounce state
  │   ├─ detect changed files
  │   ├─ optionally reload and render
  │   └─ construct MCP text/image response
  ├─ sch_render_png
  │   ├─ validate and resolve target
  │   ├─ inspect renderable content
  │   ├─ render artifact
  │   └─ construct MCP image response
  └─ sch_render_visual_diff
      ├─ validate mutation snapshot
      ├─ render before/after/diff artifacts
      └─ construct MCP image response
```

### After

```text
FastMCP composition root
  ├─ lazy compatibility dependency wrappers
  └─ thin schematic_rendering adapter
       └─ SchematicRenderingService (FastMCP-free)
            ├─ live_preview()
            ├─ render_png()
            └─ render_visual_diff()
```

Create `SchematicRenderingService` in `src/kicad_mcp/schematic/rendering.py`. It receives explicit callables for target resolution, parsing, renderability checks, safe output paths, artifact rendering, visual-diff loading/rendering, preview file/signature/state operations, payload normalization, reload, and the clock. It returns a small `SchematicRenderingResponse` data object containing text, optional metadata, and an optional image path.

Create `src/kicad_mcp/tools/schematic_rendering.py` as the thin FastMCP adapter. It preserves each public signature and docstring, applies `headless_compatible`, delegates to the service, and converts the internal response through the existing `text_tool_result` and `image_tool_result` helpers.

Keep rendering helper functions in `src/kicad_mcp/tools/schematic.py` for this tranche. The composition root injects lazy lambdas rather than captured helper objects so existing post-registration monkeypatch seams continue to work in integration tests.

## Service Interface

```python
@dataclass(frozen=True)
class SchematicRenderingResponse:
    text: str | None = None
    metadata: dict[str, Any] | None = None
    image_path: Path | None = None

@dataclass(frozen=True)
class SchematicRenderingService:
    # Explicit injected dependencies omitted here for brevity.

    def live_preview(...) -> SchematicRenderingResponse: ...
    def render_png(...) -> SchematicRenderingResponse: ...
    def render_visual_diff(...) -> SchematicRenderingResponse: ...
```

A structural `SchematicTargetLike` protocol exposes only `path` and `description`, avoiding imports from the registry module.

## Behavior Preservation

- Preserve debounce range `0..60000` and DPI range `72..600` with exact messages.
- Preserve initialization, no-change, pending-debounce, changed, rendered, reloaded, forced, empty-sheet, and failed-render statuses.
- Preserve live-preview state keys, timestamps, changed-file ordering, child-sheet render selection, reload messaging, and image-return conditions.
- Preserve safe output-name validation and exact render/visual-diff error messages.
- Preserve mutation snapshot absence, missing-before, stale-after hash, changed object/ref/net metadata, artifact directory layout, and image metadata.
- Preserve `image_tool_result` for successful artifacts and `text_tool_result` for all non-image outcomes.
- Preserve exact tool metadata and committed tool-surface snapshot.

## Testing

Direct service tests cover validation, PNG empty/success/failure paths, visual-diff snapshot states and success, live-preview initialization/no-change/debounce/forced/render failure/render success/reload behavior, state writes, and image response selection.

Adapter tests cover exact names, descriptions, schemas, annotations, delegation, and response conversion. Existing integration tests remain authoritative for real server wiring and compatibility monkeypatch seams. Architecture tests enforce service purity, adapter isolation, and the 300-line registration limit.

## Expected Result

The main schematic `register()` function loses roughly 340 lines. The three rendering tools become independently testable while their observable MCP contract and existing rendering implementation remain unchanged.
