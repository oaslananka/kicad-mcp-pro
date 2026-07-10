# MCP Bundle (.mcpb) Install

An [MCP Bundle](https://github.com/modelcontextprotocol/mcpb) (`.mcpb`, formerly
DXT) lets a desktop app such as Claude Desktop register this server from a single
file instead of hand-editing a JSON config.

## Scope and honesty

This bundle is a **configuration convenience, not a fully self-contained
one-click install.** It carries only the manifest and icon — it does *not* embed
KiCad, `uv`, or the server code. Specifically:

- **KiCad must already be installed** (the server shells out to `kicad-cli`).
- **`uv` must be installed**; the bundle launches `uvx kicad-mcp-pro`, which
  resolves and caches the published package on first run (needs network the
  first time).
- It always tracks the **published** `kicad-mcp-pro` release, so there is no
  bundled-code drift.

If you would rather not install a bundle, the manual config in
[Claude Desktop Integration](claude-desktop.md) does exactly the same thing.

## Install

1. Download `kicad-mcp-pro.mcpb` (built from `packaging/mcpb/`, attached to
   releases where available).
2. Open your desktop app's extensions/MCP settings and install the `.mcpb` file.
3. Restart the app and confirm the `kicad` server appears.

## Build it yourself

```bash
corepack pnpm run mcpb:validate   # schema + icon check
corepack pnpm run mcpb:pack       # writes dist/kicad-mcp-pro.mcpb
```

The manifest lives at `packaging/mcpb/manifest.json`. Its `version` field is
kept in sync with the package version by release-please, so it never drifts.

## Verification

```bash
kicad-mcp-pro doctor --agent claude-desktop
```

Then ask the agent: *"Use the kicad MCP server to inspect the current project."*
For environment variables (project dir, profile, operating mode) and
troubleshooting, see [Claude Desktop Integration](claude-desktop.md).
