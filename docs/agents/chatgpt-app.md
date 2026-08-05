# ChatGPT Web Integration

KiCad MCP Pro has one verified ChatGPT-facing profile today: a public-safe,
read-only Streamable HTTP app. It can analyze repository-owned or uploaded
project data inside an explicitly configured upload root and render three HTML
widgets. It does not grant ChatGPT direct access to a user's local KiCad process.

## Current architecture and trust boundaries

```text
ChatGPT web / MCP client
        |
        | HTTPS Streamable HTTP (deployment boundary)
        v
KiCad MCP Pro ChatGPT App
  - six read-only tools
  - upload-root containment
  - rate-limited analysis endpoint
  - dashboard, review, and manufacturing widgets
        |
        | optional local subprocess on the same trusted host
        v
kicad-mcp-pro package / uploaded fixture data

Separate localhost-only component (not reachable from ChatGPT web):
local client -> 127.0.0.1 TCP bridge -> local Streamable HTTP server -> KiCad
```

The public deployment operator is responsible for HTTPS, authentication, and
network policy. The app package itself does not provide a hosted relay between
ChatGPT and a user's workstation.

## Public-safe profile (supported)

The supported profile exposes these read-only tools:

- `search_kicad_knowledge`
- `analyze_uploaded_kicad_project`
- `explain_drc_report`
- `explain_erc_report`
- `generate_manufacturing_readiness_report`
- `generate_agent_config`

Every tool is exported with `readOnlyHint=true`, `destructiveHint=false`, and
`idempotentHint=true`. Only documentation search is marked open-world. Uploaded
paths are canonicalized and must remain under the OS temporary directory or a
root listed in `KICAD_MCP_UPLOAD_ROOTS`.

## Remote-to-local bridge (not currently supported)

`kicad-mcp-pro bridge` binds to `127.0.0.1` and accepts newline-delimited JSON-RPC
from a local client after pairing. It does not provide a hosted relay, NAT
traversal, browser transport, or remote discovery. It also does not implement
per-tool local approval after pairing. Therefore ChatGPT web cannot securely pair
directly with this bridge, and local write/mutation workflows must not be claimed
as supported by the ChatGPT App.

Use local stdio or local Streamable HTTP clients for KiCad mutation workflows.
Keep the bridge port localhost-only.

## Verified host matrix

| Host path | Status | Verification |
|---|---|---|
| Generic MCP SDK client -> public-safe app | Supported | `npm run test:smoke` |
| ChatGPT-compatible stateless HTTP profile | Supported protocol profile | `tests/integration/test_mcp_2026_host_smoke.py` |
| Browser widget static assets | Supported | `npm run test:smoke` |
| Local stdio clients -> local KiCad server | Supported separately | main server CI matrix |
| ChatGPT web -> localhost bridge | Not currently supported | no relay or per-tool approval |

## Local verification

```bash
cd integrations/chatgpt-app/apps-sdk
npm ci
npm run typecheck
npm run build
npm run test:smoke
```

The smoke test starts the compiled server, connects with the official MCP SDK,
validates identity, tool annotations, tool execution, and all widgets, stops the
process, restarts it, and reconnects.

## Directory submission

Repository media, privacy, metadata, and reviewer evidence are checked with:

```bash
pnpm run submission:check
SUBMISSION_MODE=1 pnpm run submission:check
```

Platform domain verification and the final dashboard submission remain manual.
See [`../submission/chatgpt-apps.md`](../submission/chatgpt-apps.md).
