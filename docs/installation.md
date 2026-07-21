# Installation

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
