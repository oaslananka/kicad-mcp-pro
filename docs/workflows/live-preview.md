# Safe live-preview workflow

This workflow describes how agents and operators should use `sch_live_preview()` without risking unsaved KiCad GUI edits.

## Purpose

`sch_live_preview()` is a polling workflow for schematic feedback. It records a baseline of watched schematic files, detects stable changes after a debounce window, and can generate rendered PNG/SVG artifacts plus a manifest for visual review.

Use it when an agent needs a closed feedback loop after schematic mutations:

1. Apply a schematic change with a transactional tool.
2. Poll `sch_live_preview()` until the debounce window has settled.
3. Review the returned structured payload.
4. Inspect the rendered PNG or follow with `sch_render_visual_diff()` and `sch_visual_qa()`.
5. Continue only when the visual artifact and quality checks match the intended design.

## Safety model

The safe default is artifact-based feedback. The tool should prefer rendered PNG/SVG/manifest evidence over any operation that asks the KiCad GUI to refresh the user-visible sheet.

The MCP process cannot reliably prove that a human has no unsaved KiCad GUI edits. For that reason, GUI refresh behavior must remain explicit and operator-approved. Agents must not treat a rendered PNG as proof that the KiCad GUI has refreshed its open editor tab.

`reload=true` is a best-effort GUI-facing request, not a guarantee that KiCad will reload the already-open schematic document from disk. KiCad `View -> Refresh` may redraw the viewport without re-reading the schematic file. Agent workflows must therefore treat `render`, `render_artifacts`, and the live-preview manifest as the authoritative review evidence.

## Recommended agent sequence

```text
1. sch_live_preview(force=true, render=true)
2. mutate the schematic with a transactional writer
3. sch_live_preview(render=true, debounce_ms=750)
4. if status is pending_debounce, call again after the debounce window
5. sch_render_visual_diff()
6. sch_visual_qa()
7. continue only if structured status and visual evidence are acceptable
```

## Tool boundaries

- `sch_live_preview()` watches schematic files and refreshes preview evidence after stable changes.
- `sch_render_png()` renders one selected schematic sheet to a PNG artifact.
- `sch_render_visual_diff()` compares schematic visual state before and after changes.
- `sch_visual_qa()` checks visual readability and schematic presentation defects.
- `sch_reload()` is a separate GUI-facing operation and should be treated as best-effort. It should not be used blindly in automated flows.

## Child sheets

By default, `sch_live_preview()` includes child sheets when computing the watched-file signature. This means edits in a hierarchical sheet can trigger a preview event even when the root sheet timestamp has not changed.

Set `include_child_sheets=false` only when an agent intentionally wants root-sheet-only behavior.

## Debounce behavior

A schematic writer may touch multiple files or update one file multiple times in quick succession. The debounce window prevents the agent from treating an intermediate write as the final preview state.

A typical flow is:

- first call records the baseline;
- next call detects a change and returns `pending_debounce`;
- after the debounce window, the next call returns the settled status and preview evidence.

## Structured result contract

Agent code should read structured fields instead of parsing human-readable messages. Important fields include:

- `status`: current workflow status such as `initialized`, `no_change`, `pending_debounce`, `changed_rendered`, or `forced_rendered`;
- `target_path`: schematic sheet used as the primary target;
- `watch_files`: files included in the signature;
- `changed_files`: files that changed since the previous accepted baseline;
- `signature`: per-file size, mtime, and digest evidence;
- `render`: generated image artifact metadata when rendering succeeds or fails;
- `render_artifacts`: PNG, SVG, and manifest evidence artifacts associated with the preview;
- `manifest_path`: durable JSON manifest path when manifest persistence succeeds.

Agents should ignore unknown fields for forward compatibility.

## Troubleshooting

If no preview appears, first check whether the response is `initialized` or `pending_debounce`. These are normal states. Call again after a schematic mutation or after the debounce window.

If rendering fails, run `sch_render_png()` directly for the selected sheet and inspect the returned diagnostic message. Do not assume a GUI refresh happened just because a GUI-facing request was made.

If the selected sheet is empty, the render result may report an empty-sheet state instead of emitting a misleading blank image.