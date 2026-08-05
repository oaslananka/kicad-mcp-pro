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
