# ChatGPT App - KiCad MCP Integration

This directory contains the public-safe ChatGPT App adapter for KiCad MCP Pro.
It serves a stateless Streamable HTTP MCP endpoint and three browser widgets.

## Current architecture and trust boundaries

```text
remote MCP host
    -> HTTPS/reverse proxy controlled by the deployer
    -> apps-sdk/src/server.ts
       -> read-only app tools
       -> allowlisted upload roots
       -> static widgets

local-only path, separate from the remote app:
local MCP client -> 127.0.0.1 bridge -> local kicad-mcp-pro HTTP server
```

The remote app does not provide a relay to a workstation and cannot access a
user's local KiCad process by itself.

## Public-safe profile (supported)

The supported profile is read-only. It provides project summary, DRC/ERC
explanation, manufacturing-readiness reporting, documentation search, and agent
configuration generation. All six tools publish MCP annotations that identify
them as read-only, non-destructive, and idempotent.

Project paths must resolve below the OS temp directory or an operator-provided
`KICAD_MCP_UPLOAD_ROOTS` entry. The `/api/analyze` endpoint is rate limited.

## Remote-to-local bridge (not currently supported)

The Python bridge binds to `127.0.0.1` and uses newline-delimited JSON-RPC over a
local TCP socket. It does not provide a hosted relay, browser transport, or NAT
traversal. After pairing it does not implement per-tool local approval. Do not
expose the bridge port to an untrusted network or describe ChatGPT web-to-local
mutation as a supported path.

Local write workflows should use a local stdio or local Streamable HTTP client
where the operator controls process and filesystem access.

## App files

| File | Purpose |
|---|---|
| `apps-sdk/package.json` | Package metadata and validation commands |
| `apps-sdk/src/server.ts` | Stateless MCP server and read-only tools |
| `apps-sdk/test/app-smoke.test.mjs` | Real SDK connection and restart smoke test |
| `apps-sdk/public/kicad-dashboard.html` | Project overview widget |
| `apps-sdk/public/project-review.html` | DRC/ERC review widget |
| `apps-sdk/public/manufacturing-report.html` | Manufacturing checklist widget |

## Verify

```bash
cd integrations/chatgpt-app/apps-sdk
npm ci
npm run typecheck
npm run build
npm run test:smoke
```

The smoke test verifies the package/server version contract, exact tool catalog,
read-only annotations, a real tool call, all widget routes, clean shutdown, and
reconnection after process restart.

## Deployment requirements

- Terminate TLS before exposing the app publicly.
- Add deployment-appropriate authentication and request controls.
- Configure only trusted upload roots.
- Never mount private project directories into a public deployment.
- Treat uploaded KiCad archives as untrusted input.
- Keep local bridge and local KiCad transports on loopback unless a separately
  reviewed secure relay is implemented.

## Directory evidence

Run the repository-wide normal and final submission checks before any external
form is submitted:

```bash
pnpm run submission:check
SUBMISSION_MODE=1 pnpm run submission:check
```

Domain verification and external review status are tracked manually in
`docs/public-listing.md`.
