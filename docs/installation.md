# Installation

## Terminal CLI (recommended)

Use [uv](https://docs.astral.sh/uv/) for a standalone installation. It keeps
the MCP tool isolated from global Python packages and allows the package manager
to safely replace or remove it.

~~~powershell
uv tool install kicad-mcp-pro
kicad-mcp-pro --version
kicad-mcp-pro setup
kicad-mcp-pro doctor
~~~

The no-argument `setup` command starts the guided setup in an interactive
terminal. In scripts or noninteractive terminals, choose a client explicitly:
`kicad-mcp-pro setup --agent claude-code` (preview only by default).
Existing `setup claude-code`, `quickstart` and `init` commands remain supported.

### Check for updates and remove the CLI

~~~powershell
kicad-mcp-pro update check
kicad-mcp-pro update check --json
kicad-mcp-pro uninstall
~~~

`update` and `uninstall` **show the matching package-manager command** rather
than modifying or removing the active running CLI. For a `uv tool` installation:

~~~powershell
uv tool upgrade kicad-mcp-pro
uv tool uninstall kicad-mcp-pro
~~~

For a pip installation, `update` and `uninstall` show a conditional
`python -m pip` command tied to the active interpreter. The CLI **does not
guess that an unknown installation came from pip**: verify its launcher and
package manager before running a suggested command. No installation is
modified by these informational commands.

Do not mix `pip install` with `uv tool install` on the same executable PATH.
`doctor` warns about duplicate `kicad-mcp-pro` launchers before users upgrade
or remove the wrong installation. Package removal is separate from revoking
Cloud devices or removing KiCad MCP entries from independently owned AI-client
configuration files; it does not delete `.kicad_pro`/`.kicad_pcb` projects.

**Windows Cloud status:** The CLI can be used locally without any Cloud account.
On releases lacking native Windows owner-private device registration and the
Windows Connector service, `cloud setup` declines early rather than creating a
partial pairing or claiming that the Cloud owner denied approval. Check the
release notes for native Windows Cloud support before attempting pairing.


## Desktop app

Download the installer for your operating system from the repository's GitHub
Releases page. Published installer behavior depends on its exact release:
the already published 4.9.0 desktop still requires a discoverable external
`uvx` runtime. Candidate desktop installers built with the bundled-bootstrap
release workflow carry pinned `uv` and create their own user-scoped Python
runtime/cache on first startup, requesting managed Python 3.13 for its
desktop-owned environment. They do not install global Python or modify the
user's independent `uv` / MCP CLI installations. The first online startup may
take several minutes while Python and exact backend dependencies are prepared;
the startup screen keeps showing progress instead of failing after 120 seconds.
An online startup is required when the matching runtime is not yet cached.

Automatic updates are not enabled for the published desktop releases.
The application includes Tauri updater integration, but automatic installation
remains unavailable unless the given release configures a valid updater
public key and publishes matching signed updater artifacts. An available GitHub
tag alone is not permission to install an unsigned update. Existing 4.9.0
installers are unsigned; users should verify the official release SHA256 and
provenance and expect potential OS publisher warnings.

### Upgrade

1. Close the desktop application.
2. Download the installer from the newer `kicad-mcp-gui-v*` GitHub release.
3. Install it using the normal package flow for your operating system.
4. Start the application and verify the displayed version and dashboard health.

### Rollback

1. Close the desktop application.
2. Download the installer from the previously trusted `kicad-mcp-gui-v*` release.
3. Reinstall that version using the normal package flow for your operating system.
4. Start the application and verify its version before reopening project work.

Desktop installation does not rewrite KiCad project files. Keep normal project
backups and verify release checksums or provenance when those assets are provided.

### macOS

The macOS desktop release is published as a `.dmg` asset (named `macos_*.dmg`)
on the `kicad-mcp-gui-v*` GitHub release. Open the `.dmg` and drag the app into
`Applications`.

The current release is not Apple-codesigned, so macOS Gatekeeper may block the
first launch. To allow it, open **System Settings → Privacy & Security**, find the
blocked-app notice, and choose **Open Anyway**; then launch the app.

The desktop app requires KiCad 10.x for full GUI/IPC capability. To enable it:

1. Install KiCad 10.x from the official download (the macOS build is a universal
   `.dmg`).
2. Open KiCad and enable the IPC API server:
   `KiCad → Preferences → Scripting → Enable IPC API Server`.
3. Run `kicad-mcp-pro doctor` and confirm the KiCad CLI path, version, and IPC
   status. On macOS the CLI is bundled at
   `/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli`; set
   `KICAD_MCP_KICAD_CLI` if auto-detection misses it.

Without a running KiCad IPC server the app still works in file-backed and
headless modes; live GUI operations report an IPC-disconnected state instead.

To connect an MCP client on macOS, use the **Setup** view's **Client Config**
step, or the `mcp-config generate` command and client paths in
[Client Configuration](client-configuration.md).

### Desktop/backend compatibility

Each desktop release is coupled to the **same exact** `kicad-mcp-pro` backend
version. For example, desktop `3.30.1` launches `kicad-mcp-pro==3.30.1`; it does
not silently fall forward to a newer cached package or fall back to an older one.

Before using an already-running backend or declaring a newly launched backend
ready, the desktop reads `/api/health` and requires the machine-readable
`desktopCompatibility` handshake to report:

- the desktop API contract version expected by the GUI;
- the same backend package version as the desktop release; and
- the `exact-release` version policy.

If another service or an incompatible backend is already listening on the
desktop port, startup fails closed and reports the expected backend and contract
instead of continuing with an unverified API. Stop that process and restart the
desktop, or run the exact backend shown in the error message.

An existing standalone `uvx` installation may reuse its cached environment.
New bundled-bootstrap builds instead use only their application-owned runtime
cache. Offline startup succeeds only after the matching Python and exact
backend have been prepared, and never silently downgrades to a different
version. If app-owned runtime preparation fails, use the desktop retry/repair
path; do not install or change global Python to fix the desktop.

## Disconnect, cleanup and uninstall

Local use does not require a Cloud account. To stop remote sharing, first
disable the relevant Cloud connector and revoke the computer or AI client's
project permission in the authenticated Cloud workspace. **Signing out, local
settings cleanup and OS uninstall do not prove server-side revocation.**
When offline, review and revoke remote access later in the Cloud account.

The local web dashboard's **Maintenance** view offers preview and explicit
confirmation before removing application-owned connector settings and owned
AI-client configuration entries. Only unchanged, fingerprint-verified entries
are eligible for automatic removal; an edited or legacy-unverified entry is
preserved and reported for manual review. User project files, KiCad itself,
other AI MCP servers, shared Python and user-wide caches are never bulk-deleted.

Use the operating system's normal Applications / Installed Apps / package
manager route to remove the desktop installer. That OS operation is separate
from Cloud revoke and local owner-controlled cleanup. A DMG-to-Trash or
AppImage deletion may bypass a running-app cleanup hook. Reinstallation must
not silently re-enable a revoked device or expand project grants. Observe
the actual connected state before saying a device is disconnected.

## Web Dashboard

The desktop app starts the dashboard automatically. You can also run it directly:

```bash
kicad-mcp-pro dashboard --open
# http://127.0.0.1:3334/ui
```

`dashboard --host` accepts only a loopback host; use the server HTTP mode behind
TLS for remote access. `--port` (default `3334`) and `--mode` set the bind port
and the operating mode for the session.

The single-page UI has these views:

- **Dashboard** — server profile, operating mode, transport, host/port, uptime;
  KiCad CLI path, version, and IPC status; active project directory, PCB, and
  schematic paths; a health checklist with an overall verdict; start/stop/restart
  and status-refresh quick actions; and the recent tool-call list.
- **Logs** — an SSE live log viewer with level filters, search, download, and clear.
- **Tools** — the MCP tool catalog with search and category filter. Selecting a
  tool shows its schema, and **Test** runs that tool against the active project.
- **Preview** — schematic render artifacts. It is empty until you run
  `sch_live_preview` to generate one.
- **Settings** — edits KiCad path, transport, host, port, profile, log level, and
  operating mode (changes apply after restart), and exports a ready-to-paste MCP
  client config for Claude Desktop, Cursor, VS Code, Windsurf, or Zed.
- **Setup**: a five-step wizard for KiCad detection, local project selection,
  transport, and guided AI-client configuration. Claude Desktop, Cursor, VS Code
  and Windsurf use preview plus explicit apply to preserve unrelated MCP
  entries and back up existing settings. Other clients retain manual snippet
  export. When launched from a newly bundled desktop, local client configuration
  reuses its exact pinned `uv` executable and private runtime cache; normal
  setup does not require a separate global Python/`uvx` install. Saving the
  client configuration is not evidence that the AI host connected: verify a
  real MCP read in the client before declaring it ready.

The dashboard reads project and KiCad state; it does not run ERC or DRC itself.
Run `run_erc()`, `run_drc()`, or `validate_design()` from your MCP client and
review the reported findings there.

## Recommended
```bash
uvx kicad-mcp-pro
```

## Package install
```bash
pip install kicad-mcp-pro
```

## HTTP support
```bash
pip install "kicad-mcp-pro[http]"
```

After installation, add the server to your MCP client. See
[Client Configuration](client-configuration.md) for VS Code, Codex, Claude, Cursor,
Gemini CLI, and generic MCP client examples.

## Source development checkout

Published-package installation above is separate from contributor setup. On a
supported Linux development host, prepare a clone with the repository-owned
bootstrap:

```bash
./scripts/bootstrap-dev.sh
source .dev-env.sh
pnpm run dev:doctor -- --ci
```

The bootstrap uses reviewed versions and checksums and keeps tools and caches
inside the checkout. See [Reproducible development bootstrap](development/reproducible-bootstrap.md)
for supported hosts, `--core-only`, verification, cleanup, checksum recovery,
and the distinction between headless KiCad CLI and a live GUI/IPC session.
