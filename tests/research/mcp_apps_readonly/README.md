# Isolated read-only MCP Apps proof — issue #1220

This is a **disposable, private research fixture**, not part of the production
KiCad MCP server, npm distribution, Cloud service, or ChatGPT Apps connector.
It never opens local KiCad designs, connects to KiCad IPC, accesses project
folders, calls write tools or creates manufacturing output. All three scenarios
are synthetic and clearly labeled as such.

The UI shows DRC/ERC counts and severity-filtered findings. A client without
MCP Apps UI support receives an equally useful **plain-text tool result**.
The sole tool (`review_kicad_fixture`) accepts only optional `variant`
(`pcb-drc`, `schematic-erc`, `empty`). It does not accept file paths,
URLs or uploads. The sole view is `ui://kicad-mcp-pro/readonly-review`.

## Reproducible local verification

Requires Node 26 and **pnpm 11.28.6**. Commands are run in this research
folder, not the repository root:

```sh
pnpm install --frozen-lockfile
pnpm test
pnpm typecheck
pnpm audit --prod --audit-level high
pnpm start:built
```

The local server listens on **127.0.0.1:3001/mcp**. For a different
non-privileged port, set `PORT` before starting. Keep this process in the
foreground and stop it with Ctrl+C. It accepts CORS only from the local
reference-host origin (port 8080); the sandbox origin (port 8081) and
external origins are denied.

For the official MCP Apps example host, pin upstream source to **exact**
Git commit `ea3e9d0e624a20bc1c51310292f09d9b8ed17161` of
`modelcontextprotocol/ext-apps` (basic-host v2.1.0). Clone it **outside**
this repository and check out that commit. Install its dependencies with
`npm ci --ignore-scripts`, build the root library using its documented
Bun tooling, then `npm --prefix examples/basic-host run build`. Start
`examples/basic-host/serve.ts` using a compatible global Bun installation.
Do not copy upstream host/build assets into this repository.

Configure the host to use only `http://127.0.0.1:3001/mcp` (its
`SERVERS` JSON environment variable). Then open `http://localhost:8080`
in a browser, call `review_kicad_fixture`, and use the native severity
filters in the sandbox iframe. Input examples: `{}`,
`{"variant":"schematic-erc"}`, `{"variant":"empty"}`.
The host and sandbox run on ports 8080 and 8081 respectively.

**Windows reference-host build note:** the pinned upstream npm dependency
tree can expose a platform-incompatible local `node_modules/.bin/bun`
binary on Windows. Using an installed compatible **global Bun 1.4.4**
explicitly, with the upstream `node_modules/.bin` directory on PATH for
`tsc`, allowed the upstream build to complete. This is an upstream
test-host setup detail, not a reason to modify the KiCad MCP production
dependencies.

The environment-independent Python isolation regression can be run with
`python -m pytest -q --noconftest tests/unit/test_mcp_apps_research_isolation.py`
from the repository root. The normal Python integration suite requires
the repository-pinned uv/Opentelemetry dependency environment.

## Security and evidence

- Exactly one tool and one resource, with UI visibility limited to the model.
- No scripts or HTML from fixture fields: findings are DOM **textContent**.
- CSP resource domain lists are empty and no browser permissions requested.
- Payloads and findings are bounded and validated; invalid results show a
  safe error state and ordinary MCP callers retain readable text.
- The reference host enforces a separate sandbox origin, but its own default
  script CSP is permissive. See the limitation in the acceptance report.

**Actual named-host results and precise limitations:**
[Reference-host acceptance evidence](../../../docs/evidence/mcp-apps/issue-1220-reference-host.md).

This research proof does not certify other conversational hosts or authorize
enabling MCP Apps in the production server. Production adoption remains a
separate PR and explicit trust-boundary decision. Stop the temporary host
and server and verify local ports are closed after testing.
