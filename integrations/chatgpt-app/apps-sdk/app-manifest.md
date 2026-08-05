# KiCad MCP Pro ChatGPT App Manifest

## App info

- **Name:** KiCad MCP Pro
- **Package:** `kicad-mcp-chatgpt-app`
- Version: `0.2.0`
- **Category:** Developer Tools
- Supported profile: public-safe, read-only
- Local mutation bridge: not currently supported

The app analyzes uploaded or operator-mounted KiCad project data inside explicit
upload roots. It does not provide direct access from ChatGPT web to a local KiCad
process.

## Tools

| Tool | Purpose | Read-only | Open-world |
|---|---|---:|---:|
| `search_kicad_knowledge` | Search KiCad documentation | Yes | Yes |
| `analyze_uploaded_kicad_project` | Summarize an uploaded project | Yes | No |
| `explain_drc_report` | Interpret DRC text | Yes | No |
| `explain_erc_report` | Interpret ERC text | Yes | No |
| `generate_manufacturing_readiness_report` | Build a readiness checklist | Yes | No |
| `generate_agent_config` | Generate local client configuration | Yes | No |

All tools export `readOnlyHint=true`, `destructiveHint=false`, and
`idempotentHint=true`. No tool in this app performs a local project mutation.

## UI components

| Widget | File | Purpose |
|---|---|---|
| Project overview | `public/kicad-dashboard.html` | Board and quality summary |
| Project review | `public/project-review.html` | DRC/ERC findings |
| Manufacturing report | `public/manufacturing-report.html` | Release checklist |

## Transport and auth boundary

- MCP transport: stateless Streamable HTTP at `/mcp`.
- Local development: loopback without built-in authentication.
- Public deployment: TLS and deployment-specific authentication are required in
  the reverse proxy or hosting platform.
- The package does not implement OAuth, a hosted workstation relay, or per-tool
  local approval.

## Verification

```bash
npm ci
npm run typecheck
npm run build
npm run test:smoke
```

`npm run test:smoke` uses a real MCP SDK client to verify server identity, the
exact tool catalog and annotations, a tool call, all three widgets, process
shutdown, restart, and reconnection.

## Submission checklist

- [x] Package and runtime server versions are synchronized.
- [x] Public-safe tools are explicitly read-only and non-destructive.
- [x] Streamable HTTP connection and restart recovery have automated evidence.
- [x] Widget routes have automated smoke coverage.
- [x] Privacy, screenshots, demo media, metadata, and reviewer prompts pass the
  normal and final repository submission checks.
- [ ] Public HTTPS deployment and authentication are configured.
- [ ] Platform-provided domain verification is complete.
- [ ] Final ChatGPT Apps dashboard submission is recorded in
  `docs/public-listing.md`.
