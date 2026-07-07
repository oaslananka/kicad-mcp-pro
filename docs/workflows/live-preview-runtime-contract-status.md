# Live-preview runtime contract status

This branch wires the typed live-preview payload model into the existing `sch_live_preview()` payload builder.

## Implemented

- The legacy live-preview response is normalized through the typed contract model before it is returned.
- Agent-facing fields are now available from the structured response contract: `schema_version`, `tool`, `session_id`, `project_path`, `project_ref`, `watched_files`, `changed_files`, `debounce_ms`, `outcome`, `reload_attempted`, `reload_outcome`, `render_artifacts`, `warnings`, `unsafe_state`, and `next_actions`.
- The contract model distinguishes rendered, reloaded, skipped, pending, fallback, and error-like outcomes.
- The manifest model can produce a `live-preview.manifest.v1` JSON shape from the normalized payload.
- Unit contract tests cover rendered output, reload distinction, render failure, manifest artifact indexing, and debounce bounds.

## Still pending

Runtime manifest file emission from `sch_live_preview()` is not yet enabled in this branch. The model can create the manifest shape, but the code path that writes a durable JSON file under the schematic render artifact directory still needs a small runtime writer.

## Validation

- `python3 -m py_compile src/kicad_mcp/models/live_preview.py src/kicad_mcp/tools/schematic.py tests/unit/test_live_preview_contract.py`
- `uv run --all-extras ruff format src/kicad_mcp/models/live_preview.py src/kicad_mcp/tools/schematic.py tests/unit/test_live_preview_contract.py`
- `uv run --all-extras ruff check src/kicad_mcp/models/live_preview.py src/kicad_mcp/tools/schematic.py tests/unit/test_live_preview_contract.py`

The local pytest invocation for `tests/unit/test_live_preview_contract.py` was attempted but the remote execution safety filter blocked the command output in this environment.
