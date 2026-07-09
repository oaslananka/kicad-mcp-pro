# KiCad companion plugin

A small KiCad **Action Plugin** that connects the running pcbnew GUI to a local
kicad-mcp-pro server. It lets an agent see what you have open and selected, and gates
any board-mutating action behind a confirmation dialog.

It is intentionally minimal-permission: it talks **only** to the loopback MCP
endpoint and never writes files itself.

## What it does

- Publishes the active project / file / selection context to the MCP server
  (via the existing `studio_push_context` tool).
- Can request server-side visual artifacts (`sch_render_png`) and net highlight
  attempts (`pcb_highlight_net`) through the same loopback `tools/call` path.
- Surfaces health/status of the connection in a dialog.
- Provides a **safe-apply** confirmation gate (`confirm_safe_apply`) that mutating
  flows must pass before touching the board.

The plugin is a thin GUI shim; all of its logic lives in the dependency-free,
unit-tested `kicad_mcp.companion.context` module so it can evolve without a KiCad
in the loop.

## Install

1. Locate your KiCad plugins directory:
   - **Windows:** `%APPDATA%\kicad\<version>\scripting\plugins`
   - **macOS:** `~/Documents/KiCad/<version>/scripting/plugins`
   - **Linux:** `~/.local/share/kicad/<version>/scripting/plugins`
   (or open *Tools → External Plugins → Open Plugin Directory* in pcbnew).
2. Copy or symlink `packages/kicad-plugin` into that directory as
   `kicad_mcp_companion`. The plugin is **self-contained** — it ships a vendored
   copy of `context.py`, so no `KICAD_MCP_HOME` and no system-wide install are
   required.
3. Optional environment overrides:

   ```bash
   export KICAD_MCP_URL=http://127.0.0.1:3334   # optional, this is the default
   export KICAD_MCP_AUTH_TOKEN=...              # only if the server requires auth
   # KICAD_MCP_HOME is only needed for a non-vendored dev checkout fallback.
   ```

4. Restart pcbnew, then run *Tools → External Plugins → Refresh*. A
   **kicad-mcp companion** toolbar button appears.

## Smoke test plan

These steps require a real KiCad install and cannot be exercised in headless CI;
the dependency-free helpers are covered by `tests/unit/test_companion_context.py`.

1. Start the server in **write** mode (the `studio_push_context` tool is rejected
   in the default read-only mode):
   `uv run kicad-mcp-pro --transport streamable-http --port 3334 --mode write`.
   The client sends `Accept: application/json, text/event-stream` as the MCP
   Streamable HTTP transport requires.
2. Open any `.kicad_pcb` in pcbnew.
3. Click **kicad-mcp companion**. Expect an information dialog confirming the
   context push to `http://127.0.0.1:3334`.
4. In another MCP client, read the `kicad://studio/context` resource and confirm
   the active file and project root match what is open in KiCad.
5. Select a footprint, push again, and confirm `selected_reference` updates.
6. From a test shell or KiCad console, call `StudioContextClient().request_render_artifact()`
   and confirm the MCP server returns either a PNG artifact path or a clear
   renderer-unavailable response.
7. Call `StudioContextClient().request_highlight_net("GND")` and confirm the
   server returns the current highlight capability status without mutating files.
8. Stop the server and push again. Expect a clear error dialog (no crash).
9. Trigger a mutating action and confirm the **safe-apply** dialog appears and
   that declining it leaves the board unchanged.

## Security notes

- The plugin connects to `127.0.0.1` only.
- It does not request filesystem or network permissions beyond the loopback POST.
- Mutating operations are listed in `SAFE_APPLY_ACTIONS` and always require an
  explicit confirmation via `confirm_safe_apply`.

## Live-preview opt-in refresh UX

The companion plugin must keep live-preview feedback artifact-first by default.
A plugin button or agent command may request `sch_live_preview(render=true)` to
produce a preview image, but it must not silently change the user's open KiCad GUI
state to update.

Recommended UX contract:

1. Show a clear action label such as **Refresh preview evidence** for ordinary
   artifact generation.
2. Use a separate, explicit action label such as **Refresh open KiCad view** for
   GUI-facing behavior.
3. Before any GUI-facing refresh, show a confirmation dialog explaining that the
   MCP server cannot prove whether the editor has unsaved human changes.
4. Remember consent only for the current plugin session; do not persist it across
   KiCad restarts.
5. Surface the resulting status in the dialog or status pane, including whether
   the operation produced a PNG artifact, skipped because no change was detected,
   or failed with a renderer diagnostic.

Agents should treat preview PNGs, visual diffs, and visual QA results as evidence
for review, not as proof that a human user's editor tab has been updated.
