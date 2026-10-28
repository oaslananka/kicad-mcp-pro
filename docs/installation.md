# Installation

## Desktop app

Download the installer for your operating system from the repository's GitHub
Releases page. Automatic updates are not enabled: the desktop application does
not check for, download, or install releases in the background.

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

`uvx` may reuse the exact release environment from its cache. When the machine
is offline and that exact backend is not cached, startup fails rather than
selecting a different version; reconnect long enough for `uvx` to obtain the
required release, or pre-cache that exact version before going offline.

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
- **Setup** — a five-step wizard: KiCad detection, default project directory,
  transport, MCP client config (preview and copy), and a connection test.

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
