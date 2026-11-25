# KiCad companion plugin

The KiCad 10 IPC companion is an independent, compact wxPython window opened
from the PCB Editor toolbar. It connects to the existing local KiCad MCP Pro
backend; it does not mutate board data or install/start a second server.

## What it does

- Shows the active PCB, current selection and backend readiness.
- **Sync PCB context** explicitly reads the current board and selection through
  KiCad IPC and publishes context to the compatible loopback backend.
- **More tools** offers a manual saved-board DRC check, a read-only findings
  table, the local dashboard and refresh. DRC uses a private copy of the
  saved file, excluding unsaved edits; it is not a manufacturing gate.
- **Select exact items in KiCad**, when available, changes editor selection only
  after verifying persisted UUIDs against the saved and live board. It never
  saves or changes PCB data.

The companion is a separate, non-always-on-top window, not a docked KiCad pane.
See the [companion README](https://github.com/oaslananka/kicad-mcp-pro/tree/main/packages/kicad-plugin)
for the detailed selection, DRC and optional Linux window-arrangement boundaries.

## Install

The maintained packaging target is a KiCad Plugin and Content Manager (PCM) v2
archive, declaring runtime: `ipc` and minimum KiCad version 10.0. Use KiCad 10,
enable its **IPC API server**, and use its graphical wxPython-enabled Python
runtime. KiCad manages the plugin's isolated Python environment and installs
the packaged kicad-python dependency. The separately installed backend is
required for context sync and the dashboard.

### PCM candidate flow

Until the package is accepted into the official KiCad addon repository, use the
versioned ZIP from a trusted project release or build the exact source revision:

```bash
uv run --all-extras python scripts/build_kicad_pcm.py \
  --output-dir ./release-assets/kicad-pcm \
  --verify
```

Verify the release checksum and provenance. In KiCad open **Plugin and Content
Manager**, choose **Install from File**, select
`kicad-mcp-pro-pcm-<version>.zip`, and restart KiCad. Open a PCB and choose
**Open MCP Pro Companion** from the PCB Editor toolbar. This local-file PCM
path is not an official PCM listing.

The existing `uvx kicad-mcp-pro` entry point remains supported independently
of PCM. Start the separately installed compatible backend when you need to sync:

```bash
uvx "kicad-mcp-pro@<version>" --transport streamable-http --host 127.0.0.1 --port 3334 --mode write
```

Replace `<version>` with the matching release version. The package's
`compatibility.json` specifies its accepted backend version range. The write
mode is needed for the explicit context-publishing tool; it does not grant
automatic board-edit permission. Keep existing authentication and approval
boundaries intact.

The companion checks `/api/health` before publishing context. Backend states
include:

- `ready` — backend is healthy and inside the package compatibility window;
- `backend_unreachable` — start the local backend and retry;
- `backend_unhealthy` — run `kicad-mcp-pro doctor` and resolve the reported health issue;
- `backend_incompatible` — install a compatible backend release;
- `authentication_required` — correct the local auth/proxy configuration;
- `runtime_unavailable` — the required KiCad/runtime capability is unavailable.

Sync requires a current board and a ready backend, and rechecks the selection
before sending context. Missing or malformed compatibility metadata fails
closed. If IPC dependencies are incomplete, use **Repair KiCad IPC
dependencies…** only after reviewing the confirmation; the repair targets the
KiCad-managed environment, not global Python.

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
kicad-mcp-pro setup-backups cursor --scope project --project-dir /path/to/project
kicad-mcp-pro setup-restore cursor --scope project --project-dir /path/to/project
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

For development only, use the KiCad 10 IPC plugins directory as described in
the companion README. Do not copy the legacy scripting plugin into the current
PCM installation. Users should prefer PCM.

### Modern plugin API readiness

The maintained package already uses the modern KiCad plugin API (IPC), with
`plugin.json`, a separate Python process and no SWIG fallback. The package
retains its development status. Historical Linux/Windows PCM evidence is not
a qualification of the current IPC artifact; current platform-specific
acceptance is required. KiCad 11 support remains preview-only until its own
native gates pass. See [ADR 0007](../adr/0007-kicad-adapter-selection-and-swig-retirement.md).

## Smoke test plan

Use disposable board files and a private KiCad profile. Record the exact source,
release artifact digest, platform and KiCad version; do not claim full physical
acceptance from unit tests or a virtual-display smoke alone.

1. Install the verified release ZIP through PCM, restart and confirm that
   **Open MCP Pro Companion** appears in the PCB Editor.
2. Open a saved fixture PCB and the companion. With the backend stopped,
   confirm actionable unavailable status and disabled sync.
3. Start the compatible loopback backend in the reviewed write mode. Refresh
   the companion, verify board/selection counts and choose **Sync PCB context**.
4. In a separate MCP client, verify the reported project and selection through
   the existing `kicad://studio/context` resource. Select another footprint and
   explicitly sync again; verify that the fresh reference is reported.
5. Optionally choose **More tools → Check saved PCB** and inspect the findings.
   Verify that the board file hash remains unchanged; only use exact-item
   selection when the verified UUID action is available.
6. Exercise an incompatible backend and verify that context sync fails closed.
7. Install a trusted compatible update or reinstall, verify discovery after
   restart, uninstall through PCM and check that unrelated client configuration
   is preserved. Reinstall the previous trusted release to verify rollback.

## Security notes

- The companion talks to a validated loopback endpoint. It does not expose a
  network service or silently start/install the backend.
- Board context publication requires explicit sync and healthy compatible
  backend. Saved-board DRC uses a temporary copy; the companion does not write
  the user's board or automatically correct a finding.
- Client configuration writes, backend mutation permissions and manufacturing
  acceptance retain their separate approval boundaries.
- Optional desktop tiling is confirmed and limited to supported Linux X11
  configurations; it does not imply native docking or automatic editor refresh.

## Live-preview opt-in refresh boundary

Keep live-preview feedback artifact-first. The companion does not currently
provide a native preview-refresh action. Any future editor-facing refresh
must use a separate explicit action, explain that unsaved human edits cannot
be verified, obtain session-scoped consent and report the actual outcome.
Never infer that an editor view was updated merely because a preview image
was produced. See the [tool workflow](../tools-agent-workflow.md).
