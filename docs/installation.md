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


## Local HTTP server (no desktop application)

Install or run the Python MCP server. The local browser dashboard and Streamable
HTTP transport remain supported without Tauri or an installer.

~~~powershell
uvx kicad-mcp-pro --transport streamable-http --host 127.0.0.1 --port 3334
~~~

Enter `http://127.0.0.1:3334/mcp` in a Streamable HTTP-capable AI client.
Use the loopback address unless you have intentionally configured
authentication and an HTTPS reverse proxy for remote access.

To open the owner-only setup dashboard instead:

~~~powershell
uvx kicad-mcp-pro dashboard --host 127.0.0.1 --port 3334 --open
~~~

The dashboard opens in a normal browser at `http://127.0.0.1:3334/ui`.
Its **Browse** action uses the local owner-only, CSRF-protected HTTP API
to open the operating system's folder chooser. Choosing a folder does not
by itself share a KiCad project or authorize an AI client.

### Optional Cloud access

Open [KiCad MCP Cloud](https://kicad-mcp-pro.oaslananka.dev/) only when
remote AI access is needed. Account sign-in, device pairing, Connector
availability, and each per-project AI-client grant are separate.
Cloud's HTTPS Streamable MCP endpoint is `/mcp`; neither signing in nor
pairing shares project files automatically.

Historic Tauri GUI releases remain archival GitHub artifacts but the desktop
application and GUI release family are retired from future development.

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

For a current CLI installation, remove the package using its confirmed
package manager (uv tool or the active pip environment), as explained
above. If you still have a retired desktop installer, remove it through
your operating system's application manager. Neither action revokes Cloud
access: verify the actual Connector and project-grant state after removal.

## Web Dashboard

The dashboard runs in your normal browser and needs no desktop application:

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
  export. Saving a client configuration does not prove the AI host is connected:
  verify a real MCP read in the client before declaring it ready.

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
