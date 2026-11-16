# Getting started tutorial

This tutorial is the first guided path for a new user who wants to verify that KiCad MCP Pro can start and expose tools to an MCP-capable client.

## Prerequisites

- Python 3.13.
- Node.js 26.13.1 (or supported Node.js 24.22.3) for the npm wrapper or repository development flow; install pnpm 11.28.6 explicitly for repository tasks.
- KiCad 10.x when you want live KiCad CLI/IPC integration.
- A local project directory for experiments. Do not begin with customer or private manufacturing data.

## 1. Install

```bash
uvx kicad-mcp-pro@latest --help
```

For local development from the repository:

```bash
npm install --global pnpm@11.28.6 --no-audit --no-fund
pnpm install --frozen-lockfile
uv sync --all-extras --frozen
```

## 2. Start in read-only mode

```bash
KICAD_MCP_OPERATING_MODE=readonly uv run --all-extras kicad-mcp-pro --help
```

## 3. Run a basic health check

```bash
uv run --all-extras kicad-mcp-pro health --json
```

## 4. Connect a client

Use the client configuration generator or the agent-specific setup docs:

- `docs/client-configuration.md`
- `docs/agents/index.md`
- `docs/agents/security.md`

## 5. Next steps

- Task recipes: `docs/how-to/index.md`.
- Tool details: `docs/reference/index.md`.
- Architecture rationale: `docs/explanation/architecture.md`.
