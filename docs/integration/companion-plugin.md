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

The maintained packaging target is a KiCad Plugin and Content Manager (PCM) v2
archive. The current companion is still a legacy `pcbnew.ActionPlugin`, so the
package truthfully declares `runtime: `swig`` and a minimum KiCad version of
10.0. It does **not** bundle or fork the MCP backend.

### PCM candidate flow

Until the package is accepted into the official KiCad addon repository, use the
versioned ZIP from a trusted project release or build the exact source revision:

```bash
uv run --all-extras python scripts/build_kicad_pcm.py \
  --output-dir ./release-assets/kicad-pcm \
  --verify
```

Then in KiCad open **Plugin and Content Manager**, choose **Install from File**,
select `kicad-mcp-pro-pcm-<version>.zip`, restart KiCad, and confirm the
**kicad-mcp companion** action is discovered. This local-file PCM path is the
pre-submission validation path; it must not be described as an official PCM
listing until the KiCad metadata repository merge request is accepted.

The companion expects the canonical backend on loopback. A power-user/backend
installation remains first-class:

```bash
uvx kicad-mcp-pro --transport streamable-http --port 3334 --mode write
```

The toolbar action checks `/api/health` before pushing context. User-facing
readiness states are closed and fail-safe:

- `ready` — backend is healthy and inside the package compatibility window;
- `backend_unreachable` — start the local backend and retry;
- `backend_unhealthy` — run `kicad-mcp-pro doctor` and resolve the reported health issue;
- `backend_incompatible` — install the backend release compatible with the PCM package;
- `authentication_required` — correct the local auth/proxy configuration;
- `runtime_unavailable` — the required KiCad/runtime capability is unavailable.

No context/tool call is attempted unless the state is `ready`. The package
compatibility file is machine-readable and malformed or missing metadata fails
closed.

### Guided MCP client configuration

PCM installation never edits another application's configuration. Preview the
exact generated change first, then opt into a write explicitly:

```bash
kicad-mcp-pro setup claude-code --project-dir /path/to/project
kicad-mcp-pro setup codex --project-dir /path/to/project --scope user
kicad-mcp-pro setup cursor --project-dir /path/to/project

# Only after reviewing the preview:
kicad-mcp-pro setup cursor --project-dir /path/to/project --write
```

The write path merges only the KiCad MCP server entry, preserves unrelated
settings/servers, validates the merged config, creates a timestamped backup, and
uses an atomic replace. Existing invalid JSON/TOML fails before mutation. Inspect
or restore backups with:

```bash
kicad-mcp-pro setup-backups cursor --scope project
kicad-mcp-pro setup-restore cursor --scope project
```

Claude Code, Codex and Cursor use this same reversible transaction boundary. A
conflicting owned `kicad` entry is changed only through the explicit `--write`
path; preview mode remains side-effect-free.

### Update, Uninstall, and Rollback

**Update:** install a newer trusted PCM ZIP only after verifying its release
checksum/provenance. Before official repository publication, treat update-by-file
as a validation path rather than automatic update support.

**Uninstall:** remove **KiCad MCP Pro** from KiCad's Plugin and Content Manager.
Uninstalling the PCM package does not delete MCP client configuration or its
backups; disconnect/restore client configuration separately when desired.

**Rollback:** uninstall the current companion, reinstall the previously trusted
versioned PCM ZIP with **Install from File**, restart KiCad, and confirm the
backend compatibility status before resuming work.

### Developer-only manual plugin copy

Manual copying remains only a source-development fallback. Copy or symlink
`packages/kicad-plugin` into the platform KiCad scripting plugin directory and
refresh external plugins. Production/user onboarding should prefer PCM rather
than manual plugin-directory manipulation.

### Modern plugin API readiness

The current PCM package is SWIG-based. It is **not** a modern KiCad IPC plugin.
Migration to the modern KiCad plugin API must preserve current KiCad 10 behavior,
move to the supported external-plugin/IPC contract, add the required `plugin.json`
shape, and obtain real-KiCad compatibility evidence before changing the PCM
`runtime` to `ipc` or claiming future-version support. See
[ADR 0007](../adr/0007-kicad-adapter-selection-and-swig-retirement.md) for the
existing SWIG-retirement boundary.

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
