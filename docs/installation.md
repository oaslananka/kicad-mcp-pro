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
