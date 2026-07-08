# Live-preview runtime contract status

This branch wires the typed live-preview payload model into the existing `sch_live_preview()` payload builder.

## Implemented

- The legacy live-preview response is normalized through the typed contract model before it is returned.
- Agent-facing fields are now available from the structured response contract: `schema_version`, `tool`, `session_id`, `project_path`, `project_ref`, `watched_files`, `changed_files`, `debounce_ms`, `outcome`, `reload_attempted`, `reload_outcome`, `reload_confirmed`, `reload_mode`, `upstream_blockers`, `render_artifacts`, `warnings`, `unsafe_state`, and `next_actions`.
- The contract model distinguishes rendered, reload-requested, confirmed-reloaded, skipped, pending, fallback, and error-like outcomes.
- The manifest model can produce a `live-preview.manifest.v1` JSON shape from the normalized payload.
- Unit contract tests cover rendered output, best-effort GUI reload requests, render failure, manifest artifact indexing, and debounce bounds.

## Reload semantics

`reload_attempted=true` records a best-effort GUI-facing request. It does not prove that the already-open KiCad schematic document reloaded from disk. Until KiCad exposes a confirmed silent schematic `RevertDocument` IPC path, clients must treat rendered artifacts and manifests as the authoritative review evidence. The upstream blocker is <https://gitlab.com/kicad/code/kicad/-/work_items/24803>.

## Still pending

Runtime manifest file emission from `sch_live_preview()` is not yet enabled in this branch. The model can create the manifest shape, but the code path that writes a durable JSON file under the schematic render artifact directory still needs a small runtime writer.

## Validation

- `python3 -m py_compile src/kicad_mcp/models/live_preview.py src/kicad_mcp/tools/schematic.py tests/unit/test_live_preview_contract.py`
- `uv run --all-extras ruff format src/kicad_mcp/models/live_preview.py src/kicad_mcp/tools/schematic.py tests/unit/test_live_preview_contract.py`
- `uv run --all-extras ruff check src/kicad_mcp/models/live_preview.py src/kicad_mcp/tools/schematic.py tests/unit/test_live_preview_contract.py`

`uv run --all-extras python -m pytest tests/unit/test_live_preview_contract.py -q`
